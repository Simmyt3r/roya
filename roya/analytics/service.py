from roya.common.db import db_connection
from roya.common.errors import RoyaError


ANALYTICS_ROLES={"owner","manager","finance"}
ACTIVE_RESERVATION_STATUSES=("confirmed","checked_in","checked_out")
RESOLVED_RESERVATION_STATUSES=("confirmed","checked_in","checked_out","cancelled","no_show")


def partner_analytics_scope(user_id):
    with db_connection() as conn:
        rows=conn.execute(
            """select o.id,o.name,om.role
               from organizations o
               join organization_members om on om.organization_id=o.id
               where om.user_id=%s
                 and om.status='active'
                 and om.role=any(%s::text[])
               order by o.name""",
            (user_id,list(ANALYTICS_ROLES)),
        ).fetchall()
    return [dict(row) for row in rows]


def _scope_params(organization_ids,property_id):
    ids=list(organization_ids)
    return ids,property_id,property_id


def _performance_snapshot(start_date,end_date,organization_ids,property_id=None):
    active=list(ACTIVE_RESERVATION_STATUSES)
    resolved=list(RESOLVED_RESERVATION_STATUSES)
    ids=list(organization_ids)

    with db_connection() as conn:
        metrics=conn.execute(
            """with
               inventory as (
                 select
                   coalesce(sum(i.total_inventory),0)::bigint capacity_room_nights,
                   coalesce(sum(i.sold_inventory),0)::bigint sold_room_nights,
                   coalesce(sum(i.held_inventory),0)::bigint held_room_nights,
                   coalesce(sum(greatest(i.total_inventory-i.sold_inventory-i.held_inventory,0)),0)::bigint remaining_room_nights,
                   coalesce(sum(i.total_inventory) filter(where i.stop_sell),0)::bigint stopped_room_nights
                 from inventory_days i
                 join room_types rt on rt.id=i.room_type_id
                 join properties p on p.id=rt.property_id
                 where i.date between %s and %s
                   and p.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or p.id=%s)
               ),
               revenue as (
                 select
                   coalesce(sum(rn.quantity),0)::bigint booked_room_nights,
                   coalesce(sum(rn.unit_price_minor*rn.quantity),0)::bigint room_revenue_minor
                 from reservation_nights rn
                 join reservations r on r.id=rn.reservation_id
                 where rn.date between %s and %s
                   and r.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or r.property_id=%s)
                   and r.status=any(%s::text[])
               ),
               bookings as (
                 select
                   count(*) filter(where status=any(%s::text[])) active_bookings,
                   count(*) filter(where status='cancelled') cancelled_bookings,
                   count(*) filter(where status='no_show') no_show_bookings,
                   count(*) filter(where status=any(%s::text[])) resolved_bookings,
                   coalesce(avg(check_in-created_at::date) filter(where status=any(%s::text[])),0) avg_lead_days,
                   coalesce(avg(nights) filter(where status=any(%s::text[])),0) avg_length_of_stay
                 from reservations
                 where created_at::date between %s and %s
                   and organization_id=any(%s::uuid[])
                   and (%s::uuid is null or property_id=%s)
               ),
               ratings as (
                 select
                   count(*)::bigint review_count,
                   coalesce(avg(rv.rating),0) average_rating
                 from reviews rv
                 join properties p on p.id=rv.property_id
                 where rv.is_visible=true
                   and rv.created_at::date between %s and %s
                   and p.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or p.id=%s)
               )
               select
                 i.*,r.*,b.*,rt.review_count,
                 round(rt.average_rating::numeric,2) average_rating,
                 case when i.capacity_room_nights>0
                   then round(100.0*i.sold_room_nights/i.capacity_room_nights,2) else 0 end occupancy_percent,
                 case when r.booked_room_nights>0
                   then round(r.room_revenue_minor::numeric/r.booked_room_nights) else 0 end adr_minor,
                 case when i.capacity_room_nights>0
                   then round(r.room_revenue_minor::numeric/i.capacity_room_nights) else 0 end revpar_minor,
                 case when b.resolved_bookings>0
                   then round(100.0*b.cancelled_bookings/b.resolved_bookings,2) else 0 end cancellation_rate_percent
               from inventory i cross join revenue r cross join bookings b cross join ratings rt""",
            (
                start_date,end_date,ids,property_id,property_id,
                start_date,end_date,ids,property_id,property_id,active,
                active,resolved,active,active,
                start_date,end_date,ids,property_id,property_id,
                start_date,end_date,ids,property_id,property_id,
            ),
        ).fetchone()

        daily=[dict(row) for row in conn.execute(
            """with days as (
                 select generate_series(%s::date,%s::date,interval '1 day')::date date
               ),
               inv as (
                 select i.date,
                        sum(i.total_inventory)::bigint capacity_room_nights,
                        sum(i.sold_inventory)::bigint sold_room_nights,
                        sum(i.held_inventory)::bigint held_room_nights,
                        sum(greatest(i.total_inventory-i.sold_inventory-i.held_inventory,0))::bigint remaining_room_nights
                 from inventory_days i
                 join room_types rt on rt.id=i.room_type_id
                 join properties p on p.id=rt.property_id
                 where i.date between %s and %s
                   and p.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or p.id=%s)
                 group by i.date
               ),
               rev as (
                 select rn.date,
                        sum(rn.quantity)::bigint booked_room_nights,
                        sum(rn.unit_price_minor*rn.quantity)::bigint room_revenue_minor
                 from reservation_nights rn
                 join reservations r on r.id=rn.reservation_id
                 where rn.date between %s and %s
                   and r.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or r.property_id=%s)
                   and r.status=any(%s::text[])
                 group by rn.date
               )
               select d.date,
                      coalesce(i.capacity_room_nights,0)::bigint capacity_room_nights,
                      coalesce(i.sold_room_nights,0)::bigint sold_room_nights,
                      coalesce(i.held_room_nights,0)::bigint held_room_nights,
                      coalesce(i.remaining_room_nights,0)::bigint remaining_room_nights,
                      coalesce(r.booked_room_nights,0)::bigint booked_room_nights,
                      coalesce(r.room_revenue_minor,0)::bigint room_revenue_minor,
                      case when coalesce(i.capacity_room_nights,0)>0
                        then round(100.0*i.sold_room_nights/i.capacity_room_nights,2) else 0 end occupancy_percent
               from days d
               left join inv i on i.date=d.date
               left join rev r on r.date=d.date
               order by d.date""",
            (
                start_date,end_date,
                start_date,end_date,ids,property_id,property_id,
                start_date,end_date,ids,property_id,property_id,active,
            ),
        ).fetchall()]

        room_types=[dict(row) for row in conn.execute(
            """with inv as (
                 select rt.id room_type_id,rt.name room_type_name,p.id property_id,p.name property_name,
                        sum(i.total_inventory)::bigint capacity_room_nights,
                        sum(i.sold_inventory)::bigint sold_room_nights,
                        sum(i.held_inventory)::bigint held_room_nights
                 from room_types rt
                 join properties p on p.id=rt.property_id
                 left join inventory_days i
                   on i.room_type_id=rt.id and i.date between %s and %s
                 where p.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or p.id=%s)
                 group by rt.id,rt.name,p.id,p.name
               ),
               rev as (
                 select rn.room_type_id,
                        sum(rn.quantity)::bigint booked_room_nights,
                        sum(rn.unit_price_minor*rn.quantity)::bigint room_revenue_minor
                 from reservation_nights rn
                 join reservations r on r.id=rn.reservation_id
                 where rn.date between %s and %s
                   and r.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or r.property_id=%s)
                   and r.status=any(%s::text[])
                 group by rn.room_type_id
               )
               select i.*,
                      coalesce(r.booked_room_nights,0)::bigint booked_room_nights,
                      coalesce(r.room_revenue_minor,0)::bigint room_revenue_minor,
                      case when i.capacity_room_nights>0
                        then round(100.0*i.sold_room_nights/i.capacity_room_nights,2) else 0 end occupancy_percent,
                      case when coalesce(r.booked_room_nights,0)>0
                        then round(r.room_revenue_minor::numeric/r.booked_room_nights) else 0 end adr_minor,
                      case when i.capacity_room_nights>0
                        then round(coalesce(r.room_revenue_minor,0)::numeric/i.capacity_room_nights) else 0 end revpar_minor
               from inv i
               left join rev r on r.room_type_id=i.room_type_id
               order by room_revenue_minor desc,i.property_name,i.room_type_name""",
            (
                start_date,end_date,ids,property_id,property_id,
                start_date,end_date,ids,property_id,property_id,active,
            ),
        ).fetchall()]

        properties=[dict(row) for row in conn.execute(
            """with inv as (
                 select p.id property_id,p.name property_name,
                        sum(i.total_inventory)::bigint capacity_room_nights,
                        sum(i.sold_inventory)::bigint sold_room_nights
                 from properties p
                 left join room_types rt on rt.property_id=p.id and rt.status='active'
                 left join inventory_days i
                   on i.room_type_id=rt.id and i.date between %s and %s
                 where p.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or p.id=%s)
                 group by p.id,p.name
               ),
               rev as (
                 select r.property_id,
                        sum(rn.quantity)::bigint booked_room_nights,
                        sum(rn.unit_price_minor*rn.quantity)::bigint room_revenue_minor
                 from reservation_nights rn
                 join reservations r on r.id=rn.reservation_id
                 where rn.date between %s and %s
                   and r.organization_id=any(%s::uuid[])
                   and (%s::uuid is null or r.property_id=%s)
                   and r.status=any(%s::text[])
                 group by r.property_id
               )
               select i.*,
                      coalesce(r.booked_room_nights,0)::bigint booked_room_nights,
                      coalesce(r.room_revenue_minor,0)::bigint room_revenue_minor,
                      case when i.capacity_room_nights>0
                        then round(100.0*i.sold_room_nights/i.capacity_room_nights,2) else 0 end occupancy_percent,
                      case when coalesce(r.booked_room_nights,0)>0
                        then round(r.room_revenue_minor::numeric/r.booked_room_nights) else 0 end adr_minor,
                      case when i.capacity_room_nights>0
                        then round(coalesce(r.room_revenue_minor,0)::numeric/i.capacity_room_nights) else 0 end revpar_minor
               from inv i
               left join rev r on r.property_id=i.property_id
               order by room_revenue_minor desc,i.property_name""",
            (
                start_date,end_date,ids,property_id,property_id,
                start_date,end_date,ids,property_id,property_id,active,
            ),
        ).fetchall()]

        guarantee_mix=[dict(row) for row in conn.execute(
            """select guarantee_type,
                      count(*)::bigint booking_count,
                      coalesce(sum(total_price_minor),0)::bigint booking_value_minor
               from reservations
               where created_at::date between %s and %s
                 and organization_id=any(%s::uuid[])
                 and (%s::uuid is null or property_id=%s)
                 and status=any(%s::text[])
               group by guarantee_type
               order by booking_count desc,guarantee_type""",
            (start_date,end_date,ids,property_id,property_id,active),
        ).fetchall()]

        status_mix=[dict(row) for row in conn.execute(
            """select status,count(*)::bigint booking_count
               from reservations
               where created_at::date between %s and %s
                 and organization_id=any(%s::uuid[])
                 and (%s::uuid is null or property_id=%s)
               group by status
               order by booking_count desc,status""",
            (start_date,end_date,ids,property_id,property_id),
        ).fetchall()]

    metrics=dict(metrics or {})
    for key in (
        "capacity_room_nights","sold_room_nights","held_room_nights","remaining_room_nights",
        "stopped_room_nights","booked_room_nights","room_revenue_minor","active_bookings",
        "cancelled_bookings","no_show_bookings","resolved_bookings","review_count",
    ):
        metrics[key]=int(metrics.get(key) or 0)
    for key in (
        "occupancy_percent","cancellation_rate_percent","average_rating",
        "avg_lead_days","avg_length_of_stay",
    ):
        metrics[key]=float(metrics.get(key) or 0)
    for key in ("adr_minor","revpar_minor"):
        metrics[key]=int(metrics.get(key) or 0)

    return {
        "metrics":metrics,
        "daily":daily,
        "room_types":room_types,
        "property_performance":properties,
        "guarantee_mix":guarantee_mix,
        "status_mix":status_mix,
    }


