import hashlib
import json

from flask import current_app

from roya.notifications.service import NotificationService
from roya.common.db import db_connection


def operations_snapshot(limit=30):
    limit=max(1,min(int(limit),1000))
    with db_connection() as conn:
        counts=conn.execute(
            """select
              (select count(*) from payment_transactions
                 where status in ('initiated','pending')
                   and created_at<now()-interval '10 minutes') stuck_payments,
              (select count(*) from refunds
                 where status='processing'
                   and updated_at<now()-interval '10 minutes') stuck_refunds,
              (select count(*) from reservations
                 where status in ('held','pending_confirmation')
                   and expires_at is not null
                   and expires_at<=now()) overdue_holds,
              (select count(*) from reservations
                 where status in ('held','pending_confirmation')
                   and expires_at>now()
                   and expires_at<=now()+interval '30 minutes') expiring_holds,
              (select count(*) from notifications
                 where channel='email' and status='failed'
                   and created_at>=now()-interval '24 hours') failed_email_24h,
              (select count(*) from notifications
                 where channel='email' and status='queued'
                   and next_attempt_at<=now()
                   and created_at<now()-interval '15 minutes') overdue_email_queue,
              (select count(*) from inventory_days
                 where held_inventory<0
                    or sold_inventory<0
                    or held_inventory+sold_inventory>total_inventory) inventory_anomalies,
              (select count(*) from properties p
                 where p.status='active'
                   and p.verification_status='verified'
                   and not exists(
                     select 1
                     from room_types rt
                     join inventory_days i on i.room_type_id=rt.id
                     where rt.property_id=p.id
                       and rt.status='active'
                       and i.date>=current_date
                       and i.date<current_date+30
                       and i.stop_sell=false
                       and (i.total_inventory-i.held_inventory-i.sold_inventory)>0
                   )) active_hotels_without_30d_inventory"""
        ).fetchone()

        issues=list(conn.execute(
            """select *
               from (
                 select
                   'overdue_hold'::text kind,
                   'critical'::text severity,
                   'Reservation hold is overdue'::text title,
                   r.reference::text reference,
                   concat(p.name,' · expired ',to_char(r.expires_at,'YYYY-MM-DD HH24:MI'))::text detail,
                   r.expires_at occurred_at,
                   ('/admin/reservations/'||r.id::text)::text link
                 from reservations r
                 join properties p on p.id=r.property_id
                 where r.status in ('held','pending_confirmation')
                   and r.expires_at is not null
                   and r.expires_at<=now()

                 union all

                 select
                   'stuck_payment','critical','Payment needs reconciliation',
                   r.reference,
                   concat(pt.provider_reference,' · ',pt.status,' · ',to_char(pt.created_at,'YYYY-MM-DD HH24:MI')),
                   pt.created_at,
                   ('/admin/reservations/'||r.id::text)
                 from payment_transactions pt
                 join reservations r on r.id=pt.reservation_id
                 where pt.status in ('initiated','pending')
                   and pt.created_at<now()-interval '10 minutes'

                 union all

                 select
                   'stuck_refund','critical','Refund is still processing',
                   r.reference,
                   concat(rf.currency,' ',round(rf.amount_minor/100.0,2),' · updated ',to_char(rf.updated_at,'YYYY-MM-DD HH24:MI')),
                   rf.updated_at,
                   ('/admin/reservations/'||r.id::text)
                 from refunds rf
                 join reservations r on r.id=rf.reservation_id
                 where rf.status='processing'
                   and rf.updated_at<now()-interval '10 minutes'

                 union all

                 select
                   'expiring_hold','warning','Reservation hold expires soon',
                   r.reference,
                   concat(p.name,' · expires ',to_char(r.expires_at,'YYYY-MM-DD HH24:MI')),
                   r.expires_at,
                   null::text
                 from reservations r
                 join properties p on p.id=r.property_id
                 where r.status in ('held','pending_confirmation')
                   and r.expires_at>now()
                   and r.expires_at<=now()+interval '30 minutes'

                 union all

                 select
                   'failed_email','warning','Email delivery failed',
                   coalesce(r.reference,n.event_type),
                   concat(n.recipient,' · ',left(coalesce(n.last_error,'No provider error recorded'),180)),
                   n.created_at,
                   case when n.reservation_id is not null then '/admin/reservations/'||n.reservation_id::text else null::text end
                 from notifications n
                 left join reservations r on r.id=n.reservation_id
                 where n.channel='email'
                   and n.status='failed'
                   and n.created_at>=now()-interval '24 hours'

                 union all

                 select
                   'email_queue','warning','Email has waited too long',
                   coalesce(r.reference,n.event_type),
                   concat(n.recipient,' · attempts ',n.attempts),
                   n.created_at,
                   case when n.reservation_id is not null then '/admin/reservations/'||n.reservation_id::text else null::text end
                 from notifications n
                 left join reservations r on r.id=n.reservation_id
                 where n.channel='email'
                   and n.status='queued'
                   and n.next_attempt_at<=now()
                   and n.created_at<now()-interval '15 minutes'

                 union all

                 select
                   'inventory','critical','Inventory counters are inconsistent',
                   rt.name,
                   concat(p.name,' · ',i.date,' · held ',i.held_inventory,' · sold ',i.sold_inventory,' / total ',i.total_inventory),
                   i.updated_at,
                   null::text
                 from inventory_days i
                 join room_types rt on rt.id=i.room_type_id
                 join properties p on p.id=rt.property_id
                 where i.held_inventory<0
                    or i.sold_inventory<0
                    or i.held_inventory+i.sold_inventory>i.total_inventory

                 union all

                 select
                   'inventory_gap','warning','Verified hotel has no sellable inventory',
                   p.name,
                   concat(p.city,', ',p.state,' · next 30 days'),
                   p.updated_at,
                   null::text
                 from properties p
                 where p.status='active'
                   and p.verification_status='verified'
                   and not exists(
                     select 1
                     from room_types rt
                     join inventory_days i on i.room_type_id=rt.id
                     where rt.property_id=p.id
                       and rt.status='active'
                       and i.date>=current_date
                       and i.date<current_date+30
                       and i.stop_sell=false
                       and (i.total_inventory-i.held_inventory-i.sold_inventory)>0
                   )
               ) operational_issues
               order by
                 case severity when 'critical' then 0 else 1 end,
                 occurred_at asc
               limit %s""",
            (limit,),
        ).fetchall())

    count_map=dict(counts or {})
    critical_keys=("stuck_payments","stuck_refunds","overdue_holds","inventory_anomalies")
    warning_keys=("expiring_holds","failed_email_24h","overdue_email_queue","active_hotels_without_30d_inventory")
    critical=sum(int(count_map.get(key) or 0) for key in critical_keys)
    warning=sum(int(count_map.get(key) or 0) for key in warning_keys)
    return {
        "counts":count_map,
        "issues":[dict(row) for row in issues],
        "critical":critical,
        "warning":warning,
        "healthy":critical==0 and warning==0,
    }


