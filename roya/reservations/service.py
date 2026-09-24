import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.notifications.service import NotificationService
from .policy import cancellation_policy_view


class ReservationService:
    def create(self,user_id,payload,idempotency_key):
        if not idempotency_key or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        params=(user_id,str(payload.property_id),str(payload.room_type_id),str(payload.rate_plan_id),payload.check_in,payload.check_out,payload.quantity,payload.adults,payload.children,payload.guest_name,str(payload.guest_email),payload.guest_phone,payload.guarantee_type,idempotency_key)
        try:
            with db_connection() as conn:
                row=conn.execute(
                    """select * from create_reservation(%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s::date,%s::date,%s::integer,%s::integer,%s::integer,%s::text,%s::text,%s::text,%s::text,%s::text)""",
                    params,
                ).fetchone(); conn.commit()
        except Exception as exc:
            message=str(exc)
            if "BOOKING_CONFLICT" in message:
                raise RoyaError("BOOKING_CONFLICT","One or more selected rooms are no longer available.",409) from exc
            if "RATE_NOT_AVAILABLE" in message:
                raise RoyaError("RATE_NOT_FOUND","The selected rate is no longer available.",409) from exc
            if "CAPACITY_EXCEEDED" in message:
                raise RoyaError("VALIDATION_ERROR","Guest count exceeds the room capacity.",422) from exc
            raise
        if row and not row.get("idempotent"):
            NotificationService().notify_reservation_created(str(row["reservation_id"]))
        return row

    def get_for_user(self,reservation_id,user_id):
        with db_connection() as conn:
            row=conn.execute(
                """select r.*,p.name property_name,p.check_in_time,
                          rt.name room_type_name,rp.name rate_plan_name,
                          rp.refundable,rp.cancellation_policy,
                          (select rf.status from refunds rf where rf.reservation_id=r.id order by rf.created_at desc limit 1) refund_status,
                          (select rf.amount_minor from refunds rf where rf.reservation_id=r.id order by rf.created_at desc limit 1) refund_amount_minor
                   from reservations r join properties p on p.id=r.property_id
                   join reservation_items ri on ri.reservation_id=r.id
                   join room_types rt on rt.id=ri.room_type_id join rate_plans rp on rp.id=ri.rate_plan_id
                   where r.id=%s and r.user_id=%s""",(reservation_id,user_id)
            ).fetchone()
        if not row:
            raise RoyaError("NOT_FOUND","Reservation not found.",404)
        result=dict(row)
        result["cancellation_policy_view"]=cancellation_policy_view(
            refundable=bool(row["refundable"]),
            policy=row["cancellation_policy"] or {},
            check_in=row["check_in"],
            check_in_time=row["check_in_time"],
        )
        return result

    def cancel(self,reservation_id,user_id,reason):
        with db_connection() as conn:
            reservation=conn.execute(
                "select id,status,amount_paid_minor,payment_status from reservations where id=%s and user_id=%s",
                (reservation_id,user_id),
            ).fetchone()
        if not reservation:
            raise RoyaError("NOT_FOUND","Reservation not found.",404)
        if int(reservation["amount_paid_minor"] or 0)>0:
            raise RoyaError(
                "REFUND_REVIEW_REQUIRED",
                "This reservation has a recorded payment and cannot be cancelled automatically yet. Contact the property or iRoya support so the refund can be reviewed first.",
                409,
            )
        try:
            with db_connection() as conn:
                row=conn.execute(
                    "select * from cancel_reservation(%s::uuid,%s::uuid,%s::text)",
                    (reservation_id,user_id,reason or "Guest cancelled"),
                ).fetchone(); conn.commit()
        except Exception as exc:
            if "RESERVATION_NOT_CANCELLABLE" in str(exc):
                raise RoyaError("RESERVATION_NOT_CANCELLABLE","This reservation can no longer be cancelled online.",409) from exc
            raise
        return row

    def list_for_partner(self,user_id,property_id=None,limit=100):
        params=[user_id]; where=["om.user_id=%s","om.status='active'"]
        if property_id:
            where.append("r.property_id=%s"); params.append(property_id)
        params.append(limit)
        with db_connection() as conn:
            rows=list(conn.execute(
                f"""select r.id,r.reference,r.property_id,p.name property_name,r.guest_name,r.guest_email,
                           r.check_in,r.check_out,r.nights,r.total_price_minor,r.amount_paid_minor,r.currency,r.status,
                           r.payment_status,r.guarantee_type,r.expires_at,r.created_at
                    from reservations r
                    join properties p on p.id=r.property_id
                    join organization_members om on om.organization_id=r.organization_id
                    where {' and '.join(where)}
                    order by case when r.status='pending_confirmation' then 0 else 1 end,r.created_at desc
                    limit %s""",tuple(params)
            ).fetchall())
        return rows

    def partner_decide(self,reservation_id,user_id,decision,reason=None):
        approve=decision=="approve"
        try:
            with db_connection() as conn:
                with conn.transaction():
                    access=conn.execute(
                        """select r.organization_id,r.property_id,r.reference,r.status,om.role
                           from reservations r join organization_members om on om.organization_id=r.organization_id
                           where r.id=%s and om.user_id=%s and om.status='active' for update of r""",
                        (reservation_id,user_id),
                    ).fetchone()
                    if not access:
                        raise RoyaError("NOT_FOUND","Reservation not found.",404)
                    if access["role"] not in {"owner","manager","reservations"}:
                        raise RoyaError("FORBIDDEN","Your organization role cannot decide this reservation.",403)
                    row=conn.execute(
                        "select * from partner_decide_reservation(%s::uuid,%s::boolean,%s::text)",
                        (reservation_id,approve,reason),
                    ).fetchone()
                    conn.execute(
                        """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                           values(%s,%s,%s,%s,'reservation',%s,%s::jsonb,%s::jsonb)""",
                        (user_id,access["organization_id"],access["property_id"],
                         "reservation.approved" if approve else "reservation.rejected",reservation_id,
                         json.dumps({"status":access["status"]}),json.dumps({"status":row["status"]},default=str)),
                    )
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "RESERVATION_NOT_DECIDABLE" in message:
                raise RoyaError("RESERVATION_NOT_DECIDABLE","This reservation is not awaiting property approval.",409) from exc
            if "RESERVATION_EXPIRED" in message:
                raise RoyaError("RESERVATION_EXPIRED","This approval window has expired.",409) from exc
            if "BOOKING_CONFLICT" in message:
                raise RoyaError("BOOKING_CONFLICT","Held inventory is no longer available.",409) from exc
            raise
        NotificationService().notify_guest_decision(reservation_id,row["status"])
        return row


    def partner_transition(self,reservation_id,user_id,target_status):
        allowed={
            "confirmed":{"checked_in","no_show"},
            "checked_in":{"checked_out"},
        }
        with db_connection() as conn:
            with conn.transaction():
                access=conn.execute(
                    """select r.id,r.organization_id,r.property_id,r.reference,r.status,r.check_in,r.check_out,
                              om.role,current_date today
                       from reservations r
                       join organization_members om on om.organization_id=r.organization_id
                       where r.id=%s and om.user_id=%s and om.status='active'
                       for update of r""",
                    (reservation_id,user_id),
                ).fetchone()
                if not access:
                    raise RoyaError("NOT_FOUND","Reservation not found.",404)
                if access["role"] not in {"owner","manager","reservations"}:
                    raise RoyaError("FORBIDDEN","Your organization role cannot manage this stay.",403)
                if target_status not in allowed.get(access["status"],set()):
                    raise RoyaError(
                        "INVALID_RESERVATION_TRANSITION",
                        f"Reservation cannot move from {access['status']} to {target_status}.",
                        409,
                    )
                if target_status in {"checked_in","no_show"} and access["today"]<access["check_in"]:
                    raise RoyaError(
                        "STAY_NOT_STARTED",
                        "This stay cannot be checked in or marked no-show before its check-in date.",
                        409,
                    )

                if target_status=="checked_in":
                    row=conn.execute(
                        """update reservations set status='checked_in',checked_in_at=coalesce(checked_in_at,now()),
                                  updated_at=now() where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()
                elif target_status=="checked_out":
                    row=conn.execute(
                        """update reservations set status='checked_out',checked_out_at=coalesce(checked_out_at,now()),
                                  updated_at=now() where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()
                else:
                    row=conn.execute(
                        """update reservations set status='no_show',updated_at=now()
                           where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()

                conn.execute(
                    """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                       values(%s,%s,%s,%s,'reservation',%s,%s::jsonb,%s::jsonb)""",
                    (
                        user_id,access["organization_id"],access["property_id"],
                        "reservation."+target_status,reservation_id,
                        json.dumps({"status":access["status"]}),
                        json.dumps({"status":target_status},default=str),
                    ),
                )
        NotificationService().notify_guest_status(reservation_id,target_status)
        return row
