from flask import current_app

from roya.common.db import db_connection
from roya.common.integrations import integration_status


def _empty_snapshot(configured=False):
    return {
        "database_configured":configured,
        "database_reachable":False,
        "core_ready":False,
        "release_ready":False,
        "booking_ready":False,
        "core_blockers":[],
        "release_blockers":[],
        "blockers":[],
        "deferred":[],
        "schema":{
            "create_reservation":False,
            "record_successful_payment":False,
            "cancel_reservation":False,
            "expire_reservation_holds":False,
            "partner_decide_reservation":False,
        },
        "integrations":{
            "payments_configured":bool(current_app.config.get("PAYSTACK_SECRET_KEY")),
            "notifications_configured":bool(
                current_app.config.get("SMTP_HOST") and current_app.config.get("SMTP_FROM")
            ),
            "storage_admin_configured":bool(current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")),
        },
        "operations":{
            "inventory_anomalies":None,
            "overdue_holds":None,
            "stuck_payments":None,
            "stuck_refunds":None,
            "failed_email_24h":None,
            "operations_scan_active":False,
            "operations_scan_last_success":None,
        },
        "activity":{
            "last_reservation_at":None,
            "last_confirmed_booking_at":None,
            "last_successful_payment_at":None,
        },
    }


def booking_readiness_snapshot():
    configured=bool(current_app.config.get("DATABASE_URL"))
    snapshot=_empty_snapshot(configured)
    if not configured:
        return snapshot

    try:
        with db_connection() as conn:
            schema=conn.execute(
                """select
                     to_regprocedure(
                       'public.create_reservation(uuid,uuid,uuid,uuid,date,date,integer,integer,integer,text,text,text,text,text)'
                     ) is not null create_reservation,
                     to_regprocedure(
                       'public.record_successful_payment(text,bigint,jsonb)'
                     ) is not null record_successful_payment,
                     to_regprocedure(
                       'public.cancel_reservation(uuid,uuid,text)'
                     ) is not null cancel_reservation,
                     to_regprocedure(
                       'public.expire_reservation_holds()'
                     ) is not null expire_reservation_holds,
                     to_regprocedure(
                       'public.partner_decide_reservation(uuid,boolean,text)'
                     ) is not null partner_decide_reservation"""
            ).fetchone()

            operations=conn.execute(
                """select
                     (select count(*) from inventory_days
                        where held_inventory<0
                           or sold_inventory<0
                           or held_inventory+sold_inventory>total_inventory) inventory_anomalies,
                     (select count(*) from reservations
                        where status in ('held','pending_confirmation')
                          and expires_at is not null
                          and expires_at<=now()) overdue_holds,
                     (select count(*) from payment_transactions
                        where status in ('initiated','pending')
                          and created_at<now()-interval '10 minutes') stuck_payments,
                     (select count(*) from refunds
                        where status='processing'
                          and updated_at<now()-interval '10 minutes') stuck_refunds,
                     (select count(*) from notifications
                        where channel='email'
                          and status='failed'
                          and created_at>=now()-interval '24 hours') failed_email_24h"""
            ).fetchone()

            activity=conn.execute(
                """select
                     (select max(created_at) from reservations) last_reservation_at,
                     (select max(confirmed_at) from reservations where confirmed_at is not null)
                       last_confirmed_booking_at,
                     (select max(paid_at) from payment_transactions
                        where status='successful' and paid_at is not null)
                       last_successful_payment_at"""
            ).fetchone()

            cron_row=conn.execute(
                """select
                     j.active,
                     max(r.end_time) filter(where r.status='succeeded') last_success
                   from cron.job j
                   left join cron.job_run_details r on r.jobid=j.jobid
                   where j.jobname='roya-operations-scan'
                   group by j.active
                   limit 1"""
            ).fetchone()

        snapshot["database_reachable"]=True
        snapshot["schema"]={key:bool(schema[key]) for key in snapshot["schema"]}
        snapshot["operations"].update({
            "inventory_anomalies":int(operations["inventory_anomalies"] or 0),
            "overdue_holds":int(operations["overdue_holds"] or 0),
            "stuck_payments":int(operations["stuck_payments"] or 0),
            "stuck_refunds":int(operations["stuck_refunds"] or 0),
            "failed_email_24h":int(operations["failed_email_24h"] or 0),
            "operations_scan_active":bool(cron_row and cron_row["active"]),
            "operations_scan_last_success":cron_row["last_success"] if cron_row else None,
        })
        snapshot["activity"].update(dict(activity or {}))

        paystack=integration_status("paystack")
        smtp=integration_status("smtp")
        snapshot["integrations"]={
            "payments_configured":bool(paystack["configured"]),
            "payments_mode":paystack.get("mode") or "",
            "notifications_configured":bool(smtp["configured"]),
            "storage_admin_configured":bool(current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")),
        }

        core_blockers=[]
        if not snapshot["database_reachable"]:
            core_blockers.append("database_unreachable")
        if not all(snapshot["schema"].values()):
            core_blockers.append("booking_schema_incomplete")
        if snapshot["operations"]["inventory_anomalies"] not in (0,None):
            core_blockers.append("inventory_anomalies")
        if snapshot["operations"]["overdue_holds"] not in (0,None):
            core_blockers.append("overdue_reservation_holds")
        if not snapshot["operations"]["operations_scan_active"]:
            core_blockers.append("operations_scan_inactive")

        release_blockers=list(core_blockers)
        deferred=[]
        if not snapshot["integrations"]["payments_configured"]:
            release_blockers.append("paystack_not_configured")
            deferred.append("paystack_configuration")

        snapshot["core_blockers"]=core_blockers
        snapshot["release_blockers"]=release_blockers
        snapshot["blockers"]=release_blockers
        snapshot["deferred"]=deferred
        snapshot["core_ready"]=not core_blockers
        snapshot["release_ready"]=not release_blockers
        snapshot["booking_ready"]=snapshot["release_ready"]
        return snapshot
    except Exception:
        current_app.logger.exception("Booking readiness check failed")
        return snapshot
