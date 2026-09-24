import hashlib
import secrets
from datetime import datetime,timedelta,timezone

from flask import current_app

from roya.common.db import db_connection
from roya.common.errors import RoyaError


INVITE_TTL_DAYS=7
ALLOWED_INVITE_ROLES={"manager","reservations","finance","staff"}


def _token_hash(token:str)->str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email:str)->str:
    return email.strip().lower()


def build_invite_url(token:str)->str:
    base=(current_app.config.get("APP_URL") or "").rstrip("/")
    return f"{base}/invite/{token}" if base else f"/invite/{token}"


def issue_invite(conn,*,organization_id,email,role,actor_user_id,actor_role):
    normalized=_normalize_email(email)
    if role not in ALLOWED_INVITE_ROLES:
        raise RoyaError("VALIDATION_ERROR","Unsupported hotel team role.",422)
    if actor_role not in {"owner","manager"}:
        raise RoyaError("FORBIDDEN","Only hotel owners and managers can invite team members.",403)
    if actor_role=="manager" and role=="manager":
        raise RoyaError("FORBIDDEN","Only an owner can invite another manager.",403)

    organization=conn.execute(
        "select id,name from organizations where id=%s",
        (organization_id,),
    ).fetchone()
    if not organization:
        raise RoyaError("ORGANIZATION_NOT_FOUND","Hotel organization not found.",404)

    conn.execute(
        """update organization_invites
           set status='revoked',updated_at=now()
           where organization_id=%s
             and lower(email)=lower(%s)
             and status='pending'""",
        (organization_id,normalized),
    )

    token=secrets.token_urlsafe(32)
    expires_at=datetime.now(timezone.utc)+timedelta(days=INVITE_TTL_DAYS)
    invite=conn.execute(
        """insert into organization_invites(
             organization_id,email,role,token_hash,status,invited_by_user_id,expires_at
           ) values(%s,%s,%s,%s,'pending',%s,%s)
           returning id,organization_id,email,role,status,expires_at,created_at""",
        (
            organization_id,
            normalized,
            role,
            _token_hash(token),
            actor_user_id,
            expires_at,
        ),
    ).fetchone()

    conn.execute(
        """insert into audit_logs(
             actor_user_id,organization_id,action,entity_type,entity_id,before_json,after_json
           ) values(%s,%s,'organization.invite_created','organization_invite',%s,'{}'::jsonb,%s::jsonb)""",
        (
            actor_user_id,
            organization_id,
            str(invite["id"]),
            '{"email":"'+normalized.replace('"','')+'","role":"'+role+'"}',
        ),
    )

    return {
        **dict(invite),
        "organization_name":organization["name"],
        "invite_url":build_invite_url(token),
    }


def preview_invite(token:str):
    token_hash=_token_hash(token)
    with db_connection() as conn:
        invite=conn.execute(
            """select oi.id,oi.organization_id,o.name organization_name,
                      oi.email,oi.role,oi.status,oi.expires_at
               from organization_invites oi
               join organizations o on o.id=oi.organization_id
               where oi.token_hash=%s""",
            (token_hash,),
        ).fetchone()
    if not invite:
        raise RoyaError("INVITE_NOT_FOUND","This hotel invitation is invalid.",404)
    if invite["status"]!="pending":
        raise RoyaError("INVITE_UNAVAILABLE","This hotel invitation is no longer available.",409)
    if invite["expires_at"]<=datetime.now(timezone.utc):
        raise RoyaError("INVITE_EXPIRED","This hotel invitation has expired.",410)
    return invite


