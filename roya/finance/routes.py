import csv
from datetime import date
from io import StringIO
from uuid import UUID

from flask import Blueprint,Response,g,render_template,request

from roya.admin.service import require_platform_roles
from roya.auth.service import current_identity,login_required
from roya.common.errors import RoyaError
from .service import partner_finance_dashboard,platform_finance_dashboard
from roya.payments.service import PaymentService


bp=Blueprint("finance",__name__)


def _filters():
    today=date.today()
    default_start=today.replace(day=1)
    start_raw=(request.args.get("start") or default_start.isoformat()).strip()
    end_raw=(request.args.get("end") or today.isoformat()).strip()
    try:
        start=date.fromisoformat(start_raw)
        end=date.fromisoformat(end_raw)
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Finance dates must use YYYY-MM-DD.",422) from exc
    if end<start:
        raise RoyaError("VALIDATION_ERROR","Finance end date must be on or after the start date.",422)
    if (end-start).days>366:
        raise RoyaError("VALIDATION_ERROR","Finance reports are limited to 367 days at a time.",422)

    organization_id=(request.args.get("organization_id") or "").strip()
    property_id=(request.args.get("property_id") or "").strip()
    try:
        if organization_id:
            organization_id=str(UUID(organization_id))
        if property_id:
            property_id=str(UUID(property_id))
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid organization or property filter.",422) from exc
    return start,end,organization_id or None,property_id or None


def _csv_cell(value):
    if value is None:
        return ""
    text=str(value)
    if text.startswith(("=","+","-","@","\t","\r")):
        return "'"+text
    return text


def _csv_response(snapshot,start,end,prefix):
    output=StringIO()
    writer=csv.writer(output)
    writer.writerow([
        "Reservation","Created","Hotel","Organization","Guest","Email",
        "Check in","Check out","Status","Guarantee","Payment status","Currency",
        "Gross","Paid","Refunded","Net collected","Outstanding",
        "Latest provider","Provider reference","Transaction status",
    ])
    for row in snapshot["ledger"]:
        writer.writerow([
            _csv_cell(row["reference"]),_csv_cell(row["created_at"]),_csv_cell(row["property_name"]),_csv_cell(row["organization_name"]),
            _csv_cell(row["guest_name"]),_csv_cell(row["guest_email"]),_csv_cell(row["check_in"]),_csv_cell(row["check_out"]),
            _csv_cell(row["status"]),_csv_cell(row["guarantee_type"]),_csv_cell(row["payment_status"]),_csv_cell(row["currency"]),
            f"{int(row['total_price_minor'] or 0)/100:.2f}",
            f"{int(row['amount_paid_minor'] or 0)/100:.2f}",
            f"{int(row['refunded_minor'] or 0)/100:.2f}",
            f"{int(row['net_collected_minor'] or 0)/100:.2f}",
            f"{int(row['outstanding_minor'] or 0)/100:.2f}",
            _csv_cell(row["latest_provider"]),_csv_cell(row["latest_provider_reference"]),_csv_cell(row["latest_transaction_status"]),
        ])
    filename=f"{prefix}-{start.isoformat()}-to-{end.isoformat()}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":f'attachment; filename="{filename}"'},
    )


@bp.get("/partner/finance")
@login_required
def partner_finance():
    identity=current_identity(required=True)
    start,end,organization_id,property_id=_filters()
    snapshot=partner_finance_dashboard(
        identity.user_id,start,end,
        organization_id=organization_id,property_id=property_id,
    )
    snapshot["refund_queue"]=[
        dict(row) for row in PaymentService().list_for_partner(
            identity.user_id,
            organization_id=organization_id,
            property_id=property_id,
            limit=100,
        )
    ]
    focus=(request.args.get("focus") or "").strip().lower()
    return render_template(
        "partner/finance.html",
        finance=snapshot,start=start,end=end,
        focus="refunds" if focus=="refunds" else "",
    )


@bp.get("/partner/finance/export.csv")
@login_required
def partner_finance_export():
    identity=current_identity(required=True)
    start,end,organization_id,property_id=_filters()
    snapshot=partner_finance_dashboard(
        identity.user_id,start,end,
        organization_id=organization_id,property_id=property_id,limit=5000,
    )
    return _csv_response(snapshot,start,end,"iroya-hotel-finance")


@bp.get("/admin/finance")
@require_platform_roles("admin","finance")
def platform_finance():
    start,end,organization_id,property_id=_filters()
    snapshot=platform_finance_dashboard(
        start,end,organization_id=organization_id,property_id=property_id,
    )
    return render_template(
        "admin/finance.html",
        finance=snapshot,start=start,end=end,
        platform_role=g.platform_role,
    )


@bp.get("/admin/finance/export.csv")
@require_platform_roles("admin","finance")
def platform_finance_export():
    start,end,organization_id,property_id=_filters()
    snapshot=platform_finance_dashboard(
        start,end,organization_id=organization_id,property_id=property_id,limit=5000,
    )
    return _csv_response(snapshot,start,end,"iroya-platform-finance")
