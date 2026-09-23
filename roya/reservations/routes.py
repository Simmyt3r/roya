from datetime import date
from flask import Blueprint, render_template, request
from pydantic import ValidationError

from roya.auth.service import current_identity, login_required
from roya.common.errors import RoyaError
from roya.common.response import ok
from .schemas import ReservationCreate
from .service import ReservationService

bp=Blueprint("reservations",__name__)
service=ReservationService()


@bp.post("/api/v1/reservations")
@login_required
def create_reservation_route():
    try:
        payload=ReservationCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid reservation details.",422,{"errors":exc.errors()}) from exc
    identity=current_identity(required=True)
    return ok(service.create(identity.user_id,payload,request.headers.get("Idempotency-Key","")),201)


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


@bp.get("/book")
@login_required
def booking_page():
    from roya.common.db import db_connection
    room_type_id=request.args.get("room_type_id",""); rate_plan_id=request.args.get("rate_plan_id","")
    try:
        check_in=date.fromisoformat(request.args.get("check_in","")); check_out=date.fromisoformat(request.args.get("check_out",""))
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Valid stay dates are required.",422) from exc
    if check_out<=check_in:
        raise RoyaError("VALIDATION_ERROR","Check-out must be after check-in.",422)
    with db_connection() as conn:
        row=conn.execute(
            """select rt.*,p.name property_name,p.id property_id,rp.id rate_id,rp.name rate_name,rp.base_price_minor,rp.guarantee_type
               from room_types rt join properties p on p.id=rt.property_id join rate_plans rp on rp.room_type_id=rt.id
               where rt.id=%s and rp.id=%s and rt.status='active' and rp.status='active' and p.status='active' and p.verification_status='verified'""",
            (room_type_id,rate_plan_id),
        ).fetchone()
    if not row:
        raise RoyaError("RATE_NOT_FOUND","Selected room/rate is unavailable.",404)
    prop={"id":row["property_id"],"name":row["property_name"]}; room={"id":row["id"],"name":row["name"]}
    rate={"id":row["rate_id"],"name":row["rate_name"],"base_price_minor":row["base_price_minor"],"guarantee_type":row["guarantee_type"]}
    return render_template("guest/booking.html",property=prop,room=room,rate=rate,check_in=check_in,check_out=check_out,nights=(check_out-check_in).days)


@bp.get("/reservation/<uuid:reservation_id>")
@login_required
def reservation_page(reservation_id):
    identity=current_identity(required=True)
    return render_template("guest/reservation.html",reservation=service.get_for_user(str(reservation_id),identity.user_id))
