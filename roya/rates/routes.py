from datetime import date
from uuid import UUID

from flask import Blueprint, request
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import current_identity, login_required
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.response import ok

bp = Blueprint("rates", __name__)


class RatePlanCreate(BaseModel):
    room_type_id: UUID
    name: str = Field(min_length=2, max_length=120)
    base_price_minor: int = Field(gt=0)
    currency: str = Field(default="NGN", min_length=3, max_length=3)
    guarantee_type: str = "pay_now"
    refundable: bool = True
    meal_plan: str = "room_only"
    deposit_percent: int = Field(default=100, ge=0, le=100)
    min_stay: int = Field(default=1, ge=1, le=90)


class DailyRateItem(BaseModel):
    date: date
    price_minor: int = Field(gt=0)


class DailyRateUpdate(BaseModel):
    rate_plan_id: UUID
    days: list[DailyRateItem] = Field(min_length=1, max_length=366)


@bp.post("/api/v1/rate-plans")
@login_required
def create_rate_plan():
    try:
        body = RatePlanCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR", "Invalid rate plan details.", 422, {"errors": exc.errors()}) from exc
    if body.guarantee_type not in {"pay_now","deposit","pay_at_property","hotel_approval"}:
        raise RoyaError("VALIDATION_ERROR", "Unsupported guarantee type.", 422)
    user = current_identity(required=True)
    with db_connection() as conn:
        access = conn.execute(
            """select om.role from room_types rt join properties p on p.id=rt.property_id
               join organization_members om on om.organization_id=p.organization_id
               where rt.id=%s and om.user_id=%s and om.status='active'""",
            (str(body.room_type_id), user.user_id),
        ).fetchone()
        if not access or access["role"] not in {"owner","manager","reservations"}:
            raise RoyaError("FORBIDDEN", "You cannot manage rates for this room type.", 403)
        row = conn.execute(
            """insert into rate_plans(room_type_id,name,base_price_minor,currency,guarantee_type,refundable,meal_plan,deposit_percent,min_stay,status)
               values(%s,%s,%s,upper(%s),%s,%s,%s,%s,%s,'active') returning *""",
            (str(body.room_type_id),body.name,body.base_price_minor,body.currency,body.guarantee_type,body.refundable,body.meal_plan,body.deposit_percent,body.min_stay),
        ).fetchone()
        conn.commit()
    return ok(row,201)


@bp.put("/api/v1/daily-rates")
@login_required
def update_daily_rates():
    try:
        body = DailyRateUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR", "Invalid daily rate details.", 422, {"errors": exc.errors()}) from exc

    user = current_identity(required=True)
    with db_connection() as conn:
        access = conn.execute(
            """select om.role
               from rate_plans rp
               join room_types rt on rt.id=rp.room_type_id
               join properties p on p.id=rt.property_id
               join organization_members om on om.organization_id=p.organization_id
               where rp.id=%s and om.user_id=%s and om.status='active'""",
            (str(body.rate_plan_id), user.user_id),
        ).fetchone()
        if not access or access["role"] not in {"owner","manager","reservations"}:
            raise RoyaError("FORBIDDEN", "You cannot manage this rate plan.", 403)

        with conn.transaction():
            for item in body.days:
                conn.execute(
                    """insert into daily_rates(rate_plan_id,date,price_minor)
                       values(%s,%s,%s)
                       on conflict(rate_plan_id,date)
                       do update set price_minor=excluded.price_minor,updated_at=now()""",
                    (str(body.rate_plan_id), item.date, item.price_minor),
                )

    return ok({"updated": len(body.days)})
