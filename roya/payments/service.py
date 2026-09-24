import hashlib
import json
import uuid
from flask import current_app

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.notifications.service import NotificationService
from roya.reservations.policy import cancellation_policy_view
from .paystack import PaystackProvider


class PaymentService:
    def initialize(self,reservation_id,user_id,idempotency_key):
        if not idempotency_key:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        with db_connection() as conn:
            reservation=conn.execute(
                """select r.id,r.reference,r.total_price_minor,r.amount_due_minor,r.amount_paid_minor,
                          r.currency,r.guest_email,r.status,r.payment_status
                   from reservations r where r.id=%s and r.user_id=%s""",(reservation_id,user_id)
            ).fetchone()
            if not reservation:
                raise RoyaError("NOT_FOUND","Reservation not found.",404)
            if reservation["status"] in {"cancelled","expired","checked_out"}:
                raise RoyaError("RESERVATION_NOT_PAYABLE","This reservation cannot be paid.",409)
            existing=conn.execute(
                "select response_json from idempotency_keys where user_id=%s and scope='payment_init' and key=%s",
                (user_id,idempotency_key),
            ).fetchone()
            if existing and existing["response_json"]:
                return existing["response_json"]
            amount=max(0,int(reservation["amount_due_minor"])-int(reservation["amount_paid_minor"] or 0))
            if amount<=0:
                raise RoyaError("RESERVATION_NOT_PAYABLE","There is no outstanding online payment for this reservation.",409)
            provider_reference=f"roya_{reservation['reference']}_{uuid.uuid4().hex[:10]}"

        provider=PaystackProvider()
        data=provider.initialize_payment(
            amount_minor=amount,email=reservation["guest_email"],reference=provider_reference,
            callback_url=f"{current_app.config['APP_URL'].rstrip('/')}/payment/callback",
            metadata={"reservation_id":str(reservation["id"]),"reservation_reference":reservation["reference"]},
        )
        response_payload={
            "provider":"paystack","reference":provider_reference,
            "authorization_url":data.get("authorization_url"),"access_code":data.get("access_code"),
            "amount_minor":amount,"currency":reservation["currency"],
        }
        with db_connection() as conn:
            with conn.transaction():
                conn.execute(
                    """insert into payment_transactions(reservation_id,provider,provider_reference,amount_minor,currency,status,raw_payload)
                       values(%s,'paystack',%s,%s,%s,'initiated',%s::jsonb)
                       on conflict(provider_reference) do nothing""",
                    (reservation_id,provider_reference,amount,reservation["currency"],json.dumps(data)),
                )
                conn.execute(
                    """insert into idempotency_keys(user_id,scope,key,response_json)
                       values(%s,'payment_init',%s,%s::jsonb)
                       on conflict(user_id,scope,key) do update set response_json=excluded.response_json""",
                    (user_id,idempotency_key,json.dumps(response_payload)),
                )
        return response_payload

    def verify_and_reconcile(self,reference,user_id):
        if not reference:
            raise RoyaError("PAYMENT_REFERENCE_REQUIRED","Payment reference is required.",400)
        with db_connection() as conn:
            tx=conn.execute(
                """select pt.provider_reference,pt.amount_minor,pt.status,
                          r.id reservation_id,r.reference reservation_reference,r.payment_status
                   from payment_transactions pt
                   join reservations r on r.id=pt.reservation_id
                   where pt.provider='paystack' and pt.provider_reference=%s and r.user_id=%s""",
                (reference,user_id),
            ).fetchone()
        if not tx:
            raise RoyaError("PAYMENT_NOT_FOUND","Payment transaction not found.",404)
        if tx["status"]=="successful":
            NotificationService().notify_payment_success(str(tx["reservation_id"]))
            return {"verified":True,"reservation_id":tx["reservation_id"],
                    "reservation_reference":tx["reservation_reference"],"payment_status":tx["payment_status"]}

        data=PaystackProvider().verify_payment(reference)
        if data.get("status")!="success":
            return {"verified":False,"reservation_id":tx["reservation_id"],
                    "reservation_reference":tx["reservation_reference"],
                    "provider_status":data.get("status") or "pending"}

        with db_connection() as conn:
            row=conn.execute(
                "select * from record_successful_payment(%s::text,%s::bigint,%s::jsonb)",
                (reference,int(data.get("amount") or 0),json.dumps(data)),
            ).fetchone()
            conn.commit()
        NotificationService().notify_payment_success(str(row["reservation_id"]))
        return {"verified":True,"reservation_id":row["reservation_id"],
                "reservation_reference":tx["reservation_reference"],
                "reservation_status":row["reservation_status"],"payment_status":row["payment_status"]}

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
                    row=conn.execute(
                        "select * from record_successful_payment(%s::text,%s::bigint,%s::jsonb)",
                        (reference,int(data.get("amount") or 0),json.dumps(data)),
                    ).fetchone()
                    conn.execute("update payment_webhook_events set processing_status='processed',processed_at=now() where id=%s",(inserted["id"],))
                    return {"processed":True,"reference":reference,"result":row}
                if event in {"refund.pending","refund.processing","refund.needs-attention","refund.failed","refund.processed"}:
                    result=self.apply_refund_webhook(conn,event,data)
                    conn.execute("update payment_webhook_events set processing_status='processed',processed_at=now() where id=%s",(inserted["id"],))
                    return {"processed":True,"event":event,"result":result}
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
                    settled=conn.execute(
                        "select * from record_successful_payment(%s::text,%s::bigint,%s::jsonb)",
                        (row["provider_reference"],int(data.get("amount") or 0),json.dumps(data)),
                    ).fetchone()
                    conn.commit()
                if settled:
                    NotificationService().notify_payment_success(str(settled["reservation_id"]))
                reconciled+=1
        return {"checked":len(rows),"reconciled":reconciled}


    def request_refund(self,reservation_id,user_id,reason):
        reason=(reason or "Guest requested cancellation and refund").strip()[:1000]
        with db_connection() as conn:
            with conn.transaction():
                reservation=conn.execute(
                    """select r.id,r.user_id,r.organization_id,r.property_id,r.status,r.payment_status,
                              r.amount_paid_minor,r.currency,r.check_in,p.check_in_time,
                              rp.refundable,rp.cancellation_policy
                       from reservations r
                       join properties p on p.id=r.property_id
                       join reservation_items ri on ri.reservation_id=r.id
                       join rate_plans rp on rp.id=ri.rate_plan_id
                       where r.id=%s and r.user_id=%s
                       order by ri.id
                       limit 1
                       for update of r""",
                    (reservation_id,user_id),
                ).fetchone()
                if not reservation:
                    raise RoyaError("NOT_FOUND","Reservation not found.",404)
                if reservation["status"] not in {"held","pending_confirmation","confirmed"}:
                    raise RoyaError("RESERVATION_NOT_CANCELLABLE","This reservation can no longer be cancelled online.",409)
                if int(reservation["amount_paid_minor"] or 0)<=0:
                    raise RoyaError("REFUND_NOT_REQUIRED","This reservation has no recorded payment to refund.",409)

                policy_view=cancellation_policy_view(
                    refundable=bool(reservation["refundable"]),
                    policy=reservation["cancellation_policy"] or {},
                    check_in=reservation["check_in"],
                    check_in_time=reservation["check_in_time"],
                )
                if not policy_view["refund_eligible"]:
                    raise RoyaError(
                        "REFUND_NOT_ELIGIBLE",
                        policy_view["summary"]+" Automatic refunds are unavailable for this cancellation.",
                        409,
                        {"policy":policy_view},
                    )

                active=conn.execute(
                    """select id,status from refunds
                       where reservation_id=%s and status in ('requested','processing','successful')
                       order by created_at desc limit 1""",
                    (reservation_id,),
                ).fetchone()
                if active:
                    raise RoyaError("REFUND_ALREADY_REQUESTED","A refund request already exists for this reservation.",409)

                transactions=list(conn.execute(
                    """select id,provider_reference,amount_minor,currency
                       from payment_transactions
                       where reservation_id=%s and provider='paystack' and status='successful'
                       order by paid_at,created_at""",
                    (reservation_id,),
                ).fetchall())
                if not transactions:
                    raise RoyaError("PAYMENT_NOT_FOUND","No successful Paystack payment was found for this reservation.",409)

                remaining=int(reservation["amount_paid_minor"])
                created=[]
                for tx in transactions:
                    if remaining<=0:
                        break
                    amount=min(int(tx["amount_minor"]),remaining)
                    row=conn.execute(
                        """insert into refunds(reservation_id,payment_transaction_id,amount_minor,currency,status,reason,created_by_user_id)
                           values(%s,%s,%s,%s,'requested',%s,%s)
                           returning id,reservation_id,payment_transaction_id,amount_minor,currency,status,reason,created_at""",
                        (reservation_id,tx["id"],amount,tx["currency"],reason,user_id),
                    ).fetchone()
                    created.append(dict(row))
                    remaining-=amount

                if remaining>0:
                    raise RoyaError("REFUND_AMOUNT_MISMATCH","Recorded payments do not cover the refundable amount.",409)

                conn.execute(
                    """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json)
                       values(%s,%s,%s,'refund.requested','reservation',%s,%s::jsonb)""",
                    (user_id,reservation["organization_id"],reservation["property_id"],reservation_id,
                     json.dumps({"reason":reason,"amount_minor":int(reservation["amount_paid_minor"])})),
                )
        NotificationService().notify_refund_requested(str(reservation_id))
        return {"reservation_id":reservation_id,"status":"requested","refunds":created}

    def list_for_partner(self,user_id,limit=50):
        with db_connection() as conn:
            return list(conn.execute(
                """select rf.id,rf.reservation_id,rf.amount_minor,rf.currency,rf.status,rf.reason,rf.created_at,
                          r.reference reservation_reference,r.guest_name,r.guest_email,p.name property_name,
                          om.role member_role
                   from refunds rf
                   join reservations r on r.id=rf.reservation_id
                   join properties p on p.id=r.property_id
                   join organization_members om on om.organization_id=r.organization_id
                   where om.user_id=%s and om.status='active'
                     and rf.status in ('requested','processing')
                   order by case when rf.status='requested' then 0 else 1 end,rf.created_at asc
                   limit %s""",
                (user_id,limit),
            ).fetchall())

    def process_refund(self,refund_id,user_id):
        with db_connection() as conn:
            with conn.transaction():
                refund=conn.execute(
                    """select rf.*,pt.provider,pt.provider_reference transaction_reference,
                              r.organization_id,r.property_id,r.reference reservation_reference,
                              om.role member_role
                       from refunds rf
                       join payment_transactions pt on pt.id=rf.payment_transaction_id
                       join reservations r on r.id=rf.reservation_id
                       join organization_members om on om.organization_id=r.organization_id
                       where rf.id=%s and om.user_id=%s and om.status='active'
                       for update of rf""",
                    (refund_id,user_id),
                ).fetchone()
                if not refund:
                    raise RoyaError("NOT_FOUND","Refund request not found.",404)
                if refund["member_role"] not in {"owner","manager","finance"}:
                    raise RoyaError("FORBIDDEN","Only hotel owners, managers or finance staff can process refunds.",403)
                if refund["status"]!="requested":
                    raise RoyaError("REFUND_NOT_PROCESSABLE","This refund is not awaiting processing.",409)
                if refund["provider"]!="paystack":
                    raise RoyaError("REFUND_PROVIDER_UNSUPPORTED","This payment provider is not supported for automated refunds.",409)
                conn.execute("update refunds set status='processing',updated_at=now() where id=%s",(refund_id,))

        try:
            data=PaystackProvider().refund_payment(refund["transaction_reference"],int(refund["amount_minor"]))
        except Exception:
            # Keep processing: an indeterminate network failure must not create a duplicate refund on retry.
            raise

        provider_ref=str(data.get("id") or data.get("refund_reference") or "")
        provider_status=str(data.get("status") or "pending").lower()
        finalized=None
        with db_connection() as conn:
            with conn.transaction():
                conn.execute(
                    "update refunds set provider_reference=%s,updated_at=now() where id=%s",
                    (provider_ref or None,refund_id),
                )
                if provider_status=="processed":
                    finalized=self._finalize_refund(conn,refund_id,True,data)
                elif provider_status=="failed":
                    finalized=self._finalize_refund(conn,refund_id,False,data)
                conn.execute(
                    """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json)
                       values(%s,%s,%s,'refund.processing','refund',%s,%s::jsonb)""",
                    (user_id,refund["organization_id"],refund["property_id"],refund_id,
                     json.dumps({"provider_status":provider_status,"provider_reference":provider_ref},default=str)),
                )
        notification_status="successful" if provider_status=="processed" else ("failed" if provider_status=="failed" else "processing")
        NotificationService().notify_refund_status(
            str(refund["reservation_id"]),
            notification_status,
            (finalized or {}).get("payment_status"),
        )
        return {"refund_id":refund_id,"status":notification_status,"provider_status":provider_status}

    def _finalize_refund(self,conn,refund_id,successful,payload):
        refund=conn.execute(
            """select rf.*,pt.provider_reference transaction_reference,
                      r.user_id,r.organization_id,r.property_id,r.status reservation_status,
                      r.amount_paid_minor
               from refunds rf
               join payment_transactions pt on pt.id=rf.payment_transaction_id
               join reservations r on r.id=rf.reservation_id
               where rf.id=%s for update of rf""",
            (refund_id,),
        ).fetchone()
        if not refund:
            return None

        if not successful:
            conn.execute("update refunds set status='failed',updated_at=now() where id=%s",(refund_id,))
            return {"refund_id":refund_id,"status":"failed"}

        conn.execute(
            "update refunds set status='successful',updated_at=now() where id=%s",
            (refund_id,),
        )
        total_refunded=conn.execute(
            "select coalesce(sum(amount_minor),0) total from refunds where reservation_id=%s and status='successful'",
            (refund["reservation_id"],),
        ).fetchone()["total"]

        payment=conn.execute(
            "select amount_captured_minor from payments where reservation_id=%s for update",
            (refund["reservation_id"],),
        ).fetchone()
        captured=int(payment["amount_captured_minor"] if payment else refund["amount_paid_minor"])
        total_refunded=int(total_refunded or 0)
        payment_status="refunded" if captured>0 and total_refunded>=captured else "partially_refunded"

        conn.execute(
            """update payments set amount_refunded_minor=%s,status=%s,updated_at=now()
               where reservation_id=%s""",
            (min(total_refunded,captured),payment_status,refund["reservation_id"]),
        )
        conn.execute(
            "update reservations set payment_status=%s,updated_at=now() where id=%s",
            (payment_status,refund["reservation_id"]),
        )

        if payment_status=="refunded" and refund["reservation_status"] in {"held","pending_confirmation","confirmed"}:
            conn.execute(
                "select * from cancel_reservation(%s::uuid,%s::uuid,%s::text)",
                (refund["reservation_id"],refund["user_id"],"Cancellation completed after refund"),
            )
            conn.execute(
                "update reservations set payment_status='refunded',updated_at=now() where id=%s",
                (refund["reservation_id"],),
            )
        return {"refund_id":refund_id,"status":"successful","payment_status":payment_status}

    def apply_refund_webhook(self,conn,event,data):
        tx_reference=data.get("transaction_reference")
        if not tx_reference:
            return {"processed":False,"reason":"missing_transaction_reference"}
        amount=int(data.get("amount") or 0)
        refund=conn.execute(
            """select rf.id
               from refunds rf join payment_transactions pt on pt.id=rf.payment_transaction_id
               where pt.provider='paystack' and pt.provider_reference=%s
                 and rf.status in ('requested','processing') and (%s=0 or rf.amount_minor=%s)
               order by rf.created_at asc limit 1
               for update of rf""",
            (tx_reference,amount,amount),
        ).fetchone()
        if not refund:
            return {"processed":False,"reason":"refund_not_found"}

        provider_ref=data.get("refund_reference")
        if provider_ref:
            conn.execute("update refunds set provider_reference=%s,updated_at=now() where id=%s",(str(provider_ref),refund["id"]))

        if event=="refund.processed":
            return self._finalize_refund(conn,str(refund["id"]),True,data)
        if event=="refund.failed":
            return self._finalize_refund(conn,str(refund["id"]),False,data)

        conn.execute("update refunds set status='processing',updated_at=now() where id=%s",(refund["id"],))
        return {"refund_id":refund["id"],"status":"processing"}
