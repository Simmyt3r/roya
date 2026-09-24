import uuid
from flask import Blueprint, redirect, render_template, request, session
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import account_type_for_user, current_identity, login_required
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.response import ok
from roya.common.slug import slugify
from roya.reservations.service import ReservationService

bp = Blueprint("organizations", __name__)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


@bp.post("/api/v1/organizations")
@login_required
def create_organization():
    try:
        body = OrganizationCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR", "Invalid organization details.", 422, {"errors": exc.errors()}) from exc

    user = current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            org = conn.execute(
                "insert into organizations(name,slug,status) values(%s,%s,'active') returning *",
                (body.name, f"{slugify(body.name)}-{uuid.uuid4().hex[:6]}"),
            ).fetchone()
            conn.execute(
                "insert into organization_members(organization_id,user_id,role,status) values(%s,%s,'owner','active')",
                (org["id"], user.user_id),
            )
            conn.execute(
                "update profiles set account_type='hotel',updated_at=now() where id=%s",
                (user.user_id,),
            )

    session["account_type"] = "hotel"
    return ok({**dict(org), "redirect_to": "/partner"}, 201)


@bp.get("/partner/start")
@login_required
def partner_start():
    user = current_identity(required=True)
    with db_connection() as conn:
        organizations = list(
            conn.execute(
                """select o.id,o.name,o.slug,om.role
                   from organizations o
                   join organization_members om on om.organization_id=o.id
                   where om.user_id=%s and om.status='active'
                   order by o.name""",
                (user.user_id,),
            ).fetchall()
        )

    if organizations:
        with db_connection() as conn:
            conn.execute(
                "update profiles set account_type='hotel',updated_at=now() where id=%s",
                (user.user_id,),
            )
            conn.commit()
        session["account_type"] = "hotel"
        return redirect("/partner")

    return render_template("partner/start.html")


@bp.get("/partner")
@login_required
def partner_dashboard():
    user = current_identity(required=True)
    account_type = account_type_for_user(user.user_id)
    session["account_type"] = account_type
    session["user_email"] = user.email

    if account_type != "hotel":
        return redirect("/partner/start")

    with db_connection() as conn:
        organizations = list(
            conn.execute(
                """select o.id,o.name,o.slug,om.role
                   from organizations o join organization_members om on om.organization_id=o.id
                   where om.user_id=%s and om.status='active' order by o.name""",
                (user.user_id,),
            ).fetchall()
        )
        properties = list(
            conn.execute(
                """select p.id,p.name,p.slug,p.city,p.verification_status,p.status,o.name organization_name
                   from properties p join organizations o on o.id=p.organization_id
                   join organization_members om on om.organization_id=o.id
                   where om.user_id=%s and om.status='active' order by p.created_at desc""",
                (user.user_id,),
            ).fetchall()
        )

    if not organizations:
        return redirect("/partner/start")

    partner_reservations = ReservationService().list_for_partner(user.user_id, limit=50)
    pending_reservations = [r for r in partner_reservations if r["status"] == "pending_confirmation"][:20]

    return render_template(
        "partner/dashboard.html",
        organizations=organizations,
        properties=properties,
        pending_reservations=pending_reservations,
    )
