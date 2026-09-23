import hmac
from functools import wraps
from urllib.parse import urlsplit

from flask import current_app, request, session

from .errors import RoyaError


def require_cron_secret(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        configured = current_app.config.get("CRON_SECRET", "")
        supplied = request.headers.get("Authorization", "")
        candidate = supplied.removeprefix("Bearer ").strip()
        if not configured or not hmac.compare_digest(candidate, configured):
            raise RoyaError("FORBIDDEN", "Invalid cron authorization.", 403)
        return view(*args, **kwargs)

    return wrapped


def enforce_same_origin_for_cookie_mutations():
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return
    if not session.get("access_token"):
        return

    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    expected = f"{forwarded_proto or request.scheme}://{forwarded_host or request.host}".rstrip("/")

    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source:
        raise RoyaError("FORBIDDEN", "A same-origin browser request is required.", 403)

    parsed = urlsplit(source)
    source_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if not hmac.compare_digest(source_origin, expected):
        raise RoyaError("FORBIDDEN", "Cross-origin mutation rejected.", 403)
