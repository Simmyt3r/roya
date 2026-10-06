import json
import re
from typing import Literal
from uuid import UUID
from flask import Blueprint,current_app,g,render_template,request
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator, model_validator
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.integrations import (
    integration_status, paystack_settings, save_integration, smtp_settings,
)
from roya.common.response import ok
from roya.common.readiness import booking_readiness_snapshot
from .service import require_platform_admin, require_platform_roles
from .operations_service import (
    acknowledge_operational_alert, expire_overdue_holds, list_operational_alerts,
    operations_snapshot, reservation_case, search_reservation_cases, sync_operational_alerts,
)
from .audit_service import audit_counts, audit_filter_options, list_audit_events
from .review_service import list_reviews, review_counts, set_review_visibility
from .user_service import (
    change_platform_role, change_user_status, search_user_accounts, user_account_counts,
)
from .email_service import (
    create_template, delete_template, deliver_email_queue, list_subscribers, list_templates,
    queue_campaign, recent_campaigns, record_marketing_consent,
    subscriber_counts, suppress_marketing_subscriber, update_template,
)

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


class EmailTemplateConfiguration(BaseModel):
    name: str = Field(min_length=2,max_length=120)
    subject: str = Field(min_length=2,max_length=180)
    body: str = Field(min_length=2,max_length=20000)
    category: Literal["marketing","general","hotel_outreach"] = "marketing"


class EmailCampaignRequest(BaseModel):
    audience: Literal["all","external","registered_all","registered_guests","registered_hotels","custom"]
    subject: str = Field(min_length=2,max_length=180)
    body: str = Field(min_length=2,max_length=20000)
    template_id: UUID | None = None
    custom_recipients: list[EmailStr] = Field(default_factory=list,max_length=500)

    @model_validator(mode="after")
    def validate_custom_audience(self):
        if self.audience=="custom" and not self.custom_recipients:
            raise ValueError("Add at least one external email recipient.")
        if self.audience!="custom" and self.custom_recipients:
            raise ValueError("Custom recipients are only valid for the custom audience.")
        return self


class ReviewVisibilityRequest(BaseModel):
    is_visible: bool


class UserStatusRequest(BaseModel):
    status: Literal["active","suspended"]


class PlatformRoleRequest(BaseModel):
    platform_role: Literal["user","support","finance"]


class MarketingConsentRequest(BaseModel):
    email: EmailStr
    consent_confirmed: bool

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.consent_confirmed:
            raise ValueError("Confirm that the recipient explicitly opted in to marketing email.")
        return self


def _configuration_payload(schema):
    if not request.is_json:
        raise RoyaError("UNSUPPORTED_MEDIA_TYPE","JSON request body required.",415)
    try:
        return schema.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        # Pydantic errors may include the submitted secret; never echo them.
        raise RoyaError("VALIDATION_ERROR","Check the submitted settings and try again.",422) from exc


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
    readiness=booking_readiness_snapshot()
    try:
        operations=operations_snapshot()
    except Exception as exc:
        current_app.logger.warning("Admin operations snapshot unavailable: %s",exc)
        operations={
            "counts":{
                "stuck_payments":0,"stuck_refunds":0,"overdue_holds":0,"expiring_holds":0,
                "failed_email_24h":0,"overdue_email_queue":0,"inventory_anomalies":0,
                "active_hotels_without_30d_inventory":0,
            },
            "issues":[],"critical":0,"warning":0,"healthy":True,
        }
    try:
        operational_alerts=list_operational_alerts()
    except Exception as exc:
        current_app.logger.warning("Admin operational alert ledger unavailable: %s",exc)
        operational_alerts=[]
    try:
        email_templates=list_templates()
        email_campaigns=recent_campaigns()
        marketing_subscribers=subscriber_counts()
        marketing_subscriber_rows=list_subscribers()
    except Exception as exc:
        current_app.logger.warning("Admin email tools unavailable until migration is applied: %s",exc)
        email_templates=[]
        email_campaigns=[]
        marketing_subscribers={"active_total":0,"active_registered":0,"active_external":0,"unsubscribed_total":0}
        marketing_subscriber_rows=[]
    return render_template(
        "admin/dashboard.html",metrics=metrics,pending=pending,
        smtp=integration_status("smtp"),paystack=integration_status("paystack"),
        paystack_webhook_url=(current_app.config["APP_URL"].rstrip("/")+"/api/webhooks/paystack"),
        email_templates=email_templates,email_campaigns=email_campaigns,
        marketing_subscribers=marketing_subscribers,
        marketing_subscriber_rows=marketing_subscriber_rows,
        operations=operations,operational_alerts=operational_alerts,
        readiness=readiness,
    )


