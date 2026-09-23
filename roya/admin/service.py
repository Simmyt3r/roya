from functools import wraps
from flask import g
from roya.auth.service import current_identity
from roya.common.db import db_connection
from roya.common.errors import RoyaError


def require_platform_admin(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        identity=current_identity(required=True)
        with db_connection() as conn:
            row=conn.execute("select platform_role,status from profiles where id=%s",(identity.user_id,)).fetchone()
        if not row or row["platform_role"]!="admin" or row["status"]!="active":
            raise RoyaError("FORBIDDEN","Platform administrator access is required.",403)
        g.platform_admin=identity
        return view(*args,**kwargs)
    return wrapped
