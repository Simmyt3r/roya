from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from roya.common.db import db_connection
from roya.common.errors import RoyaError


UNSUBSCRIBE_SALT = "iroya-marketing-unsubscribe-v1"


def _normalize_email(email):
    return str(email or "").strip().lower()


def _serializer():
    secret = current_app.config.get("SECRET_KEY") or ""
    if not secret:
        raise RoyaError("UNSUBSCRIBE_UNAVAILABLE", "Email preference management is unavailable.", 503)
    return URLSafeSerializer(secret, salt=UNSUBSCRIBE_SALT)


def create_unsubscribe_token(email):
    normalized = _normalize_email(email)
    if not normalized or "@" not in normalized:
        raise RoyaError("INVALID_EMAIL", "A valid email address is required.", 422)
    return _serializer().dumps({"email": normalized})


def unsubscribe_url(email):
    base = (current_app.config.get("APP_URL") or "").rstrip("/")
    path = f"/email/unsubscribe/{create_unsubscribe_token(email)}"
    return f"{base}{path}" if base else path


def _email_from_token(token):
    try:
        payload = _serializer().loads(token)
    except BadSignature as exc:
        raise RoyaError(
            "INVALID_UNSUBSCRIBE_LINK",
            "This unsubscribe link is invalid.",
            400,
        ) from exc

    email = _normalize_email((payload or {}).get("email"))
    if not email or "@" not in email:
        raise RoyaError(
            "INVALID_UNSUBSCRIBE_LINK",
            "This unsubscribe link is invalid.",
            400,
        )
    return email


def _mask_email(email):
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    hidden = "*" * max(2, min(len(local) - len(visible), 6))
    return f"{visible}{hidden}@{domain}"


def preview_unsubscribe(token):
    email = _email_from_token(token)
    return {"masked_email": _mask_email(email)}


def unsubscribe_by_token(token):
    email = _email_from_token(token)
    with db_connection() as conn:
        row = conn.execute(
            """update private.marketing_subscribers
               set unsubscribed_at=coalesce(unsubscribed_at,now()),
                   updated_at=now()
               where lower(email)=lower(%s)
               returning id::text id,email,unsubscribed_at""",
            (email,),
        ).fetchone()
        conn.commit()

    return {
        "unsubscribed": True,
        "masked_email": _mask_email(email),
        "subscriber_found": bool(row),
    }
