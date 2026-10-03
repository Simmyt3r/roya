import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError


def list_reviews(query="",visibility="",limit=100):
    query=(query or "").strip()
    visibility=(visibility or "").strip()
    limit=max(1,min(int(limit),200))
    where=["1=1"]
    params=[]

    if query:
        needle=f"%{query}%"
        where.append("""(
          pr.name ilike %s
          or coalesce(p.name,'') ilike %s
          or u.email ilike %s
          or coalesce(r.comment,'') ilike %s
          or rs.reference ilike %s
        )""")
        params.extend([needle,needle,needle,needle,needle])
    if visibility=="visible":
        where.append("r.is_visible=true")
    elif visibility=="hidden":
        where.append("r.is_visible=false")

    params.append(limit)
    with db_connection() as conn:
        rows=conn.execute(
            f"""select
                  r.id,r.rating,r.comment,r.is_visible,r.created_at,r.updated_at,
                  r.reservation_id,rs.reference reservation_reference,
                  pr.id property_id,pr.name property_name,
                  p.id user_id,p.name reviewer_name,u.email reviewer_email
                from reviews r
                join reservations rs on rs.id=r.reservation_id
                join properties pr on pr.id=r.property_id
                join auth.users u on u.id=r.user_id
                left join profiles p on p.id=r.user_id
                where {' and '.join(where)}
                order by r.created_at desc
                limit %s""",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def review_counts():
    with db_connection() as conn:
        row=conn.execute(
            """select
                 count(*) total,
                 count(*) filter(where is_visible=true) visible,
                 count(*) filter(where is_visible=false) hidden,
                 coalesce(round(avg(rating) filter(where is_visible=true)::numeric,1),0) average_visible
               from reviews"""
        ).fetchone()
    return dict(row) if row else {"total":0,"visible":0,"hidden":0,"average_visible":0}


def set_review_visibility(review_id,is_visible,actor_user_id):
    with db_connection() as conn:
        with conn.transaction():
            before=conn.execute(
                """select r.*,rs.reference reservation_reference,pr.name property_name
                   from reviews r
                   join reservations rs on rs.id=r.reservation_id
                   join properties pr on pr.id=r.property_id
                   where r.id=%s
                   for update of r""",
                (review_id,),
            ).fetchone()
            if not before:
                raise RoyaError("REVIEW_NOT_FOUND","Review not found.",404)

            row=conn.execute(
                """update reviews
                   set is_visible=%s,updated_at=now()
                   where id=%s
                   returning id,user_id,property_id,reservation_id,rating,comment,is_visible,created_at,updated_at""",
                (is_visible,review_id),
            ).fetchone()

            conn.execute(
                """insert into audit_logs(
                     actor_user_id,property_id,action,entity_type,entity_id,before_json,after_json
                   ) values(%s,%s,'review.visibility_changed','review',%s,%s::jsonb,%s::jsonb)""",
                (
                    actor_user_id,
                    before["property_id"],
                    str(review_id),
                    json.dumps({"is_visible":before["is_visible"]}),
                    json.dumps({"is_visible":is_visible}),
                ),
            )

    result=dict(row)
    result["property_name"]=before["property_name"]
    result["reservation_reference"]=before["reservation_reference"]
    return result
