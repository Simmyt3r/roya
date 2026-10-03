import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError


class ReviewService:
    def create(self,user_id,payload):
        comment=(payload.comment or "").strip()
        with db_connection() as conn:
            with conn.transaction():
                reservation=conn.execute(
                    """select r.id,r.property_id,r.organization_id,r.status,r.user_id,p.name property_name
                       from reservations r
                       join properties p on p.id=r.property_id
                       where r.id=%s and r.user_id=%s
                       for update of r""",
                    (str(payload.reservation_id),user_id),
                ).fetchone()
                if not reservation:
                    raise RoyaError("NOT_FOUND","Reservation not found.",404)
                if reservation["status"]!="checked_out":
                    raise RoyaError(
                        "REVIEW_NOT_ELIGIBLE",
                        "You can review this stay after checkout is completed.",
                        409,
                    )

                existing=conn.execute(
                    """select id from reviews
                       where reservation_id=%s and user_id=%s""",
                    (str(payload.reservation_id),user_id),
                ).fetchone()
                if existing:
                    raise RoyaError(
                        "REVIEW_ALREADY_SUBMITTED",
                        "A review has already been submitted for this stay.",
                        409,
                    )

                row=conn.execute(
                    """insert into reviews(user_id,property_id,reservation_id,rating,comment)
                       values(%s,%s,%s,%s,%s)
                       returning id,user_id,property_id,reservation_id,rating,comment,is_visible,created_at,updated_at""",
                    (
                        user_id,
                        reservation["property_id"],
                        str(payload.reservation_id),
                        payload.rating,
                        comment,
                    ),
                ).fetchone()

                conn.execute(
                    """insert into audit_logs(
                         actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
                       ) values(%s,%s,%s,'review.created','review',%s,%s::jsonb)""",
                    (
                        user_id,
                        reservation["organization_id"],
                        reservation["property_id"],
                        str(row["id"]),
                        json.dumps({
                            "reservation_id":str(payload.reservation_id),
                            "rating":payload.rating,
                        }),
                    ),
                )

        result=dict(row)
        result["property_name"]=reservation["property_name"]
        return result

    def for_reservation(self,reservation_id,user_id):
        with db_connection() as conn:
            row=conn.execute(
                """select id,rating,comment,is_visible,created_at,updated_at
                   from reviews
                   where reservation_id=%s and user_id=%s""",
                (reservation_id,user_id),
            ).fetchone()
        return dict(row) if row else None

    def list_public(self,property_id,limit=20):
        limit=max(1,min(int(limit),50))
        with db_connection() as conn:
            rows=conn.execute(
                """select r.id,r.rating,r.comment,r.created_at,
                          coalesce(nullif(split_part(p.name,' ',1),''),'Guest') reviewer_name
                   from reviews r
                   left join profiles p on p.id=r.user_id
                   where r.property_id=%s and r.is_visible=true
                   order by r.created_at desc
                   limit %s""",
                (property_id,limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self,property_id):
        with db_connection() as conn:
            row=conn.execute(
                """select count(*) review_count,
                          coalesce(round(avg(rating)::numeric,1),0) average_rating
                   from reviews
                   where property_id=%s and is_visible=true""",
                (property_id,),
            ).fetchone()
        return dict(row) if row else {"review_count":0,"average_rating":0}
