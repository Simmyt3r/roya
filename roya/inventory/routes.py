from datetime import date
from uuid import UUID
from flask import Blueprint, request
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import current_identity, login_required
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.response import ok
from roya.common.security import require_cron_secret
from roya.payments.service import PaymentService

bp=Blueprint("inventory",__name__)


class InventoryItem(BaseModel):
    date: date
    total_inventory: int = Field(ge=0,le=1000)
    price_override_minor: int|None = Field(default=None,gt=0)
    stop_sell: bool=False
    closed_to_arrival: bool=False
    closed_to_departure: bool=False
    min_stay: int=Field(default=1,ge=1,le=90)


class InventoryUpdate(BaseModel):
    room_type_id: UUID
    days: list[InventoryItem]=Field(min_length=1,max_length=366)


@bp.put("/api/v1/inventory")
@login_required
def update_inventory():
    try:
        body=InventoryUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid inventory details.",422,{"errors":exc.errors()}) from exc
    user=current_identity(required=True)
    with db_connection() as conn:
        access=conn.execute(
            """select om.role from room_types rt join properties p on p.id=rt.property_id
               join organization_members om on om.organization_id=p.organization_id
               where rt.id=%s and om.user_id=%s and om.status='active'""",(str(body.room_type_id),user.user_id)
        ).fetchone()
        if not access or access["role"] not in {"owner","manager","reservations"}:
            raise RoyaError("FORBIDDEN","You cannot manage this inventory.",403)
        with conn.transaction():
            for item in body.days:
                conn.execute(
                    """insert into inventory_days(room_type_id,date,total_inventory,price_override_minor,stop_sell,closed_to_arrival,closed_to_departure,min_stay,source)
                       values(%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                       on conflict(room_type_id,date) do update set
                         total_inventory=excluded.total_inventory,price_override_minor=excluded.price_override_minor,
                         stop_sell=excluded.stop_sell,closed_to_arrival=excluded.closed_to_arrival,
                         closed_to_departure=excluded.closed_to_departure,min_stay=excluded.min_stay,
                         version=inventory_days.version+1,source='manual',updated_at=now()
                       where inventory_days.sold_inventory+inventory_days.held_inventory <= excluded.total_inventory""",
                    (str(body.room_type_id),item.date,item.total_inventory,item.price_override_minor,item.stop_sell,item.closed_to_arrival,item.closed_to_departure,item.min_stay),
                )
    return ok({"updated":len(body.days)})


@bp.get("/api/internal/cron/expire-holds")
@require_cron_secret
def expire_holds():
    with db_connection() as conn:
        row=conn.execute("select * from expire_reservation_holds()").fetchone(); conn.commit()
    return ok(row or {"expired":0})


@bp.get("/api/internal/cron/payment-reconcile")
@require_cron_secret
def reconcile_payments():
    return ok(PaymentService().reconcile_pending())


@bp.get("/api/internal/cron/send-reminders")
@require_cron_secret
def reminder_scan():
    from roya.notifications.service import NotificationService
    from roya.notifications.smtp import SmtpNotificationAdapter
    with db_connection() as conn:
        rows=list(conn.execute(
            """select id,reference,guest_email,check_in from reservations
               where status='confirmed' and check_in=current_date+1 and reminder_sent_at is null limit 100"""
        ).fetchall())
    service=NotificationService(SmtpNotificationAdapter()); sent=0
    for r in rows:
        result=service.send(recipient=r["guest_email"],subject=f"Your Roya stay {r['reference']} is tomorrow",body=f"Reminder: your reservation {r['reference']} checks in on {r['check_in']}.")
        if result.get("sent"):
            with db_connection() as conn:
                conn.execute("update reservations set reminder_sent_at=now() where id=%s and reminder_sent_at is null",(r["id"],)); conn.commit()
            sent+=1
    return ok({"pending_reminders":len(rows),"sent":sent})
