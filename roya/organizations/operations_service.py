from roya.common.db import db_connection


DEFAULT_HORIZON_DAYS=7
MIN_HORIZON_DAYS=3
MAX_HORIZON_DAYS=14


def normalize_horizon_days(value):
    try:
        days=int(value or DEFAULT_HORIZON_DAYS)
    except (TypeError,ValueError):
        days=DEFAULT_HORIZON_DAYS
    return max(MIN_HORIZON_DAYS,min(days,MAX_HORIZON_DAYS))


def select_property_scope(properties,property_id):
    requested=str(property_id or "").strip()
    selected=next((row for row in properties if str(row["id"])==requested),None)
    return (str(selected["id"]) if selected else None),selected


def scope_action_links(tasks,property_id,horizon_days):
    if not property_id:
        return tasks
    prefix=f"/partner?property_id={property_id}&days={horizon_days}#"
    scoped=[]
    for task in tasks:
        item={**task}
        if item["href"].startswith("/partner#"):
            item["href"]=item["href"].replace("/partner#",prefix,1)
        elif item["href"].startswith("/partner/reservations?"):
            item["href"]+=f"&property_id={property_id}"
        elif item["href"].startswith("/partner/rooms?"):
            item["href"]+=f"&property_id={property_id}"
        elif item["href"].startswith("/partner/finance?"):
            item["href"]+=f"&property_id={property_id}"
        scoped.append(item)
    return scoped


def empty_operations_snapshot(horizon_days):
    return {
        "organizations":[],
        "properties":[],
        "selected_property_id":None,
        "selected_property":None,
        "summary":{},
        "arrivals":[],
        "departures":[],
        "overdue":[],
        "forecast":[],
        "low_inventory":[],
        "source_mix":[],
        "channel_errors":[],
        "tasks":[],
        "horizon_days":horizon_days,
    }


def _task(priority,title,detail,href):
    return {
        "priority":priority,
        "title":title,
        "detail":detail,
        "href":href,
    }


def build_daily_actions(summary,low_inventory,channel_errors,not_ready_arrivals=0):
    tasks=[]
    pending=int(summary.get("pending_approvals") or 0)
    overdue_arrivals=int(summary.get("overdue_arrivals") or 0)
    overdue_departures=int(summary.get("overdue_departures") or 0)
    arrivals=int(summary.get("arrivals_today") or 0)
    departures=int(summary.get("departures_today") or 0)
    refund_attention=int(summary.get("refund_attention") or 0)

    if overdue_arrivals:
        tasks.append(_task(
            "critical",
            f"{overdue_arrivals} overdue arrival{'s' if overdue_arrivals != 1 else ''}",
            "Confirmed stays have passed their arrival date without check-in or no-show resolution.",
            "/partner#operations-overdue",
        ))
    if overdue_departures:
        tasks.append(_task(
            "critical",
            f"{overdue_departures} overdue departure{'s' if overdue_departures != 1 else ''}",
            "Checked-in stays are past their planned check-out date and need front-desk review.",
            "/partner#operations-overdue",
        ))
    if pending:
        tasks.append(_task(
            "warning",
            f"{pending} reservation approval{'s' if pending != 1 else ''} waiting",
            "Review hotel-approval bookings before their inventory holds expire.",
            "/partner/reservations?tab=pending",
        ))
    if not_ready_arrivals:
        tasks.append(_task(
            "warning",
            f"{not_ready_arrivals} arrival{'s' if not_ready_arrivals != 1 else ''} waiting on room readiness",
            "One or more tracked room types do not yet have enough ready rooms for check-in.",
            "/partner/rooms?focus=readiness",
        ))
    if low_inventory:
        tasks.append(_task(
            "warning",
            f"{len(low_inventory)} low-inventory room date{'s' if len(low_inventory) != 1 else ''}",
            "Future sellable inventory is at two rooms or fewer for these room/date combinations.",
            "/partner/rooms?focus=inventory",
        ))
    if channel_errors:
        tasks.append(_task(
            "warning",
            f"{len(channel_errors)} distribution channel error{'s' if len(channel_errors) != 1 else ''}",
            "A built-in distribution connection needs review or a manual retry.",
            "/partner/distribution",
        ))
    if refund_attention:
        tasks.append(_task(
            "warning",
            f"{refund_attention} refund request{'s' if refund_attention != 1 else ''} need attention",
            "Requested or processing refunds are still open for this hotel workspace.",
            "/partner/finance?focus=refunds",
        ))
    if arrivals:
        tasks.append(_task(
            "info",
            f"{arrivals} arrival{'s' if arrivals != 1 else ''} today",
            "Prepare rooms and verify the guest list before check-in.",
            "/partner#operations-arrivals",
        ))
    if departures:
        tasks.append(_task(
            "info",
            f"{departures} departure{'s' if departures != 1 else ''} today",
            "Prepare check-out, room turnover and final guest handling.",
            "/partner#operations-departures",
        ))
    return tasks[:8]


