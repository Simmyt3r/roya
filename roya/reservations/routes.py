from datetime import date
from flask import Blueprint, render_template, request
from pydantic import ValidationError

from roya.auth.service import current_identity, login_required
from roya.common.errors import RoyaError
from roya.common.response import ok
from .schemas import PartnerReservationDecision, PartnerReservationStatusChange, ReservationCreate
from .service import ReservationService
from roya.reviews.service import ReviewService

bp=Blueprint("reservations",__name__)
service=ReservationService()
review_service=ReviewService()


@bp.post("/api/v1/reservations")
@login_required
def create_reservation_route():
    try:
        payload=ReservationCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid reservation details.",422,{"errors":exc.errors()}) from exc
    identity=current_identity(required=True)
    source_channel=service.source_channel_for_request(str(payload.property_id),request.host)
    return ok(
        service.create(
            identity.user_id,
            payload,
            request.headers.get("Idempotency-Key",""),
            source_channel=source_channel,
        ),
        201,
    )


@bp.get("/api/v1/reservations/<uuid:reservation_id>")
@login_required
def get_reservation(reservation_id):
    identity=current_identity(required=True)
    return ok(service.get_for_user(str(reservation_id),identity.user_id))


@bp.post("/api/v1/reservations/<uuid:reservation_id>/cancel")
@login_required
def cancel_reservation_route(reservation_id):
    identity=current_identity(required=True)
    body=request.get_json(silent=True) or {}
    return ok(service.cancel(str(reservation_id),identity.user_id,body.get("reason")))


@bp.get("/partner/guests")
@login_required
def partner_guests():
    identity=current_identity(required=True)
    workspace=service.guest_workspace_for_partner(
        identity.user_id,
        property_id=request.args.get("property_id"),
        query=request.args.get("q"),
        limit=50,
    )
    return render_template("partner/guests.html",workspace=workspace)


@bp.get("/partner/reservations")
@login_required
def partner_reservation_workspace():
    identity=current_identity(required=True)
    workspace=service.workspace_for_partner(
        identity.user_id,
        tab=request.args.get("tab","today"),
        property_id=request.args.get("property_id"),
        query=request.args.get("q"),
        limit=100,
    )
    return render_template("partner/reservations.html",workspace=workspace)


@bp.get("/partner/reservations/<uuid:reservation_id>")
@login_required
def partner_reservation_page(reservation_id):
    identity=current_identity(required=True)
    workspace=service.get_for_partner(str(reservation_id),identity.user_id)
    return render_template("partner/reservation.html",workspace=workspace)


@bp.get("/api/v1/partner/reservations")
@login_required
def partner_reservations():
    identity=current_identity(required=True)
    property_id=request.args.get("property_id") or None
    return ok(service.list_for_partner(identity.user_id,property_id=property_id))


@bp.get("/api/v1/partner/reservations/search")
@login_required
def partner_reservation_search():
    identity=current_identity(required=True)
    query=(request.args.get("q") or "").strip()
    property_id=(request.args.get("property_id") or "").strip() or None
    return ok(service.search_for_partner(
        identity.user_id,
        query,
        property_id=property_id,
        limit=request.args.get("limit",20),
    ))


@bp.post("/api/v1/partner/reservations/<uuid:reservation_id>/decision")
@login_required
def partner_reservation_decision(reservation_id):
    try:
        body=PartnerReservationDecision.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid reservation decision.",422,{"errors":exc.errors()}) from exc
    identity=current_identity(required=True)
    return ok(service.partner_decide(str(reservation_id),identity.user_id,body.decision,body.reason))


@bp.post("/api/v1/partner/reservations/<uuid:reservation_id>/status")
@login_required
def partner_reservation_status(reservation_id):
    try:
        body=PartnerReservationStatusChange.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid reservation status.",422,{"errors":exc.errors()}) from exc
    identity=current_identity(required=True)
    return ok(service.partner_transition(str(reservation_id),identity.user_id,body.status))


