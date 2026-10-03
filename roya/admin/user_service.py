import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError


def search_user_accounts(query="",status="",limit=100):
    query=(query or "").strip()
    status=(status or "").strip()
    limit=max(1,min(int(limit),200))
    where=["1=1"]
    params=[]

    if query:
        needle=f"%{query}%"
        where.append("(u.email ilike %s or coalesce(p.name,'') ilike %s or coalesce(p.phone,'') ilike %s)")
        params.extend([needle,needle,needle])
    if status in {"active","suspended","pending_verification"}:
        where.append("p.status=%s")
        params.append(status)

    params.append(limit)
    with db_connection() as conn:
        rows=conn.execute(
            f"""select
                  p.id,p.name,p.phone,p.account_type,p.platform_role,p.status,
                  p.created_at,p.updated_at,u.email,u.last_sign_in_at,
                  (select count(*) from reservations r where r.user_id=p.id) reservation_count,
                  (select count(*) from organization_members om
                     where om.user_id=p.id and om.status='active') organization_count
                from profiles p
                join auth.users u on u.id=p.id
                where {' and '.join(where)}
                order by
                  case p.status when 'suspended' then 0 when 'pending_verification' then 1 else 2 end,
                  p.created_at desc
                limit %s""",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def change_user_status(user_id,status,actor_user_id):
    if status not in {"active","suspended"}:
        raise RoyaError("VALIDATION_ERROR","User status must be active or suspended.",422)
    if str(user_id)==str(actor_user_id):
        raise RoyaError(
            "SELF_STATUS_CHANGE_FORBIDDEN",
            "Use another platform administrator for changes to your own account.",
            409,
        )

    with db_connection() as conn:
        with conn.transaction():
            before=conn.execute(
                """select p.id,p.name,p.account_type,p.platform_role,p.status,u.email
                   from profiles p
                   join auth.users u on u.id=p.id
                   where p.id=%s
                   for update of p""",
                (user_id,),
            ).fetchone()
            if not before:
                raise RoyaError("USER_NOT_FOUND","User account not found.",404)
            if before["platform_role"]=="admin":
                raise RoyaError(
                    "ADMIN_STATUS_CHANGE_RESTRICTED",
                    "Platform administrator accounts require a separate privileged recovery process.",
                    409,
                )

            row=conn.execute(
                """update profiles
                   set status=%s,updated_at=now()
                   where id=%s
                   returning id,name,phone,account_type,platform_role,status,created_at,updated_at""",
                (status,user_id),
            ).fetchone()

            revoked_sessions=0
            if status=="suspended":
                result=conn.execute(
                    """update private.app_sessions
                       set revoked_at=coalesce(revoked_at,now()),updated_at=now()
                       where user_id=%s and revoked_at is null""",
                    (user_id,),
                )
                revoked_sessions=max(int(result.rowcount or 0),0)

            conn.execute(
                """insert into audit_logs(
                     actor_user_id,action,entity_type,entity_id,before_json,after_json
                   ) values(%s,'user.status_changed','user',%s,%s::jsonb,%s::jsonb)""",
                (
                    actor_user_id,
                    str(user_id),
                    json.dumps({
                        "status":before["status"],
                        "platform_role":before["platform_role"],
                    }),
                    json.dumps({
                        "status":status,
                        "revoked_sessions":revoked_sessions,
                    }),
                ),
            )

    result=dict(row)
    result["email"]=before["email"]
    result["previous_status"]=before["status"]
    result["revoked_sessions"]=revoked_sessions
    return result


def user_account_counts():
    with db_connection() as conn:
        row=conn.execute(
            """select
                 count(*) total,
                 count(*) filter(where status='active') active,
                 count(*) filter(where status='suspended') suspended,
                 count(*) filter(where status='pending_verification') pending_verification,
                 count(*) filter(where account_type='guest') guests,
                 count(*) filter(where account_type='hotel') hotels
               from profiles"""
        ).fetchone()
    return dict(row) if row else {
        "total":0,"active":0,"suspended":0,"pending_verification":0,"guests":0,"hotels":0,
    }
