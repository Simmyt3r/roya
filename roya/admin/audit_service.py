from roya.common.db import db_connection


def list_audit_events(query="",entity_type="",action="",since_days=7,limit=150):
    query=(query or "").strip()
    entity_type=(entity_type or "").strip()
    action=(action or "").strip()
    since_days=max(1,min(int(since_days),365))
    limit=max(1,min(int(limit),300))

    where=["al.created_at>=now()-(%s * interval '1 day')"]
    params=[since_days]

    if query:
        needle=f"%{query}%"
        where.append("""(
          al.entity_id ilike %s
          or al.action ilike %s
          or al.entity_type ilike %s
          or coalesce(p.name,'') ilike %s
          or coalesce(u.email,'') ilike %s
          or coalesce(o.name,'') ilike %s
          or coalesce(pr.name,'') ilike %s
        )""")
        params.extend([needle,needle,needle,needle,needle,needle,needle])
    if entity_type:
        where.append("al.entity_type=%s")
        params.append(entity_type)
    if action:
        where.append("al.action=%s")
        params.append(action)

    params.append(limit)
    with db_connection() as conn:
        rows=conn.execute(
            f"""select
                  al.id,al.actor_user_id,al.organization_id,al.property_id,
                  al.action,al.entity_type,al.entity_id,
                  al.before_json,al.after_json,al.ip_address,al.user_agent,al.created_at,
                  coalesce(nullif(p.name,''),u.email,'System') actor_name,
                  u.email actor_email,
                  o.name organization_name,
                  pr.name property_name
                from audit_logs al
                left join profiles p on p.id=al.actor_user_id
                left join auth.users u on u.id=al.actor_user_id
                left join organizations o on o.id=al.organization_id
                left join properties pr on pr.id=al.property_id
                where {' and '.join(where)}
                order by al.created_at desc
                limit %s""",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def audit_filter_options():
    with db_connection() as conn:
        entity_types=[
            row["entity_type"] for row in conn.execute(
                """select distinct entity_type
                   from audit_logs
                   where created_at>=now()-interval '90 days'
                   order by entity_type"""
            ).fetchall()
        ]
        actions=[
            row["action"] for row in conn.execute(
                """select distinct action
                   from audit_logs
                   where created_at>=now()-interval '90 days'
                   order by action"""
            ).fetchall()
        ]
    return {"entity_types":entity_types,"actions":actions}


def audit_counts():
    with db_connection() as conn:
        row=conn.execute(
            """select
                 count(*) total,
                 count(*) filter(where created_at>=now()-interval '24 hours') last_24h,
                 count(distinct actor_user_id) filter(where actor_user_id is not null) actors,
                 count(distinct property_id) filter(where property_id is not null) properties
               from audit_logs"""
        ).fetchone()
    return dict(row) if row else {"total":0,"last_24h":0,"actors":0,"properties":0}