def expire_overdue_holds():
    with db_connection() as conn:
        row=conn.execute("select expired from expire_reservation_holds()").fetchone()
        conn.commit()
    return {"expired":int(row["expired"] if row else 0)}


def search_reservation_cases(query,limit=20):
    query=(query or "").strip()
    if len(query)<2:
        return []
    limit=max(1,min(int(limit),50))
    needle=f"%{query}%"
    with db_connection() as conn:
        return [
            dict(row) for row in conn.execute(
                """select distinct
                     r.id,r.reference,r.guest_name,r.guest_email,r.check_in,r.check_out,
                     r.status,r.payment_status,r.total_price_minor,r.amount_paid_minor,r.currency,
                     p.name property_name,r.created_at
                   from reservations r
                   join properties p on p.id=r.property_id
                   left join payment_transactions pt on pt.reservation_id=r.id
                   left join refunds rf on rf.reservation_id=r.id
                   where r.reference ilike %s
                      or r.guest_email ilike %s
                      or r.guest_name ilike %s
                      or coalesce(pt.provider_reference,'') ilike %s
                      or coalesce(rf.provider_reference,'') ilike %s
                   order by r.created_at desc
                   limit %s""",
                (needle,needle,needle,needle,needle,limit),
            ).fetchall()
        ]


