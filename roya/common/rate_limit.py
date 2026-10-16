import hashlib
import hmac
import time
from datetime import datetime, timezone

from flask import current_app, request

from .db import db_connection
from .errors import RoyaError


def _client_address():
    forwarded=(request.headers.get("X-Forwarded-For") or "").split(",",1)[0].strip()
    return forwarded or request.remote_addr or "unknown"


def _subject_digest(subject):
    raw=str(subject or _client_address()).strip().lower().encode("utf-8")
    secret=(current_app.config.get("SECRET_KEY") or "").encode("utf-8")
    if secret:
        return hmac.new(secret,raw,hashlib.sha256).hexdigest()
    return hashlib.sha256(raw).hexdigest()


def enforce_rate_limit(scope,*,limit,window_seconds,subject=None):
    """Apply an atomic fixed-window rate limit backed by Postgres."""
    if limit<1 or window_seconds<1:
        raise ValueError("Rate-limit values must be positive.")

    # Unit tests use mocked request flows and should not create database state.
    if current_app.config.get("TESTING"):
        return 0
    if not current_app.config.get("DATABASE_URL"):
        return 0

    now=int(time.time())
    bucket=now-(now % int(window_seconds))
    window_start=datetime.fromtimestamp(bucket,tz=timezone.utc)
    subject_hash=_subject_digest(subject)

    with db_connection() as conn:
        row=conn.execute(
            """insert into private.request_rate_limits(
                 scope,subject_hash,window_start,request_count,updated_at
               ) values(%s,%s,%s,1,now())
               on conflict(scope,subject_hash,window_start)
               do update set
                 request_count=private.request_rate_limits.request_count+1,
                 updated_at=now()
               returning request_count""",
            (scope,subject_hash,window_start),
        ).fetchone()

        count=int(row["request_count"] or 0)
        if count==1:
            conn.execute(
                """delete from private.request_rate_limits
                   where window_start<now()-interval '2 days'"""
            )
        conn.commit()

    if count>int(limit):
        retry_after=max(1,bucket+int(window_seconds)-now)
        raise RoyaError(
            "RATE_LIMITED",
            "Too many requests. Try again shortly.",
            429,
            {"retry_after_seconds":retry_after},
        )
    return count
