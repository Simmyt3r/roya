import csv
from datetime import date
from io import StringIO
from uuid import UUID

from flask import Blueprint,Response,render_template,request

from roya.auth.service import current_identity,login_required
from roya.common.errors import RoyaError
from .service import partner_performance_dashboard


bp=Blueprint("analytics",__name__)


def _filters():
    today=date.today()
    default_start=today.replace(day=1)
    start_raw=(request.args.get("start") or default_start.isoformat()).strip()
    end_raw=(request.args.get("end") or today.isoformat()).strip()
    try:
        start=date.fromisoformat(start_raw)
        end=date.fromisoformat(end_raw)
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Analytics dates must use YYYY-MM-DD.",422) from exc
    if end<start:
        raise RoyaError("VALIDATION_ERROR","Analytics end date must be on or after the start date.",422)
    if (end-start).days>366:
        raise RoyaError("VALIDATION_ERROR","Analytics reports are limited to 367 days at a time.",422)

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


@bp.get("/partner/analytics")
@login_required
def partner_analytics():
    identity=current_identity(required=True)
    start,end,organization_id,property_id=_filters()
    analytics=partner_performance_dashboard(
        identity.user_id,start,end,
        organization_id=organization_id,property_id=property_id,
    )
    return render_template(
        "partner/analytics.html",
        analytics=analytics,start=start,end=end,
    )


@bp.get("/partner/analytics/export.csv")
@login_required
def partner_analytics_export():
    identity=current_identity(required=True)
    start,end,organization_id,property_id=_filters()
    analytics=partner_performance_dashboard(
        identity.user_id,start,end,
        organization_id=organization_id,property_id=property_id,
    )
    output=StringIO()
    writer=csv.writer(output)
    writer.writerow([
        "Date","Capacity room nights","Sold room nights","Held room nights",
        "Remaining room nights","Booked room nights","Occupancy %","Room revenue NGN",
    ])
    for row in analytics["daily"]:
        writer.writerow([
            row["date"],int(row["capacity_room_nights"] or 0),int(row["sold_room_nights"] or 0),
            int(row["held_room_nights"] or 0),int(row["remaining_room_nights"] or 0),
            int(row["booked_room_nights"] or 0),row["occupancy_percent"],
            f"{int(row['room_revenue_minor'] or 0)/100:.2f}",
        ])
    filename=f"iroya-hotel-performance-{start.isoformat()}-to-{end.isoformat()}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":f'attachment; filename="{filename}"'},
    )
