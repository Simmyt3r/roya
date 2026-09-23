from roya.common.db import db_connection
from roya.common.errors import RoyaError


def require_organization_member(user_id: str, organization_id: str, allowed_roles: set[str] | None = None):
    with db_connection() as conn:
        row = conn.execute(
            "select role from organization_members where organization_id=%s and user_id=%s and status='active'",
            (organization_id, user_id),
        ).fetchone()
    if not row:
        raise RoyaError("FORBIDDEN", "You do not have access to this organization.", 403)
    if allowed_roles and row["role"] not in allowed_roles:
        raise RoyaError("FORBIDDEN", "Your organization role cannot perform this action.", 403)
    return row["role"]