def partner_performance_dashboard(user_id,start_date,end_date,organization_id=None,property_id=None):
    organizations=partner_analytics_scope(user_id)
    if not organizations:
        raise RoyaError(
            "FORBIDDEN",
            "Hotel analytics requires an owner, manager or finance role.",
            403,
        )

    allowed_ids={str(row["id"]) for row in organizations}
    if organization_id and str(organization_id) not in allowed_ids:
        raise RoyaError("FORBIDDEN","You do not have analytics access to that organization.",403)

    selected_ids=[str(organization_id)] if organization_id else sorted(allowed_ids)
    with db_connection() as conn:
        properties=[
            dict(row) for row in conn.execute(
                """select id,name,organization_id
                   from properties
                   where organization_id=any(%s::uuid[])
                   order by name""",
                (selected_ids,),
            ).fetchall()
        ]

    if property_id and str(property_id) not in {str(row["id"]) for row in properties}:
        raise RoyaError("FORBIDDEN","You do not have analytics access to that property.",403)

    snapshot=_performance_snapshot(
        start_date,end_date,selected_ids,
        property_id=str(property_id) if property_id else None,
    )
    snapshot.update({
        "organizations":organizations,
        "properties":properties,
        "selected_organization_id":str(organization_id) if organization_id else "",
        "selected_property_id":str(property_id) if property_id else "",
    })
    return snapshot
