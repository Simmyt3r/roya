from uuid import UUID
from flask import Blueprint, request
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import current_identity, login_required
from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.response import ok

bp = Blueprint("rooms", __name__)


class RoomTypeCreate(BaseModel):
    property_id: UUID
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=3000)
    capacity_adults: int = Field(default=2, ge=1, le=20)
    capacity_children: int = Field(default=0, ge=0, le=20)
    base_occupancy: int = Field(default=1, ge=1, le=20)
    total_inventory: int = Field(ge=1, le=1000)
    bed_configuration: str = Field(default="", max_length=200)


@bp.post("/api/v1/room-types")
@login_required
def create_room_type():
    try:
        body = RoomTypeCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR", "Invalid room type details.", 422, {"errors": exc.errors()}) from exc
    user = current_identity(required=True)
    with db_connection() as conn:
        access = conn.execute(
            """select om.role from properties p join organization_members om on om.organization_id=p.organization_id
               where p.id=%s and om.user_id=%s and om.status='active'""",
            (str(body.property_id), user.user_id),
        ).fetchone()
        if not access or access["role"] not in {"owner","manager","reservations"}:
            raise RoyaError("FORBIDDEN", "You cannot manage rooms for this property.", 403)
        row = conn.execute(
            """insert into room_types(property_id,name,description,capacity_adults,capacity_children,base_occupancy,total_inventory,bed_configuration,status)
               values(%s,%s,%s,%s,%s,%s,%s,%s,'active') returning *""",
            (str(body.property_id),body.name,body.description,body.capacity_adults,body.capacity_children,body.base_occupancy,body.total_inventory,body.bed_configuration),
        ).fetchone()
        conn.commit()
    return ok(row, 201)
