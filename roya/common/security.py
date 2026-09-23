import hmac
from functools import wraps
from flask import current_app, request

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