def reservation_case(reservation_id):
    with db_connection() as conn:
        reservation=conn.execute(
            """select r.*,p.name property_name,p.city property_city,p.state property_state,
                      o.name organization_name
               from reservations r
               join properties p on p.id=r.property_id
               join organizations o on o.id=r.organization_id
               where r.id=%s""",
            (reservation_id,),
        ).fetchone()
        if not reservation:
            return None

        items=list(conn.execute(
            """select ri.id,ri.quantity,ri.unit_price_minor,ri.total_price_minor,
                      rt.name room_type_name,rp.name rate_plan_name,rp.guarantee_type
               from reservation_items ri
               join room_types rt on rt.id=ri.room_type_id
               join rate_plans rp on rp.id=ri.rate_plan_id
               where ri.reservation_id=%s
               order by ri.created_at""",
            (reservation_id,),
        ).fetchall())

        transactions=list(conn.execute(
            """select id,provider,provider_reference,amount_minor,currency,status,
                      paid_at,created_at,updated_at
               from payment_transactions
               where reservation_id=%s
               order by created_at desc""",
            (reservation_id,),
        ).fetchall())

        refunds=list(conn.execute(
            """select id,provider_reference,amount_minor,currency,status,reason,created_at,updated_at
               from refunds
               where reservation_id=%s
               order by created_at desc""",
            (reservation_id,),
        ).fetchall())

        notifications=list(conn.execute(
            """select id,channel,event_type,recipient,status,attempts,next_attempt_at,
                      last_error,sent_at,created_at
               from notifications
               where reservation_id=%s
               order by created_at desc
               limit 100""",
            (reservation_id,),
        ).fetchall())

        audit=list(conn.execute(
            """select action,actor_user_id,before_json,after_json,created_at
               from audit_logs
               where entity_type='reservation' and entity_id=%s
               order by created_at desc
               limit 50""",
            (reservation_id,),
        ).fetchall())

    return {
        "reservation":dict(reservation),
        "items":[dict(row) for row in items],
        "transactions":[dict(row) for row in transactions],
        "refunds":[dict(row) for row in refunds],
        "notifications":[dict(row) for row in notifications],
        "audit":[dict(row) for row in audit],
    }


def _alert_fingerprint(issue):
    link=(issue.get("link") or "").strip()
    stable=link or "|".join([
        str(issue.get("reference") or ""),
        str(issue.get("detail") or ""),
    ])
    raw=f"{issue.get('kind','unknown')}|{stable}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _alert_entity(issue):
    link=(issue.get("link") or "").strip()
    prefix="/admin/reservations/"
    if link.startswith(prefix):
        return "reservation",link[len(prefix):].split("/",1)[0]
    return None,None


def list_operational_alerts(limit=50):
    limit=max(1,min(int(limit),100))
    with db_connection() as conn:
        return [
            dict(row) for row in conn.execute(
                """select a.*,p.name acknowledged_by_name
                   from private.operational_alerts a
                   left join profiles p on p.id=a.acknowledged_by
                   order by
                     case a.status when 'open' then 0 when 'acknowledged' then 1 else 2 end,
                     case a.severity when 'critical' then 0 else 1 end,
                     a.last_seen_at desc
                   limit %s""",
                (limit,),
            ).fetchall()
        ]


def acknowledge_operational_alert(alert_id,actor_user_id):
    with db_connection() as conn:
        with conn.transaction():
            row=conn.execute(
                """update private.operational_alerts
                   set status=case when status='open' then 'acknowledged' else status end,
                       acknowledged_at=case when status='open' then now() else acknowledged_at end,
                       acknowledged_by=case when status='open' then %s else acknowledged_by end,
                       updated_at=now()
                   where id=%s and status in ('open','acknowledged')
                   returning *""",
                (actor_user_id,alert_id),
            ).fetchone()
            if row:
                conn.execute(
                    """insert into audit_logs(
                         actor_user_id,action,entity_type,entity_id,after_json
                       ) values(%s,'operations.alert_acknowledged','operational_alert',%s,%s::jsonb)""",
                    (
                        actor_user_id,
                        str(alert_id),
                        json.dumps({
                            "status":row["status"],
                            "kind":row["kind"],
                            "severity":row["severity"],
                        }),
                    ),
                )
    return dict(row) if row else None