def accept_invite(token:str,*,user_id,user_email):
    token_hash=_token_hash(token)
    normalized=_normalize_email(user_email or "")
    with db_connection() as conn:
        with conn.transaction():
            invite=conn.execute(
                """select oi.*,o.name organization_name
                   from organization_invites oi
                   join organizations o on o.id=oi.organization_id
                   where oi.token_hash=%s
                   for update of oi""",
                (token_hash,),
            ).fetchone()
            if not invite:
                raise RoyaError("INVITE_NOT_FOUND","This hotel invitation is invalid.",404)
            if invite["status"]!="pending":
                raise RoyaError("INVITE_UNAVAILABLE","This hotel invitation is no longer available.",409)
            if invite["expires_at"]<=datetime.now(timezone.utc):
                conn.execute(
                    "update organization_invites set status='expired',updated_at=now() where id=%s",
                    (invite["id"],),
                )
                raise RoyaError("INVITE_EXPIRED","This hotel invitation has expired.",410)
            if _normalize_email(invite["email"])!=normalized:
                raise RoyaError(
                    "INVITE_EMAIL_MISMATCH",
                    "Sign in with the email address this hotel invitation was sent to.",
                    403,
                )

            existing=conn.execute(
                """select role,status from organization_members
                   where organization_id=%s and user_id=%s
                   for update""",
                (invite["organization_id"],user_id),
            ).fetchone()

            if existing and existing["role"]=="owner":
                role="owner"
                conn.execute(
                    """update organization_members set status='active'
                       where organization_id=%s and user_id=%s""",
                    (invite["organization_id"],user_id),
                )
            else:
                role=invite["role"]
                conn.execute(
                    """insert into organization_members(organization_id,user_id,role,status)
                       values(%s,%s,%s,'active')
                       on conflict(organization_id,user_id)
                       do update set role=excluded.role,status='active'""",
                    (invite["organization_id"],user_id,role),
                )

            conn.execute(
                "update profiles set account_type='hotel',updated_at=now() where id=%s",
                (user_id,),
            )
            conn.execute(
                """update organization_invites
                   set status='accepted',accepted_by_user_id=%s,accepted_at=now(),updated_at=now()
                   where id=%s""",
                (user_id,invite["id"]),
            )
            conn.execute(
                """insert into audit_logs(
                     actor_user_id,organization_id,action,entity_type,entity_id,before_json,after_json
                   ) values(%s,%s,'organization.invite_accepted','organization_invite',%s,'{}'::jsonb,%s::jsonb)""",
                (
                    user_id,
                    invite["organization_id"],
                    str(invite["id"]),
                    '{"role":"'+str(role).replace('"','')+'"}',
                ),
            )

    return {
        "organization_id":str(invite["organization_id"]),
        "organization_name":invite["organization_name"],
        "role":role,
        "redirect_to":"/partner",
    }


def revoke_invite(invite_id,*,organization_id,actor_user_id):
    with db_connection() as conn:
        with conn.transaction():
            actor=conn.execute(
                """select role from organization_members
                   where organization_id=%s and user_id=%s and status='active'
                   for update""",
                (organization_id,actor_user_id),
            ).fetchone()
            if not actor or actor["role"] not in {"owner","manager"}:
                raise RoyaError("FORBIDDEN","Only hotel owners and managers can revoke invitations.",403)

            invite=conn.execute(
                """select * from organization_invites
                   where id=%s and organization_id=%s
                   for update""",
                (invite_id,organization_id),
            ).fetchone()
            if not invite:
                raise RoyaError("INVITE_NOT_FOUND","Hotel invitation not found.",404)
            if actor["role"]=="manager" and invite["role"]=="manager":
                raise RoyaError("FORBIDDEN","Only an owner can manage manager invitations.",403)
            if invite["status"]!="pending":
                raise RoyaError("INVITE_UNAVAILABLE","This invitation is no longer pending.",409)

            conn.execute(
                """update organization_invites
                   set status='revoked',updated_at=now()
                   where id=%s""",
                (invite_id,),
            )
            conn.execute(
                """insert into audit_logs(
                     actor_user_id,organization_id,action,entity_type,entity_id,before_json,after_json
                   ) values(%s,%s,'organization.invite_revoked','organization_invite',%s,%s::jsonb,'{"status":"revoked"}'::jsonb)""",
                (
                    actor_user_id,
                    organization_id,
                    str(invite_id),
                    '{"email":"'+str(invite["email"]).replace('"','')+'","role":"'+str(invite["role"]).replace('"','')+'","status":"pending"}',
                ),
            )
    return {"revoked":True,"invite_id":str(invite_id)}
