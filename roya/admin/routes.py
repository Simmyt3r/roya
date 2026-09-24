import json
from flask import Blueprint,g,render_template,request
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.response import ok
from .service import require_platform_admin

bp=Blueprint("admin",__name__)


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
    return render_template("admin/dashboard.html",metrics=metrics,pending=pending)


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