@bp.get("/admin/audit")
@require_platform_admin
def admin_audit():
    query=(request.args.get("q") or "").strip()
    if len(query)>160:
        raise RoyaError("VALIDATION_ERROR","Audit search is too long.",422)
    entity_type=(request.args.get("entity_type") or "").strip()
    action=(request.args.get("action") or "").strip()
    if len(entity_type)>80 or len(action)>120:
        raise RoyaError("VALIDATION_ERROR","Audit filter is too long.",422)
    try:
        since_days=int(request.args.get("since_days","7"))
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Audit date range is invalid.",422) from exc
    if since_days not in {1,7,30,90,365}:
        raise RoyaError("VALIDATION_ERROR","Audit date range is invalid.",422)

    return render_template(
        "admin/audit.html",
        query=query,
        entity_type_filter=entity_type,
        action_filter=action,
        since_days=since_days,
        events=list_audit_events(
            query=query,entity_type=entity_type,action=action,since_days=since_days,
        ),
        filters=audit_filter_options(),
        counts=audit_counts(),
    )


@bp.get("/admin/reviews")
@require_platform_admin
def admin_reviews():
    query=(request.args.get("q") or "").strip()
    if len(query)>160:
        raise RoyaError("VALIDATION_ERROR","Review search is too long.",422)
    visibility=(request.args.get("visibility") or "").strip()
    if visibility not in {"","visible","hidden"}:
        raise RoyaError("VALIDATION_ERROR","Invalid review visibility filter.",422)
    return render_template(
        "admin/reviews.html",
        query=query,
        visibility_filter=visibility,
        reviews=list_reviews(query=query,visibility=visibility),
        counts=review_counts(),
    )


@bp.put("/api/v1/admin/reviews/<uuid:review_id>/visibility")
@require_platform_admin
def admin_review_visibility(review_id):
    body=_configuration_payload(ReviewVisibilityRequest)
    return ok(set_review_visibility(
        review_id=str(review_id),
        is_visible=body.is_visible,
        actor_user_id=g.platform_admin.user_id,
    ))


@bp.get("/admin/users")
@require_platform_admin
def admin_users():
    query=(request.args.get("q") or "").strip()
    if len(query)>120:
        raise RoyaError("VALIDATION_ERROR","User search is too long.",422)
    status=(request.args.get("status") or "").strip()
    if status not in {"","active","suspended","pending_verification"}:
        raise RoyaError("VALIDATION_ERROR","Invalid account status filter.",422)
    return render_template(
        "admin/users.html",
        query=query,
        status_filter=status,
        users=search_user_accounts(query=query,status=status),
        counts=user_account_counts(),
    )


@bp.put("/api/v1/admin/users/<uuid:user_id>/status")
@require_platform_admin
def admin_change_user_status(user_id):
    body=_configuration_payload(UserStatusRequest)
    return ok(change_user_status(
        user_id=str(user_id),
        status=body.status,
        actor_user_id=g.platform_admin.user_id,
    ))


@bp.put("/api/v1/admin/users/<uuid:user_id>/platform-role")
@require_platform_admin
def admin_change_platform_role(user_id):
    body=_configuration_payload(PlatformRoleRequest)
    return ok(change_platform_role(
        user_id=str(user_id),
        platform_role=body.platform_role,
        actor_user_id=g.platform_admin.user_id,
    ))


@bp.get("/admin/reservations")
@require_platform_admin
def admin_reservation_search():
    query=(request.args.get("q") or "").strip()
    results=search_reservation_cases(query) if query else []
    return render_template(
        "admin/reservation_search.html",query=query,results=results,support_mode=False,
    )


@bp.get("/admin/reservations/<uuid:reservation_id>")
@require_platform_admin
def admin_reservation_case(reservation_id):
    case=reservation_case(str(reservation_id))
    if not case:
        raise RoyaError("NOT_FOUND","Reservation not found.",404)
    return render_template("admin/reservation_case.html",case=case,support_mode=False)


@bp.get("/support")
@require_platform_roles("admin","support")
def support_dashboard():
    snapshot=operations_snapshot(limit=30)
    return render_template(
        "support/dashboard.html",
        operations=snapshot,
        platform_role=g.platform_role,
    )


