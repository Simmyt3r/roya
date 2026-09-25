from urllib.parse import urlsplit
from flask import Blueprint, render_template, request, session
from pydantic import BaseModel, Field, ValidationError

from roya.common.db import db_connection, supabase_anon_client
from roya.common.errors import RoyaError
from roya.common.response import ok
from .schemas import LoginInput, RegisterInput
from .service import account_profile, create_server_session, current_identity, login_required, revoke_server_session

bp = Blueprint("auth", __name__)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2,max_length=120)
    phone: str | None = Field(default=None,max_length=30)


def _safe_next_path(value):
    if not value or len(value)>2048:
        return None
    value=str(value).strip()
    if not value.startswith("/") or value.startswith("//"):
        return None
    parsed=urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


def _payload(model):
    if not request.is_json:
        raise RoyaError("UNSUPPORTED_MEDIA_TYPE", "JSON request body required.", 415)
    data = request.get_json(silent=True)
    try:
        return model.model_validate(data or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR", "Please correct the submitted details.", 422, {"errors": exc.errors()}) from exc


def _store_session(result, account_type: str, name: str | None = None, platform_role: str = "user"):
    raw_session_id=create_server_session(result)
    session.clear()
    session["sid"]=raw_session_id
    session["account_type"]=account_type
    session["platform_role"]=platform_role
    session["user_email"]=getattr(result.user,"email",None)
    if name:
        session["user_name"]=name
    session.permanent=True


@bp.get("/login")
def login_page():
    return render_template(
        "auth/login.html",
        next_path=_safe_next_path(request.args.get("next")),
    )


@bp.get("/register")
def register_page():
    return render_template(
        "auth/register.html",
        next_path=_safe_next_path(request.args.get("next")),
    )


@bp.post("/api/v1/auth/register")
def register():
    body = _payload(RegisterInput)
    client = supabase_anon_client()
    try:
        result = client.auth.sign_up(
            {
                "email": str(body.email),
                "password": body.password,
                "options": {"data": {"name": body.name, "account_type": body.account_type}},
            }
        )
    except Exception as exc:
        raise RoyaError("AUTH_REGISTRATION_FAILED", "Registration could not be completed.", 400) from exc

    safe_next=_safe_next_path(body.next_path)
    redirect_to = f"/invite/{body.invite_token}" if body.invite_token else (safe_next or ("/partner/start" if body.account_type == "hotel" else "/account"))
    if result.session:
        _store_session(result, body.account_type, body.name)

    return ok(
        {
            "user_id": str(result.user.id),
            "account_type": body.account_type,
            "redirect_to": redirect_to,
            "email_confirmation_required": result.session is None,
        },
        201,
    )


@bp.post("/api/v1/auth/login")
def login():
    body = _payload(LoginInput)
    try:
        result = supabase_anon_client().auth.sign_in_with_password(
            {"email": str(body.email), "password": body.password}
        )
    except Exception as exc:
        raise RoyaError("AUTH_FAILED", "Invalid email or password.", 401) from exc

    profile = account_profile(str(result.user.id))
    _store_session(result, profile["account_type"], profile.get("name"), profile["platform_role"])
    safe_next=_safe_next_path(body.next_path)
    redirect_to = f"/invite/{body.invite_token}" if body.invite_token else (safe_next or ("/partner" if profile["account_type"] == "hotel" else "/account"))

    return ok(
        {
            "user_id": str(result.user.id),
            "account_type": profile["account_type"],
            "redirect_to": redirect_to,
        }
    )


@bp.post("/api/v1/auth/logout")
def logout():
    if not request.is_json:
        raise RoyaError("UNSUPPORTED_MEDIA_TYPE", "JSON request body required.", 415)
    raw_session_id=session.get("sid")
    if raw_session_id:
        revoke_server_session(raw_session_id)
    session.clear()
    return ok({})


@bp.get("/api/v1/auth/me")
@login_required
def me():
    identity = current_identity(required=True)
    profile = account_profile(identity.user_id)
    return ok(
        {
            "id": identity.user_id,
            "email": identity.email,
            "name": profile["name"],
            "phone": profile["phone"],
            "account_type": profile["account_type"],
            "platform_role": profile["platform_role"],
        }
    )


@bp.put("/api/v1/auth/profile")
@login_required
def update_profile():
    body=_payload(ProfileUpdate)
    identity=current_identity(required=True)
    with db_connection() as conn:
        row=conn.execute(
            """update profiles set name=%s,phone=%s,updated_at=now()
               where id=%s returning id,name,phone,account_type,platform_role,status""",
            (body.name,body.phone,identity.user_id),
        ).fetchone()
        conn.commit()
    session["user_name"]=row["name"]
    return ok({**dict(row),"email":identity.email})


@bp.get("/account")
@login_required
def account_page():
    identity = current_identity(required=True)
    profile = account_profile(identity.user_id)
    session["account_type"] = profile["account_type"]
    session["user_email"] = identity.email
    session["user_name"] = profile.get("name")
    session["platform_role"] = profile["platform_role"]

    with db_connection() as conn:
        reservations = list(
            conn.execute(
                """select id,reference,check_in,check_out,nights,status,payment_status,
                          total_price_minor,currency,guest_name,
                          (select name from properties p where p.id=reservations.property_id) property_name
                   from reservations
                   where user_id=%s
                   order by created_at desc
                   limit 30""",
                (identity.user_id,),
            ).fetchall()
        )

    return render_template(
        "guest/account.html",
        profile=profile,
        email=identity.email,
        reservations=reservations,
    )
