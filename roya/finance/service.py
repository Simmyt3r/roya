from roya.common.db import db_connection
from roya.common.errors import RoyaError


PARTNER_FINANCE_ROLES={"owner","manager","finance"}
FINANCIAL_RESERVATION_STATUSES=("confirmed","checked_in","checked_out")


def partner_finance_scope(user_id):
    with db_connection() as conn:
        rows=conn.execute(
            """select o.id,o.name,om.role
               from organizations o
               join organization_members om on om.organization_id=o.id
               where om.user_id=%s
                 and om.status='active'
                 and om.role=any(%s::text[])
               order by o.name""",
            (user_id,list(PARTNER_FINANCE_ROLES)),
        ).fetchall()
    return [dict(row) for row in rows]


def _finance_where(start_date,end_date,organization_ids=None,organization_id=None,property_id=None,alias="r"):
    clauses=[f"{alias}.created_at::date between %s and %s"]
    params=[start_date,end_date]
    if organization_ids is not None:
        clauses.append(f"{alias}.organization_id=any(%s::uuid[])")
        params.append(list(organization_ids))
    if organization_id:
        clauses.append(f"{alias}.organization_id=%s")
        params.append(organization_id)
    if property_id:
        clauses.append(f"{alias}.property_id=%s")
        params.append(property_id)
    return " and ".join(clauses),params


def _finance_snapshot(start_date,end_date,organization_ids=None,organization_id=None,property_id=None,limit=150):
    where,params=_finance_where(
        start_date,end_date,
        organization_ids=organization_ids,
        organization_id=organization_id,
        property_id=property_id,
    )
    active_statuses=list(FINANCIAL_RESERVATION_STATUSES)

    with db_connection() as conn:
        metrics=conn.execute(
            f"""with scoped as (
                  select r.*,
                    coalesce((
                      select sum(rf.amount_minor)
                      from refunds rf
                      where rf.reservation_id=r.id and rf.status='successful'
                    ),0)::bigint refunded_minor
                  from reservations r
                  where {where}
                )
                select
                  count(*) filter(where status=any(%s::text[])) booking_count,
                  coalesce(sum(total_price_minor) filter(where status=any(%s::text[])),0)::bigint gross_booking_value_minor,
                  coalesce(sum(amount_paid_minor) filter(where status=any(%s::text[])),0)::bigint collected_minor,
                  coalesce(sum(refunded_minor),0)::bigint refunded_minor,
                  coalesce(sum(greatest(amount_paid_minor-refunded_minor,0)),0)::bigint net_collected_minor,
                  coalesce(sum(amount_paid_minor) filter(
                    where guarantee_type='deposit' and status=any(%s::text[])
                  ),0)::bigint deposits_collected_minor,
                  coalesce(sum(greatest(total_price_minor-amount_paid_minor,0)) filter(
                    where status=any(%s::text[])
                  ),0)::bigint outstanding_balance_minor,
                  coalesce(sum(greatest(total_price_minor-amount_paid_minor,0)) filter(
                    where guarantee_type='pay_at_property' and status=any(%s::text[])
                  ),0)::bigint due_at_property_minor,
                  count(*) filter(where payment_status in ('pending','partially_paid')) payment_attention_count
                from scoped""",
            tuple(params+[active_statuses,active_statuses,active_statuses,active_statuses,active_statuses,active_statuses]),
        ).fetchone()

        ledger=list(conn.execute(
            f"""select
                  r.id,r.reference,r.created_at,r.check_in,r.check_out,
                  r.guest_name,r.guest_email,r.status,r.payment_status,r.guarantee_type,
                  r.currency,r.total_price_minor,r.amount_due_minor,r.amount_paid_minor,
                  o.id organization_id,o.name organization_name,
                  p.id property_id,p.name property_name,
                  coalesce((
                    select sum(rf.amount_minor)
                    from refunds rf
                    where rf.reservation_id=r.id and rf.status='successful'
                  ),0)::bigint refunded_minor,
                  greatest(
                    r.amount_paid_minor-coalesce((
                      select sum(rf.amount_minor)
                      from refunds rf
                      where rf.reservation_id=r.id and rf.status='successful'
                    ),0),0
                  )::bigint net_collected_minor,
                  greatest(r.total_price_minor-r.amount_paid_minor,0)::bigint outstanding_minor,
                  coalesce((
                    select pt.provider
                    from payment_transactions pt
                    where pt.reservation_id=r.id
                    order by pt.created_at desc
                    limit 1
                  ),'') latest_provider,
                  coalesce((
                    select pt.provider_reference
                    from payment_transactions pt
                    where pt.reservation_id=r.id
                    order by pt.created_at desc
                    limit 1
                  ),'') latest_provider_reference,
                  coalesce((
                    select pt.status
                    from payment_transactions pt
                    where pt.reservation_id=r.id
                    order by pt.created_at desc
                    limit 1
                  ),'') latest_transaction_status
                from reservations r
                join organizations o on o.id=r.organization_id
                join properties p on p.id=r.property_id
                where {where}
                order by r.created_at desc
                limit %s""",
            tuple(params+[max(1,min(int(limit),5000))]),
        ).fetchall())

        payment_activity=list(conn.execute(
            """select
                 pt.id,'payment'::text activity_type,pt.created_at,
                 pt.paid_at activity_at,pt.amount_minor,pt.currency,pt.status,
                 pt.provider,pt.provider_reference,
                 r.id reservation_id,r.reference reservation_reference,
                 r.guest_name,r.guest_email,p.name property_name,o.name organization_name
               from payment_transactions pt
               join reservations r on r.id=pt.reservation_id
               join properties p on p.id=r.property_id
               join organizations o on o.id=r.organization_id
               where coalesce(pt.paid_at,pt.created_at)::date between %s and %s
                 and (%s::uuid[] is null or r.organization_id=any(%s::uuid[]))
                 and (%s::uuid is null or r.organization_id=%s)
                 and (%s::uuid is null or r.property_id=%s)
               order by coalesce(pt.paid_at,pt.created_at) desc
               limit 100""",
            (
                start_date,end_date,
                list(organization_ids) if organization_ids is not None else None,
                list(organization_ids) if organization_ids is not None else None,
                organization_id,organization_id,property_id,property_id,
            ),
        ).fetchall())

        refund_activity=list(conn.execute(
            """select
                 rf.id,'refund'::text activity_type,rf.created_at,
                 rf.updated_at activity_at,rf.amount_minor,rf.currency,rf.status,
                 'refund'::text provider,coalesce(rf.provider_reference,'') provider_reference,
                 r.id reservation_id,r.reference reservation_reference,
                 r.guest_name,r.guest_email,p.name property_name,o.name organization_name
               from refunds rf
               join reservations r on r.id=rf.reservation_id
               join properties p on p.id=r.property_id
               join organizations o on o.id=r.organization_id
               where rf.created_at::date between %s and %s
                 and (%s::uuid[] is null or r.organization_id=any(%s::uuid[]))
                 and (%s::uuid is null or r.organization_id=%s)
                 and (%s::uuid is null or r.property_id=%s)
               order by rf.created_at desc
               limit 100""",
            (
                start_date,end_date,
                list(organization_ids) if organization_ids is not None else None,
                list(organization_ids) if organization_ids is not None else None,
                organization_id,organization_id,property_id,property_id,
            ),
        ).fetchall())

    metrics=dict(metrics or {})
    booking_count=int(metrics.get("booking_count") or 0)
    gross=int(metrics.get("gross_booking_value_minor") or 0)
    metrics["average_booking_value_minor"]=gross//booking_count if booking_count else 0
    metrics["platform_fee_minor"]=0
    metrics["platform_fee_configured"]=False
    metrics["settlement_execution_enabled"]=False

    activity=[dict(row) for row in payment_activity]+[dict(row) for row in refund_activity]
    activity.sort(
        key=lambda row:row.get("activity_at") or row.get("created_at"),
        reverse=True,
    )
    return {
        "metrics":metrics,
        "ledger":[dict(row) for row in ledger],
        "activity":activity[:100],
    }