@bp.get("/book")
@login_required
def booking_page():
    from roya.common.db import db_connection
    identity=current_identity(required=True)
    room_type_id=request.args.get("room_type_id",""); rate_plan_id=request.args.get("rate_plan_id","")
    try:
        check_in=date.fromisoformat(request.args.get("check_in","")); check_out=date.fromisoformat(request.args.get("check_out",""))
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Valid stay dates are required.",422) from exc
    if check_in<date.today():
        raise RoyaError("VALIDATION_ERROR","Check-in cannot be in the past.",422)
    if check_out<=check_in:
        raise RoyaError("VALIDATION_ERROR","Check-out must be after check-in.",422)
    with db_connection() as conn:
        row=conn.execute(
            """select rt.*,p.name property_name,p.id property_id,p.slug property_slug,rp.id rate_id,rp.name rate_name,
                      rp.base_price_minor,rp.currency,rp.guarantee_type,rp.refundable,rp.cancellation_policy,
                      rp.deposit_percent,rp.min_stay rate_min_stay
               from room_types rt
               join properties p on p.id=rt.property_id
               join rate_plans rp on rp.room_type_id=rt.id
               where rt.id=%s and rp.id=%s
                 and rt.status='active' and rp.status='active'
                 and p.status='active' and p.verification_status='verified'""",
            (room_type_id,rate_plan_id),
        ).fetchone()
        profile=conn.execute("select name,phone from profiles where id=%s",(identity.user_id,)).fetchone()
        availability=None
        if row:
            nights=(check_out-check_in).days
            availability=conn.execute(
                """select
                     count(*) total_nights,
                     count(*) filter(
                       where i.stop_sell=false
                         and i.min_stay<=%s
                         and (i.total_inventory-i.held_inventory-i.sold_inventory)>0
                         and not (i.date=%s and i.closed_to_arrival)
                         and not (i.date=(%s::date-1) and i.closed_to_departure)
                     ) sellable_nights,
                     coalesce(sum(coalesce(dr.price_minor,i.price_override_minor,%s)),0)::bigint total_price_minor
                   from inventory_days i
                   left join daily_rates dr
                     on dr.rate_plan_id=%s
                    and dr.date=i.date
                   where i.room_type_id=%s
                     and i.date>=%s
                     and i.date<%s""",
                (
                    nights,check_in,check_out,int(row["base_price_minor"]),
                    rate_plan_id,room_type_id,check_in,check_out,
                ),
            ).fetchone()
    if not row:
        raise RoyaError("RATE_NOT_FOUND","Selected room/rate is unavailable.",404)

    service.source_channel_for_request(str(row["property_id"]),request.host)

    nights=(check_out-check_in).days
    if nights<int(row["rate_min_stay"] or 1) or not availability or int(availability["total_nights"] or 0)!=nights or int(availability["sellable_nights"] or 0)!=nights:
        raise RoyaError(
            "BOOKING_CONFLICT",
            "This stay is no longer available for the selected dates.",
            409,
        )

    total_price_minor=int(availability["total_price_minor"] or 0)
    guarantee_type=row["guarantee_type"]
    if guarantee_type=="pay_now":
        amount_due_minor=total_price_minor
    elif guarantee_type=="deposit":
        deposit_percent=int(row["deposit_percent"] or 0)
        amount_due_minor=(total_price_minor*deposit_percent+99)//100
    else:
        amount_due_minor=0

    prop={"id":row["property_id"],"name":row["property_name"],"slug":row["property_slug"]}
    room={
        "id":row["id"],
        "name":row["name"],
        "capacity_adults":row["capacity_adults"],
        "capacity_children":row["capacity_children"],
    }
    rate={
        "id":row["rate_id"],
        "name":row["rate_name"],
        "base_price_minor":row["base_price_minor"],
        "currency":row["currency"],
        "guarantee_type":guarantee_type,
        "refundable":row["refundable"],
        "cancellation_policy":row["cancellation_policy"] or {},
        "deposit_percent":int(row["deposit_percent"] or 0),
        "total_price_minor":total_price_minor,
        "amount_due_minor":amount_due_minor,
    }
    guest={"name":(profile["name"] if profile else "") or "","email":identity.email or "","phone":(profile["phone"] if profile else "") or ""}
    return render_template(
        "guest/booking.html",
        property=prop,room=room,rate=rate,
        check_in=check_in,check_out=check_out,nights=nights,guest=guest,
    )


@bp.get("/reservation/<uuid:reservation_id>")
@login_required
def reservation_page(reservation_id):
    identity=current_identity(required=True)
    reservation=service.get_for_user(str(reservation_id),identity.user_id)
    review=review_service.for_reservation(str(reservation_id),identity.user_id)
    return render_template("guest/reservation.html",reservation=reservation,review=review)
