from dataclasses import dataclass
from functools import wraps
from flask import g, request, session

from roya.common.db import supabase_anon_client
from roya.common.errors import RoyaError


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str | None = None


def _extract_access_token() -> tuple[str | None, bool]:
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer "):
        return bearer[7:].strip(), False
    return session.get("access_token"), True


def _identity_from_token(client, token: str) -> Identity:
    result = client.auth.get_user(token)
    user = result.user
    return Identity(user_id=str(user.id), email=getattr(user, "email", None))


def current_identity(required: bool = False) -> Identity | None:
    if hasattr(g, "roya_identity"):
        return g.roya_identity

    token, cookie_backed = _extract_access_token()
    if not token:
        if required:
            raise RoyaError("AUTH_REQUIRED", "Authentication is required.", 401)
        g.roya_identity = None
        return None

    client = supabase_anon_client()
    try:
        identity = _identity_from_token(client, token)
        g.roya_identity = identity
        return identity
    except Exception as original_exc:
        refresh_token = session.get("refresh_token") if cookie_backed else None
        if refresh_token:
            try:
                refreshed = client.auth.refresh_session(refresh_token)
                refreshed_session = refreshed.session
                if refreshed_session:
                    session["access_token"] = refreshed_session.access_token
                    session["refresh_token"] = refreshed_session.refresh_token
                    identity = _identity_from_token(client, refreshed_session.access_token)
                    g.roya_identity = identity
                    return identity
            except Exception:
                session.clear()

        if required:
            raise RoyaError("AUTH_REQUIRED", "Your session is invalid or expired.", 401) from original_exc
        g.roya_identity = None
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        current_identity(required=True)
        return view(*args, **kwargs)

    return wrapped
