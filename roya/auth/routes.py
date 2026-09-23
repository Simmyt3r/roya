from flask import Blueprint, render_template, request, session
from pydantic import ValidationError

from roya.common.db import supabase_anon_client
from roya.common.errors import RoyaError
from roya.common.response import ok
from .schemas import LoginInput, RegisterInput
from .service import current_identity, login_required

bp = Blueprint("auth", __name__)


def _payload(model):
    if not request.is_json:
        raise RoyaError("UNSUPPORTED_MEDIA_TYPE", "JSON request body required.", 415)
    data = request.get_json(silent=True)
    try:
        return model.model_validate(data or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR", "Please correct the submitted details.", 422, {"errors": exc.errors()}) from exc


@bp.get("/login")
def login_page():
    return render_template("auth/login.html")


@bp.get("/register")
def register_page():
    return render_template("auth/register.html")


@bp.post("/api/v1/auth/register")
def register():
    body = _payload(RegisterInput)
    client = supabase_anon_client()
    try:
        result = client.auth.sign_up({"email": str(body.email), "password": body.password, "options": {"data": {"name": body.name}}})
    except Exception as exc:
        raise RoyaError("AUTH_REGISTRATION_FAILED", "Registration could not be completed.", 400) from exc
    if result.session:
        session["access_token"] = result.session.access_token
        session["refresh_token"] = result.session.refresh_token
    return ok({"user_id": str(result.user.id), "email_confirmation_required": result.session is None}, 201)


@bp.post("/api/v1/auth/login")
def login():
    body = _payload(LoginInput)
    try:
        result = supabase_anon_client().auth.sign_in_with_password({"email": str(body.email), "password": body.password})
    except Exception as exc:
        raise RoyaError("AUTH_FAILED", "Invalid email or password.", 401) from exc
    session["access_token"] = result.session.access_token
    session["refresh_token"] = result.session.refresh_token
    return ok({"user_id": str(result.user.id)})


@bp.post("/api/v1/auth/logout")
def logout():
    if not request.is_json:
        raise RoyaError("UNSUPPORTED_MEDIA_TYPE", "JSON request body required.", 415)
    session.clear()
    return ok({})


@bp.get("/api/v1/auth/me")
@login_required
def me():
    identity = current_identity(required=True)
    return ok({"id": identity.user_id, "email": identity.email})
