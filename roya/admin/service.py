from functools import wraps
from flask import g
from roya.auth.service import current_identity
from roya.common.db import db_connection
from roya.common.errors import RoyaError


def require_platform_roles(*allowed_roles):
    allowed=set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            identity=current_identity(required=True)
            with db_connection() as conn:
                row=conn.execute(
                    "select platform_role,status from profiles where id=%s",
                    (identity.user_id,),
                ).fetchone()
            if not row or row["status"]!="active" or row["platform_role"] not in allowed:
                raise RoyaError("FORBIDDEN","This platform role does not have access to this area.",403)
            g.platform_identity=identity
            g.platform_role=row["platform_role"]
            if row["platform_role"]=="admin":
                g.platform_admin=identity
            return view(*args,**kwargs)
        return wrapped
    return decorator


def require_platform_admin(view):
    return require_platform_roles("admin")(view)
