from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from flask import current_app
from supabase import create_client

from .errors import RoyaError


def database_url() -> str:
    url = current_app.config.get("DATABASE_URL", "")
    if not url:
        raise RoyaError("DATABASE_NOT_CONFIGURED", "Database connection is not configured.", 503)
    return url


@contextmanager
def db_connection():
    conn = psycopg.connect(database_url(), row_factory=dict_row, prepare_threshold=None)
    try:
        yield conn
    finally:
        conn.close()


def supabase_anon_client():
    url = current_app.config.get("SUPABASE_URL", "")
    key = current_app.config.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not url or not key:
        raise RoyaError("SUPABASE_NOT_CONFIGURED", "Supabase is not configured.", 503)
    return create_client(url, key)


def supabase_admin_client():
    url = current_app.config.get("SUPABASE_URL", "")
    key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RoyaError("SUPABASE_ADMIN_NOT_CONFIGURED", "Supabase privileged access is not configured.", 503)
    return create_client(url, key)
