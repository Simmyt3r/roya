from dataclasses import dataclass
from functools import wraps
from flask import g, request, session

from roya.common.db import supabase_anon_client
from roya.common.errors import RoyaError


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str | None = None


def _extract_access_token() -> str | None:
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer "):
        return bearer[7:].strip()
    return session.get("access_token")


def current_identity(required: bool = False) -> Identity | None:
    if hasattr(g, "roya_identity"):
        return g.roya_identity
    token = _extract_access_token()
    if not token:
        if required:
            raise RoyaError("AUTH_REQUIRED", "Authentication is required.", 401)
        g.roya_identity = None
        return None
    try:
        result = supabase_anon_client().auth.get_user(token)
        user = result.user
        identity = Identity(user_id=str(user.id), email=getattr(user, "email", None))
        g.roya_identity = identity
        return identity
    except Exception as exc:
        if required:
            raise RoyaError("AUTH_REQUIRED", "Your session is invalid or expired.", 401) from exc
        g.roya_identity = None
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        current_identity(required=True)
        return view(*args, **kwargs)
    return wrapped
