from uuid import UUID

from flask import Blueprint,render_template,request

from roya.auth.service import current_identity,login_required
from roya.common.errors import RoyaError
from roya.common.response import ok
from .service import distribution_dashboard,set_builtin_connection_status,sync_builtin_channel


bp=Blueprint("distribution",__name__)


def _filters():
    organization_id=(request.args.get("organization_id") or "").strip()
    property_id=(request.args.get("property_id") or "").strip()
    try:
        if organization_id:
            organization_id=str(UUID(organization_id))
        if property_id:
            property_id=str(UUID(property_id))
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid organization or property filter.",422) from exc
    return organization_id or None,property_id or None


@bp.get("/partner/distribution")
@login_required
def partner_distribution():
    identity=current_identity(required=True)
    organization_id,property_id=_filters()
    distribution=distribution_dashboard(
        identity.user_id,
        organization_id=organization_id,
        property_id=property_id,
    )
    return render_template(
        "partner/distribution.html",
        distribution=distribution,
    )


@bp.post("/api/v1/distribution/properties/<uuid:property_id>/<channel>/sync")
@login_required
def partner_distribution_sync(property_id,channel):
    identity=current_identity(required=True)
    return ok(sync_builtin_channel(
        identity.user_id,
        str(property_id),
        channel.strip().lower(),
    ))


@bp.post("/api/v1/distribution/connections/<uuid:connection_id>/status")
@login_required
def partner_distribution_status(connection_id):
    identity=current_identity(required=True)
    body=request.get_json(silent=True) or {}
    return ok(set_builtin_connection_status(
        identity.user_id,
        str(connection_id),
        str(body.get("status") or "").strip().lower(),
    ))
