import hashlib
import json
import uuid
from flask import current_app

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from .paystack import PaystackProvider


class PaymentService:
    def initialize(self,reservation_id,user_id,idempotency_key):
        if not idempotency_key:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        with db_connection() as conn:
            reservation=conn.execute(
                """select r.id,r.reference,r.total_price_minor,r.amount_due_minor,r.currency,r.guest_email,r.status,r.payment_status
                   from reservations r where r.id=%s and r.user_id=%s""",(reservation_id,user_id)
            ).fetchone()
            if not reservation:
                raise RoyaError("NOT_FOUND","Reservation not found.",404)
            if reservation["status"] in {"cancelled","expired","checked_out"}:
                raise RoyaError("RESERVATION_NOT_PAYABLE","This reservation cannot be paid.",409)
            existing=conn.execute("select response_json from idempotency_keys where user_id=%s and scope='payment_init' and key=%s",(user_id,idempotency_key)).fetchone()
            if existing and existing["response_json"]:
                return existing["response_json"]
            amount=int(reservation["amount_due_minor"])
            if amount<=0:
                raise RoyaError("RESERVATION_NOT_PAYABLE","There is no outstanding online payment for this reservation.",409)
            provider_reference=f"roya_{reservation['reference']}_{uuid.uuid4().hex[:10]}"

        provider=PaystackProvider()
        data=provider.initialize_payment(
            amount_minor=amount,email=reservation["guest_email"],reference=provider_reference,
            callback_url=f"{current_app.config['APP_URL'].rstrip('/')}/payment/callback",
            metadata={"reservation_id":str(reservation["id"]),"reservation_reference":reservation["reference"]},
        )
        response_payload={"provider":"paystack","reference":provider_reference,"authorization_url":data.get("authorization_url"),"access_code":data.get("access_code"),"amount_minor":amount,"currency":reservation["currency"]}
        with db_connection() as conn:
            with conn.transaction():
                conn.execute(
                    """insert into payment_transactions(reservation_id,provider,provider_reference,amount_minor,currency,status,raw_payload)
                       values(%s,'paystack',%s,%s,%s,'initiated',%s::jsonb) on conflict(provider_reference) do nothing""",
                    (reservation_id,provider_reference,amount,reservation["currency"],json.dumps(data)),
                )
                conn.execute(
                    """insert into idempotency_keys(user_id,scope,key,response_json) values(%s,'payment_init',%s,%s::jsonb)
                       on conflict(user_id,scope,key) do update set response_json=excluded.response_json""",
                    (user_id,idempotency_key,json.dumps(response_payload)),
                )
        return response_payload

    def process_paystack_webhook(self,raw_body,signature):
        provider=PaystackProvider()
        if not provider.verify_webhook(raw_body,signature):
            raise RoyaError("INVALID_WEBHOOK_SIGNATURE","Invalid webhook signature.",401)
        payload=json.loads(raw_body.decode("utf-8")); event=payload.get("event","unknown"); data=payload.get("data") or {}
        reference=data.get("reference"); fingerprint=hashlib.sha256(raw_body).hexdigest()
        with db_connection() as conn:
            with conn.transaction():
                inserted=conn.execute(
                    """insert into payment_webhook_events(provider,event_key,event_type,payload_json,signature_valid,processing_status)
                       values('paystack',%s,%s,%s::jsonb,true,'received')
                       on conflict(provider,event_key) do nothing returning id""",
                    (fingerprint,event,json.dumps(payload)),
                ).fetchone()
                if not inserted:
                    return {"duplicate":True}
                if event=="charge.success" and reference:
                    row=conn.execute("select * from record_successful_payment(%s::text,%s::bigint,%s::jsonb)",(reference,int(data.get("amount") or 0),json.dumps(data))).fetchone()
                    conn.execute("update payment_webhook_events set processing_status='processed',processed_at=now() where id=%s",(inserted["id"],))
                    return {"processed":True,"reference":reference,"result":row}
                conn.execute("update payment_webhook_events set processing_status='ignored',processed_at=now() where id=%s",(inserted["id"],))
                return {"processed":False,"ignored":True,"event":event}

    def reconcile_pending(self,limit=50):
        provider=PaystackProvider()
        with db_connection() as conn:
            rows=list(conn.execute(
                """select provider_reference from payment_transactions
                   where provider='paystack' and status in ('initiated','pending') and created_at < now()-interval '5 minutes'
                   order by created_at asc limit %s""",(limit,)
            ).fetchall())
        reconciled=0
        for row in rows:
            data=provider.verify_payment(row["provider_reference"])
            if data.get("status")=="success":
                with db_connection() as conn:
                    conn.execute("select * from record_successful_payment(%s::text,%s::bigint,%s::jsonb)",(row["provider_reference"],int(data.get("amount") or 0),json.dumps(data))); conn.commit()
                reconciled+=1
        return {"checked":len(rows),"reconciled":reconciled}