@bp.get("/support/reservations")
@require_platform_roles("admin","support")
def support_reservation_search():
    query=(request.args.get("q") or "").strip()
    if len(query)>254:
        raise RoyaError("VALIDATION_ERROR","Reservation search is too long.",422)
    results=search_reservation_cases(query) if query else []
    return render_template(
        "admin/reservation_search.html",query=query,results=results,support_mode=True,
    )


@bp.get("/support/reservations/<uuid:reservation_id>")
@require_platform_roles("admin","support")
def support_reservation_case(reservation_id):
    case=reservation_case(str(reservation_id))
    if not case:
        raise RoyaError("NOT_FOUND","Reservation not found.",404)
    return render_template("admin/reservation_case.html",case=case,support_mode=True)


@bp.get("/api/v1/admin/readiness")
@require_platform_admin
def admin_readiness():
    return ok(booking_readiness_snapshot())


@bp.get("/api/v1/admin/operations")
@require_platform_admin
def admin_operations_snapshot():
    return ok(operations_snapshot())


@bp.post("/api/v1/admin/operations/scan")
@require_platform_admin
def admin_operations_scan():
    return ok(sync_operational_alerts())


@bp.post("/api/v1/admin/operations/alerts/<uuid:alert_id>/acknowledge")
@require_platform_admin
def admin_acknowledge_operational_alert(alert_id):
    row=acknowledge_operational_alert(str(alert_id),g.platform_admin.user_id)
    if not row:
        raise RoyaError("NOT_FOUND","Active operational alert not found.",404)
    return ok(row)


@bp.post("/api/v1/admin/operations/expire-holds")
@require_platform_admin
def admin_expire_holds():
    return ok(expire_overdue_holds())


@bp.post("/api/v1/admin/operations/reconcile-money")
@require_platform_admin
def admin_reconcile_money():
    from roya.payments.service import PaymentService
    service=PaymentService()
    return ok({
        "payments":service.reconcile_pending(),
        "refunds":service.reconcile_refunds(),
    })


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


@bp.post("/api/v1/admin/email/templates")
@require_platform_admin
def create_email_template():
    body=_configuration_payload(EmailTemplateConfiguration)
    return ok(create_template(
        name=body.name.strip(),subject=body.subject.strip(),body=body.body.strip(),
        category=body.category,actor_user_id=g.platform_admin.user_id,
    ))


@bp.put("/api/v1/admin/email/templates/<uuid:template_id>")
@require_platform_admin
def update_email_template(template_id):
    body=_configuration_payload(EmailTemplateConfiguration)
    return ok(update_template(
        template_id=str(template_id),name=body.name.strip(),subject=body.subject.strip(),
        body=body.body.strip(),category=body.category,
        actor_user_id=g.platform_admin.user_id,
    ))


@bp.delete("/api/v1/admin/email/templates/<uuid:template_id>")
@require_platform_admin
def archive_email_template(template_id):
    return ok(delete_template(
        template_id=str(template_id),actor_user_id=g.platform_admin.user_id,
    ))


@bp.post("/api/v1/admin/email/subscribers")
@require_platform_admin
def add_marketing_subscriber():
    body=_configuration_payload(MarketingConsentRequest)
    return ok(record_marketing_consent(
        email=str(body.email),actor_user_id=g.platform_admin.user_id,
    ))


@bp.delete("/api/v1/admin/email/subscribers/<uuid:subscriber_id>")
@require_platform_admin
def suppress_marketing_subscription(subscriber_id):
    return ok(suppress_marketing_subscriber(
        subscriber_id=str(subscriber_id),
        actor_user_id=g.platform_admin.user_id,
    ))


@bp.post("/api/v1/admin/email/campaigns")
@require_platform_admin
def send_email_campaign():
    if not integration_status("smtp")["configured"]:
        raise RoyaError(
            "SMTP_NOT_CONFIGURED",
            "Configure and test SMTP before sending a campaign.",
            409,
        )
    body=_configuration_payload(EmailCampaignRequest)
    return ok(queue_campaign(
        audience=body.audience,
        subject=body.subject.strip(),
        body=body.body.strip(),
        template_id=str(body.template_id) if body.template_id else None,
        custom_recipients=[str(item) for item in body.custom_recipients],
        actor_user_id=g.platform_admin.user_id,
    ))


@bp.post("/api/v1/admin/email/deliver")
@require_platform_admin
def deliver_admin_email_queue():
    if not integration_status("smtp")["configured"]:
        raise RoyaError("SMTP_NOT_CONFIGURED","Configure SMTP before processing email.",409)
    return ok(deliver_email_queue(limit=50))


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