def sync_operational_alerts():
    snapshot=operations_snapshot(limit=1000)
    issues=snapshot["issues"]
    active_fingerprints=[]
    new_alerts=0
    reopened_alerts=0
    resolved_alerts=0
    in_app_created=0
    email_ids=[]

    with db_connection() as conn:
        with conn.transaction():
            admins=list(conn.execute(
                """select p.id,p.name,u.email
                   from profiles p
                   join auth.users u on u.id=p.id
                   where p.platform_role='admin' and p.status='active'"""
            ).fetchall())

            for issue in issues:
                fingerprint=_alert_fingerprint(issue)
                active_fingerprints.append(fingerprint)
                entity_type,entity_id=_alert_entity(issue)
                existing=conn.execute(
                    """select id,status,notification_sent_at
                       from private.operational_alerts
                       where fingerprint=%s
                       for update""",
                    (fingerprint,),
                ).fetchone()

                if existing:
                    was_resolved=existing["status"]=="resolved"
                    row=conn.execute(
                        """update private.operational_alerts
                           set kind=%s,severity=%s,title=%s,reference=%s,detail=%s,
                               entity_type=%s,entity_id=%s,link=%s,
                               status=case when status='resolved' then 'open' else status end,
                               acknowledged_at=case when status='resolved' then null else acknowledged_at end,
                               acknowledged_by=case when status='resolved' then null else acknowledged_by end,
                               resolved_at=null,
                               notification_sent_at=case when status='resolved' then null else notification_sent_at end,
                               last_seen_at=now(),occurrences=occurrences+1,updated_at=now()
                           where id=%s
                           returning *""",
                        (
                            issue["kind"],issue["severity"],issue["title"],issue["reference"],
                            issue["detail"],entity_type,entity_id,issue.get("link"),existing["id"],
                        ),
                    ).fetchone()
                    if was_resolved:
                        reopened_alerts+=1
                else:
                    row=conn.execute(
                        """insert into private.operational_alerts(
                             fingerprint,kind,severity,title,reference,detail,
                             entity_type,entity_id,link
                           ) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           returning *""",
                        (
                            fingerprint,issue["kind"],issue["severity"],issue["title"],
                            issue["reference"],issue["detail"],entity_type,entity_id,issue.get("link"),
                        ),
                    ).fetchone()
                    new_alerts+=1

                if row["notification_sent_at"] is not None:
                    continue

                href=row["link"] or "/admin"
                body=f"{row['reference'] or row['kind']} · {row['detail']}"
                for admin in admins:
                    payload={
                        "operational_alert_id":str(row["id"]),
                        "severity":row["severity"],
                        "title":row["title"],
                        "body":body,
                        "href":href,
                    }
                    inserted=conn.execute(
                        """insert into notifications(
                             user_id,channel,event_type,recipient,status,payload,sent_at
                           ) values(%s,'in_app','operations.alert',%s,'sent',%s::jsonb,now())
                           on conflict do nothing
                           returning id""",
                        (admin["id"],str(admin["id"]),json.dumps(payload)),
                    ).fetchone()
                    if inserted:
                        in_app_created+=1

                    if row["severity"]=="critical" and admin["email"]:
                        email_payload={
                            "operational_alert_id":str(row["id"]),
                            "severity":row["severity"],
                            "subject":f"iRoya operations: {row['title']}",
                            "body":(
                                f"{row['title']}\n\n{body}\n\n"
                                f"Review: {NotificationService._absolute_url(href)}"
                            ),
                            "href":href,
                        }
                        queued=conn.execute(
                            """insert into notifications(
                                 user_id,channel,event_type,recipient,status,payload,next_attempt_at
                               ) values(%s,'email','operations.alert',%s,'queued',%s::jsonb,now())
                               on conflict do nothing
                               returning id""",
                            (admin["id"],admin["email"],json.dumps(email_payload)),
                        ).fetchone()
                        if queued:
                            email_ids.append(str(queued["id"]))

                conn.execute(
                    """update private.operational_alerts
                       set notification_sent_at=now(),updated_at=now()
                       where id=%s""",
                    (row["id"],),
                )

            total_active=int(snapshot["critical"] or 0)+int(snapshot["warning"] or 0)
            complete_scan=total_active<=len(issues)
            if complete_scan:
                if active_fingerprints:
                    result=conn.execute(
                        """update private.operational_alerts
                           set status='resolved',resolved_at=now(),updated_at=now()
                           where status in ('open','acknowledged')
                             and not (fingerprint=any(%s::text[]))""",
                        (active_fingerprints,),
                    )
                else:
                    result=conn.execute(
                        """update private.operational_alerts
                           set status='resolved',resolved_at=now(),updated_at=now()
                           where status in ('open','acknowledged')"""
                    )
                resolved_alerts=max(int(result.rowcount or 0),0)

    delivery=NotificationService().deliver_pending_emails(
        limit=max(1,len(email_ids)),
        notification_ids=email_ids,
    ) if email_ids else {
        "configured":None,"checked":0,"sent":0,"retrying":0,"failed":0,"suppressed":0,
    }

    return {
        "snapshot":snapshot,
        "new_alerts":new_alerts,
        "reopened_alerts":reopened_alerts,
        "resolved_alerts":resolved_alerts,
        "in_app_created":in_app_created,
        "critical_emails_queued":len(email_ids),
        "critical_email_delivery":delivery,
    }
