from datetime import date, timedelta

from flask import Blueprint

from roya.common.db import db_connection
from roya.common.response import ok
from roya.common.security import require_cron_secret
from roya.notifications.service import NotificationService
from roya.notifications.smtp import SmtpNotificationAdapter
from roya.payments.service import PaymentService

bp = Blueprint("internal", __name__)


@bp.get("/api/internal/cron/expire-holds")
@require_cron_secret
def expire_holds():
    """Fallback/manual trigger. Supabase Cron is the primary scheduler."""
    with db_connection() as conn:
        row = conn.execute("select expired from expire_reservation_holds()").fetchone()
        conn.commit()
    return ok({"expired": int(row["expired"] if row else 0)})


@bp.get("/api/internal/cron/payment-reconcile")
@require_cron_secret
def payment_reconcile():
    return ok(PaymentService().reconcile_pending())


@bp.get("/api/internal/cron/send-notifications")
@require_cron_secret
def send_notifications():
    notifier=NotificationService(SmtpNotificationAdapter())
    return ok(notifier.deliver_pending_emails(limit=100))


@bp.get("/api/internal/cron/send-reminders")
@require_cron_secret
def send_reminders():
    queued_delivery=NotificationService(SmtpNotificationAdapter()).deliver_pending_emails(limit=100)
    target_date = date.today() + timedelta(days=1)
    with db_connection() as conn:
        reservations = list(
            conn.execute(
                """select id,reference,guest_name,guest_email,check_in,check_out
                   from reservations
                   where status='confirmed'
                     and check_in=%s
                     and reminder_sent_at is null
                   order by created_at asc
                   limit 100""",
                (target_date,),
            ).fetchall()
        )

    notifier = NotificationService(SmtpNotificationAdapter())
    sent = 0
    skipped = 0
    failed = 0

    for reservation in reservations:
        try:
            result = notifier.send(
                recipient=reservation["guest_email"],
                subject=f"Roya booking reminder: {reservation['reference']}",
                body=(
                    f"Hello {reservation['guest_name']},\n\n"
                    f"This is a reminder that your Roya booking "
                    f"{reservation['reference']} starts on {reservation['check_in']}. "
                    f"Your check-out date is {reservation['check_out']}.\n\n"
                    "Please keep your reservation reference available at check-in."
                ),
            )
        except Exception:
            failed += 1
            continue

        if not result.get("sent"):
            skipped += 1
            continue

        with db_connection() as conn:
            updated = conn.execute(
                """update reservations
                   set reminder_sent_at=now(),updated_at=now()
                   where id=%s and reminder_sent_at is null
                   returning id""",
                (reservation["id"],),
            ).fetchone()
            if updated:
                conn.execute(
                    """insert into notifications(
                           reservation_id,channel,event_type,recipient,status,payload,sent_at
                       ) values(%s,'email','reservation.check_in_reminder',%s,'sent','{}'::jsonb,now())""",
                    (reservation["id"], reservation["guest_email"]),
                )
                conn.commit()
                sent += 1

    return ok(
        {
            "target_date": target_date.isoformat(),
            "candidates": len(reservations),
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
            "queued_delivery":queued_delivery,
        }
    )
