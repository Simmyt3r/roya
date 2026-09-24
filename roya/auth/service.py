import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, g, request, session

from roya.common.db import db_connection, supabase_anon_client
from roya.common.errors import RoyaError


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str | None = None


def _session_hash(raw_session_id: str) -> str:
    return hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()


def create_server_session(result) -> str:
    auth_session=getattr(result,"session",None)
    user=getattr(result,"user",None)
    if not auth_session or not user:
        raise RoyaError("AUTH_SESSION_MISSING","Authentication session was not returned.",503)

    raw_session_id=secrets.token_urlsafe(32)
    session_hash=_session_hash(raw_session_id)
    ttl_days=max(1,int(current_app.config.get("SESSION_TTL_DAYS",30)))
    expires_at=datetime.now(timezone.utc)+timedelta(days=ttl_days)

    with db_connection() as conn:
        with conn.transaction():
            conn.execute(
                """delete from private.app_sessions
                   where user_id=%s and (expires_at<=now() or revoked_at is not null)""",
                (str(user.id),),
            )
            conn.execute(
                """insert into private.app_sessions(
                     session_hash,user_id,access_token,refresh_token,expires_at
                   ) values(%s,%s,%s,%s,%s)""",
                (
                    session_hash,
                    str(user.id),
                    auth_session.access_token,
                    auth_session.refresh_token,
                    expires_at,
                ),
            )

    return raw_session_id


def revoke_server_session(raw_session_id: str | None) -> None:
    if not raw_session_id:
        return
    with db_connection() as conn:
        conn.execute(
            """update private.app_sessions
               set revoked_at=coalesce(revoked_at,now()),updated_at=now()
               where session_hash=%s""",
            (_session_hash(raw_session_id),),
        )
        conn.commit()


def _load_server_session(raw_session_id: str):
    with db_connection() as conn:
        return conn.execute(
            """select session_hash,user_id,access_token,refresh_token,expires_at
               from private.app_sessions
               where session_hash=%s
                 and revoked_at is null
                 and expires_at>now()""",
            (_session_hash(raw_session_id),),
        ).fetchone()


def _update_server_session(raw_session_id: str,access_token: str,refresh_token: str) -> None:
    with db_connection() as conn:
        row=conn.execute(
            """update private.app_sessions
               set access_token=%s,refresh_token=%s,last_seen_at=now(),updated_at=now()
               where session_hash=%s
                 and revoked_at is null
                 and expires_at>now()
               returning session_hash""",
            (access_token,refresh_token,_session_hash(raw_session_id)),
        ).fetchone()
        conn.commit()
    if not row:
        raise RoyaError("AUTH_REQUIRED","Your session is invalid or expired.",401)


def _extract_access_context():
    bearer=request.headers.get("Authorization","")
    if bearer.startswith("Bearer "):
        return bearer[7:].strip(),False,None,None

    raw_session_id=session.get("sid")
    if not raw_session_id:
        return None,True,None,None

    stored=_load_server_session(raw_session_id)
    if not stored:
        session.clear()
        return None,True,None,None

    return stored["access_token"],True,raw_session_id,stored["refresh_token"]


def _identity_from_token(client,token: str) -> Identity:
    result=client.auth.get_user(token)
    user=result.user
    return Identity(user_id=str(user.id),email=getattr(user,"email",None))


def current_identity(required: bool=False) -> Identity | None:
    if hasattr(g,"roya_identity"):
        return g.roya_identity

    token,cookie_backed,raw_session_id,refresh_token=_extract_access_context()
    if not token:
        if required:
            raise RoyaError("AUTH_REQUIRED","Authentication is required.",401)
        g.roya_identity=None
        return None

    client=supabase_anon_client()
    try:
        identity=_identity_from_token(client,token)
        g.roya_identity=identity
        return identity
    except Exception as original_exc:
        if cookie_backed and raw_session_id and refresh_token:
            try:
                refreshed=client.auth.refresh_session(refresh_token)
                refreshed_session=refreshed.session
                if refreshed_session:
                    _update_server_session(
                        raw_session_id,
                        refreshed_session.access_token,
                        refreshed_session.refresh_token,
                    )
                    identity=_identity_from_token(client,refreshed_session.access_token)
                    g.roya_identity=identity
                    return identity
            except Exception:
                try:
                    revoke_server_session(raw_session_id)
                finally:
                    session.clear()

        if required:
            raise RoyaError("AUTH_REQUIRED","Your session is invalid or expired.",401) from original_exc
        g.roya_identity=None
        return None


def account_profile(user_id: str):
    with db_connection() as conn:
        profile=conn.execute(
            """select id,name,phone,avatar_path,account_type,platform_role,status
               from profiles where id=%s""",
            (user_id,),
        ).fetchone()
    if not profile:
        raise RoyaError("PROFILE_NOT_FOUND","Your account profile is unavailable.",404)
    return profile


def account_type_for_user(user_id: str) -> str:
    return account_profile(user_id)["account_type"]


def require_account_type(expected: str):
    identity=current_identity(required=True)
    actual=account_type_for_user(identity.user_id)
    if actual!=expected:
        raise RoyaError(
            "ACCOUNT_TYPE_REQUIRED",
            f"This area requires a {expected} account.",
            403,
            {"account_type":actual},
        )
    return identity


def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        current_identity(required=True)
        return view(*args,**kwargs)

    return wrapped
