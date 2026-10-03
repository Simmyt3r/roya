from roya.common.db import db_connection


def operations_snapshot(limit=30):
    limit=max(1,min(int(limit),100))
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
                   null::text link
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
                   null::text
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
                   null::text
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
                   null::text
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
                   null::text
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
                   ('/partner/properties/'||p.id::text)
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
                   ('/partner/properties/'||p.id::text)
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
