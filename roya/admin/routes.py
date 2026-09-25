import json
import re
from flask import Blueprint,current_app,g,render_template,request
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator, model_validator
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.integrations import (
    integration_status, paystack_settings, save_integration, smtp_settings,
)
from roya.common.response import ok
from .service import require_platform_admin

bp=Blueprint("admin",__name__)


class SmtpConfiguration(BaseModel):
    host: str = Field(min_length=4,max_length=255)
    port: int = Field(ge=1,le=65535)
    security: str
    username: str = Field(min_length=1,max_length=255)
    sender: EmailStr
    password: str | None = Field(default=None,max_length=512)

    @field_validator("host")
    @classmethod
    def valid_host(cls,value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]",value) or ".." in value:
            raise ValueError("Use a hostname such as smtp.example.com.")
        return value

    @model_validator(mode="after")
    def valid_security(self):
        if (self.security,self.port) not in {
            ("ssl",465),("starttls",587),("starttls",2525)
        }:
            raise ValueError("Use SSL on 465 or STARTTLS on 587 or 2525.")
        return self


class PaystackConfiguration(BaseModel):
    public_key: str = Field(min_length=12,max_length=256)
    secret_key: str | None = Field(default=None,max_length=256)

    @field_validator("public_key")
    @classmethod
    def valid_public_key(cls,value):
        if not re.fullmatch(r"pk_(test|live)_[A-Za-z0-9_-]{4,}",value):
            raise ValueError("Enter a Paystack public key.")
        return value


def _configuration_payload(schema):
    if not request.is_json:
        raise RoyaError("UNSUPPORTED_MEDIA_TYPE","JSON request body required.",415)
    try:
        return schema.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        # Pydantic errors may include the submitted secret; never echo them.
        raise RoyaError("VALIDATION_ERROR","Check the integration settings and try again.",422) from exc


@bp.get("/admin")
@require_platform_admin
def dashboard():
    with db_connection() as conn:
        metrics=conn.execute(
            """select
               (select count(*) from properties where verification_status='pending') pending_properties,
               (select count(*) from properties where verification_status='verified') verified_properties,
               (select count(*) from reservations where created_at>=date_trunc('month',now())) reservations_this_month,
               (select coalesce(sum(amount_minor),0) from payment_transactions where status='successful' and created_at>=date_trunc('month',now())) volume_this_month_minor"""
        ).fetchone()
        pending=list(conn.execute(
            """select p.id,p.name,p.city,p.state,p.created_at,
                      exists(select 1 from room_types rt where rt.property_id=p.id and rt.status='active') has_room,
                      exists(select 1 from rate_plans rp join room_types rt on rt.id=rp.room_type_id
                             where rt.property_id=p.id and rt.status='active' and rp.status='active') has_rate,
                      exists(select 1 from inventory_days i join room_types rt on rt.id=i.room_type_id
                             where rt.property_id=p.id and rt.status='active' and i.date>=current_date
                               and i.stop_sell=false and (i.total_inventory-i.held_inventory-i.sold_inventory)>0) has_inventory
               from properties p
               where p.verification_status='pending'
               order by p.created_at asc limit 50"""
        ).fetchall())
    return render_template(
        "admin/dashboard.html",metrics=metrics,pending=pending,
        smtp=integration_status("smtp"),paystack=integration_status("paystack"),
        paystack_webhook_url=(current_app.config["APP_URL"].rstrip("/")+"/api/webhooks/paystack"),
    )


@bp.put("/api/v1/admin/integrations/smtp")
@require_platform_admin
def save_smtp():
    body=_configuration_payload(SmtpConfiguration)
    save_integration("smtp",{
        "host":body.host,"port":body.port,"security":body.security,
        "username":body.username,"sender":str(body.sender),
    },body.password or None,g.platform_admin.user_id)
    return ok(integration_status("smtp"))


@bp.put("/api/v1/admin/integrations/paystack")
@require_platform_admin
def save_paystack():
    body=_configuration_payload(PaystackConfiguration)
    secret=(body.secret_key or "").strip()
    if secret and not re.fullmatch(r"sk_(test|live)_[A-Za-z0-9_-]{4,}",secret):
        raise RoyaError("VALIDATION_ERROR","Enter a valid Paystack secret key.",422)
    mode="live" if secret.startswith("sk_live_") else "test" if secret else paystack_settings()["mode"]
    if not mode or not body.public_key.startswith(f"pk_{mode}_"):
        raise RoyaError("KEY_MODE_MISMATCH","Paystack public and secret keys must use the same mode.",422)
    save_integration("paystack",{
        "public_key":body.public_key,"mode":mode,
    },secret or None,g.platform_admin.user_id)
    return ok(integration_status("paystack"))


@bp.post("/api/v1/admin/integrations/smtp/test")
@require_platform_admin
def test_smtp():
    from roya.notifications.smtp import SmtpNotificationAdapter
    SmtpNotificationAdapter().test_connection()
    return ok({"connected":True,"message":"SMTP connection and login succeeded. No email was sent."})


@bp.post("/api/v1/admin/integrations/paystack/test")
@require_platform_admin
def test_paystack():
    from roya.payments.paystack import PaystackProvider
    PaystackProvider().test_connection()
    return ok({"connected":True,"message":"Paystack key accepted. No payment was initiated."})


@bp.put("/api/v1/admin/properties/<uuid:property_id>/verification")
@require_platform_admin
def verify_property(property_id):
    body=request.get_json(silent=True) or {}; status=body.get("status")
    if status not in {"verified","rejected","suspended"}:
        raise RoyaError("VALIDATION_ERROR","Invalid verification status.",422)

    with db_connection() as conn:
        with conn.transaction():
            before=conn.execute("select * from properties where id=%s for update",(str(property_id),)).fetchone()
            if not before:
                raise RoyaError("PROPERTY_NOT_FOUND","Property not found.",404)

            if status=="verified":
                readiness=conn.execute(
                    """select
                         exists(select 1 from room_types rt where rt.property_id=%s and rt.status='active') has_room,
                         exists(select 1 from rate_plans rp join room_types rt on rt.id=rp.room_type_id
                                where rt.property_id=%s and rt.status='active' and rp.status='active') has_rate,
                         exists(select 1 from inventory_days i join room_types rt on rt.id=i.room_type_id
                                where rt.property_id=%s and rt.status='active' and i.date>=current_date
                                  and i.stop_sell=false and (i.total_inventory-i.held_inventory-i.sold_inventory)>0) has_inventory""",
                    (str(property_id),str(property_id),str(property_id)),
                ).fetchone()
                missing=[]
                if not readiness["has_room"]: missing.append("room type")
                if not readiness["has_rate"]: missing.append("rate plan")
                if not readiness["has_inventory"]: missing.append("future inventory")
                if missing:
                    raise RoyaError(
                        "PROPERTY_NOT_READY",
                        "This property cannot be verified until its sellable setup is complete.",
                        409,
                        {"missing":missing},
                    )

            row=conn.execute(
                "update properties set verification_status=%s,status=case when %s='verified' then 'active' else status end,verification_notes=%s,updated_at=now() where id=%s returning *",
                (status,status,body.get("notes"),str(property_id)),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'property.verification_changed','property',%s,%s::jsonb,%s::jsonb)""",
                (g.platform_admin.user_id,before["organization_id"],str(property_id),str(property_id),
                 json.dumps(dict(before),default=str),json.dumps(dict(row),default=str)),
            )
    return ok(row)