def partner_finance_dashboard(user_id,start_date,end_date,organization_id=None,property_id=None,limit=150):
    organizations=partner_finance_scope(user_id)
    if not organizations:
        raise RoyaError("FORBIDDEN","Hotel finance access requires an owner, manager or finance role.",403)

    allowed_ids={str(row["id"]) for row in organizations}
    if organization_id and str(organization_id) not in allowed_ids:
        raise RoyaError("FORBIDDEN","You do not have finance access to that organization.",403)

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
        raise RoyaError("FORBIDDEN","You do not have finance access to that property.",403)

    snapshot=_finance_snapshot(
        start_date,end_date,
        organization_ids=selected_ids,
        property_id=str(property_id) if property_id else None,
        limit=limit,
    )
    snapshot.update({
        "organizations":organizations,
        "properties":properties,
        "selected_organization_id":str(organization_id) if organization_id else "",
        "selected_property_id":str(property_id) if property_id else "",
    })
    return snapshot


def platform_finance_dashboard(start_date,end_date,organization_id=None,property_id=None,limit=150):
    with db_connection() as conn:
        organizations=[dict(row) for row in conn.execute(
            "select id,name from organizations order by name"
        ).fetchall()]
        properties=[dict(row) for row in conn.execute(
            """select id,name,organization_id
               from properties
               where (%s::uuid is null or organization_id=%s)
               order by name""",
            (organization_id,organization_id),
        ).fetchall()]

    if organization_id and str(organization_id) not in {str(row["id"]) for row in organizations}:
        raise RoyaError("NOT_FOUND","Organization not found.",404)
    if property_id and str(property_id) not in {str(row["id"]) for row in properties}:
        raise RoyaError("NOT_FOUND","Property not found in the selected organization.",404)

    snapshot=_finance_snapshot(
        start_date,end_date,
        organization_id=str(organization_id) if organization_id else None,
        property_id=str(property_id) if property_id else None,
        limit=limit,
    )
    snapshot.update({
        "organizations":organizations,
        "properties":properties,
        "selected_organization_id":str(organization_id) if organization_id else "",
        "selected_property_id":str(property_id) if property_id else "",
    })

    with db_connection() as conn:
        top_hotels=[dict(row) for row in conn.execute(
            """select p.id,p.name,o.name organization_name,
                      count(*) filter(where r.status=any(%s::text[])) booking_count,
                      coalesce(sum(r.total_price_minor) filter(where r.status=any(%s::text[])),0)::bigint gross_minor,
                      coalesce(sum(r.amount_paid_minor) filter(where r.status=any(%s::text[])),0)::bigint collected_minor
               from properties p
               join organizations o on o.id=p.organization_id
               left join reservations r
                 on r.property_id=p.id
                and r.created_at::date between %s and %s
               group by p.id,p.name,o.name
               order by gross_minor desc,p.name
               limit 25""",
            (
                list(FINANCIAL_RESERVATION_STATUSES),
                list(FINANCIAL_RESERVATION_STATUSES),
                list(FINANCIAL_RESERVATION_STATUSES),
                start_date,end_date,
            ),
        ).fetchall()]
    snapshot["top_hotels"]=top_hotels
    return snapshot