def hotel_operations_snapshot(user_id,horizon_days=DEFAULT_HORIZON_DAYS,property_id=None):
    horizon_days=normalize_horizon_days(horizon_days)
    with db_connection() as conn:
        memberships=[
            dict(row) for row in conn.execute(
                """select o.id,o.name,om.role
                   from organizations o
                   join organization_members om on om.organization_id=o.id
                   where om.user_id=%s
                     and om.status='active'
                   order by o.name""",
                (user_id,),
            ).fetchall()
        ]
        if not memberships:
            return empty_operations_snapshot(horizon_days)

        organization_ids=[str(row["id"]) for row in memberships]
        properties=[
            dict(row) for row in conn.execute(
                """select p.id,p.name,p.organization_id
                   from properties p
                   where p.organization_id=any(%s::uuid[])
                   order by p.name""",
                (organization_ids,),
            ).fetchall()
        ]
        selected_property_id,selected_property=select_property_scope(properties,property_id)

        summary=dict(conn.execute(
            """select
                 count(*) filter(where status='confirmed' and check_in=current_date)::bigint arrivals_today,
                 count(*) filter(where status='checked_in' and check_out=current_date)::bigint departures_today,
                 count(*) filter(where status='checked_in')::bigint in_house,
                 count(*) filter(where status='pending_confirmation')::bigint pending_approvals,
                 count(*) filter(where status='confirmed' and check_in<current_date)::bigint overdue_arrivals,
                 count(*) filter(where status='checked_in' and check_out<current_date)::bigint overdue_departures,
                 count(*) filter(
                   where status in ('confirmed','checked_in')
                     and check_in<=current_date+1
                     and check_out>current_date
                 )::bigint active_next_24h,
                 (select count(*) from refunds rf
                    join reservations rr on rr.id=rf.reservation_id
                    where rr.organization_id=any(%s::uuid[])
                      and (%s::uuid is null or rr.property_id=%s::uuid)
                      and rf.status in ('requested','processing'))::bigint refund_attention
               from reservations r
               where r.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or r.property_id=%s::uuid)""",
            (
                organization_ids,selected_property_id,selected_property_id,
                organization_ids,selected_property_id,selected_property_id,
            ),
        ).fetchone() or {})

        arrivals=[dict(row) for row in conn.execute(
            """select r.id,r.organization_id,r.reference,r.guest_name,r.guest_email,r.check_in,r.check_out,r.status,
                      r.payment_status,r.guarantee_type,r.source_channel,p.name property_name,
                      coalesce((
                        select count(*)>0 and bool_and(
                          (select count(*) from physical_rooms pr where pr.room_type_id=ri.room_type_id)>=rt.total_inventory
                        )
                        from reservation_items ri
                        join room_types rt on rt.id=ri.room_type_id
                        where ri.reservation_id=r.id
                      ),false) room_readiness_tracked,
                      coalesce((
                        select bool_and(
                          (select count(*) from physical_rooms pr
                             where pr.room_type_id=ri.room_type_id
                               and pr.status='active'
                               and pr.housekeeping_status='ready'
                               and pr.current_reservation_id is null)>=ri.quantity
                        )
                        from reservation_items ri
                        where ri.reservation_id=r.id
                      ),true) rooms_ready
               from reservations r
               join properties p on p.id=r.property_id
               where r.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or r.property_id=%s::uuid)
                 and r.status='confirmed'
                 and r.check_in=current_date
               order by p.name,r.created_at
               limit 20""",
            (organization_ids,selected_property_id,selected_property_id),
        ).fetchall()]

        departures=[dict(row) for row in conn.execute(
            """select r.id,r.organization_id,r.reference,r.guest_name,r.guest_email,r.check_in,r.check_out,r.status,
                      r.payment_status,r.source_channel,p.name property_name
               from reservations r
               join properties p on p.id=r.property_id
               where r.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or r.property_id=%s::uuid)
                 and r.status='checked_in'
                 and r.check_out=current_date
               order by p.name,r.checked_in_at nulls last,r.created_at
               limit 20""",
            (organization_ids,selected_property_id,selected_property_id),
        ).fetchall()]

        overdue=[dict(row) for row in conn.execute(
            """select r.id,r.organization_id,r.reference,r.guest_name,r.check_in,r.check_out,r.status,
                      r.payment_status,p.name property_name,
                      case
                        when r.status='confirmed' and r.check_in<current_date then 'arrival'
                        when r.status='checked_in' and r.check_out<current_date then 'departure'
                      end overdue_type
               from reservations r
               join properties p on p.id=r.property_id
               where r.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or r.property_id=%s::uuid)
                 and (
                   (r.status='confirmed' and r.check_in<current_date)
                   or (r.status='checked_in' and r.check_out<current_date)
                 )
               order by least(r.check_in,r.check_out),p.name
               limit 20""",
            (organization_ids,selected_property_id,selected_property_id),
        ).fetchall()]

        forecast=[dict(row) for row in conn.execute(
            """select i.date,
                      coalesce(sum(i.total_inventory),0)::bigint total_inventory,
                      coalesce(sum(i.sold_inventory),0)::bigint sold_inventory,
                      coalesce(sum(i.held_inventory),0)::bigint held_inventory,
                      coalesce(sum(
                        case when i.stop_sell then 0
                             else greatest(i.total_inventory-i.sold_inventory-i.held_inventory,0)
                        end
                      ),0)::bigint sellable_inventory,
                      count(*) filter(where i.stop_sell)::bigint stopped_room_types,
                      case when coalesce(sum(i.total_inventory),0)>0
                        then round(100.0*sum(i.sold_inventory)/sum(i.total_inventory),1)
                        else 0 end occupancy_percent,
                      case when coalesce(sum(i.total_inventory),0)>0
                        then round(100.0*sum(i.sold_inventory+i.held_inventory)/sum(i.total_inventory),1)
                        else 0 end committed_percent
               from inventory_days i
               join room_types rt on rt.id=i.room_type_id
               join properties p on p.id=rt.property_id
               where p.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or p.id=%s::uuid)
                 and rt.status='active'
                 and i.date between current_date and current_date+(%s::int-1)
               group by i.date
               order by i.date""",
            (organization_ids,selected_property_id,selected_property_id,horizon_days),
        ).fetchall()]

        low_inventory=[dict(row) for row in conn.execute(
            """select p.id property_id,p.name property_name,rt.id room_type_id,rt.name room_type_name,
                      i.date,i.total_inventory,i.sold_inventory,i.held_inventory,
                      greatest(i.total_inventory-i.sold_inventory-i.held_inventory,0)::integer available
               from inventory_days i
               join room_types rt on rt.id=i.room_type_id
               join properties p on p.id=rt.property_id
               where p.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or p.id=%s::uuid)
                 and rt.status='active'
                 and i.stop_sell=false
                 and i.date between current_date and current_date+(%s::int-1)
                 and greatest(i.total_inventory-i.sold_inventory-i.held_inventory,0)<=2
               order by available asc,i.date,p.name,rt.name
               limit 30""",
            (organization_ids,selected_property_id,selected_property_id,horizon_days),
        ).fetchall()]

        source_mix=[]

        channel_errors=[dict(row) for row in conn.execute(
            """select c.id,c.channel,c.status,c.last_synced_at,p.name property_name
               from channel_connections c
               join properties p on p.id=c.property_id
               where c.organization_id=any(%s::uuid[])
                 and (%s::uuid is null or c.property_id=%s::uuid)
                 and c.status='error'
               order by c.updated_at desc
               limit 20""",
            (organization_ids,selected_property_id,selected_property_id),
        ).fetchall()]

    for key in (
        "arrivals_today","departures_today","in_house","pending_approvals",
        "overdue_arrivals","overdue_departures","active_next_24h","refund_attention",
    ):
        summary[key]=int(summary.get(key) or 0)

    role_by_organization={str(row["id"]):row["role"] for row in memberships}
    for stay in arrivals+departures+overdue:
        stay["member_role"]=role_by_organization.get(str(stay["organization_id"]))

    not_ready_arrivals=sum(
        1 for stay in arrivals
        if stay.get("room_readiness_tracked") and not stay.get("rooms_ready")
    )
    tasks=scope_action_links(
        build_daily_actions(summary,low_inventory,channel_errors,not_ready_arrivals),
        selected_property_id,
        horizon_days,
    )
    return {
        "organizations":memberships,
        "properties":properties,
        "selected_property_id":selected_property_id,
        "selected_property":selected_property,
        "summary":summary,
        "arrivals":arrivals,
        "departures":departures,
        "overdue":overdue,
        "forecast":forecast,
        "low_inventory":low_inventory,
        "source_mix":source_mix,
        "channel_errors":channel_errors,
        "tasks":tasks,
        "horizon_days":horizon_days,
    }
