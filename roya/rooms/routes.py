import json
import uuid as uuidlib
from typing import Literal
from uuid import UUID
from flask import Blueprint, current_app, request
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import current_identity, login_required
from roya.common.db import db_connection, supabase_admin_client
from roya.common.errors import RoyaError
from roya.common.media import read_image_upload, storage_object_path
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


class RoomImageUpdate(BaseModel):
    alt_text: str|None = Field(default=None,max_length=300)
    sort_order: int = Field(default=0,ge=0,le=10000)


class RoomTypeUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=3000)
    capacity_adults: int = Field(default=2, ge=1, le=20)
    capacity_children: int = Field(default=0, ge=0, le=20)
    base_occupancy: int = Field(default=1, ge=1, le=20)
    total_inventory: int = Field(ge=1, le=1000)
    bed_configuration: str = Field(default="", max_length=200)
    status: Literal["active","inactive"] = "active"


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


@bp.put("/api/v1/room-types/<uuid:room_type_id>")
@login_required
def update_room_type(room_type_id):
    try:
        body=RoomTypeUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid room type details.",422,{"errors":exc.errors()}) from exc
    if body.base_occupancy>body.capacity_adults:
        raise RoyaError("VALIDATION_ERROR","Base occupancy cannot exceed adult capacity.",422)

    user=current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            access=conn.execute(
                """select rt.property_id,om.role
                   from room_types rt join properties p on p.id=rt.property_id
                   join organization_members om on om.organization_id=p.organization_id
                   where rt.id=%s and om.user_id=%s and om.status='active'
                   for update of rt""",
                (str(room_type_id),user.user_id),
            ).fetchone()
            if not access or access["role"] not in {"owner","manager","reservations"}:
                raise RoyaError("FORBIDDEN","You cannot manage this room type.",403)

            committed=conn.execute(
                """select coalesce(max(held_inventory+sold_inventory),0) committed
                   from inventory_days where room_type_id=%s and date>=current_date""",
                (str(room_type_id),),
            ).fetchone()["committed"]
            if body.total_inventory<int(committed or 0):
                raise RoyaError(
                    "INVENTORY_BELOW_COMMITTED",
                    "Room inventory cannot be reduced below rooms already held or sold.",
                    409,
                    {"minimum_total_inventory":int(committed or 0)},
                )

            row=conn.execute(
                """update room_types set name=%s,description=%s,capacity_adults=%s,capacity_children=%s,
                          base_occupancy=%s,total_inventory=%s,bed_configuration=%s,status=%s,updated_at=now()
                   where id=%s returning *""",
                (body.name,body.description,body.capacity_adults,body.capacity_children,
                 body.base_occupancy,body.total_inventory,body.bed_configuration,body.status,str(room_type_id)),
            ).fetchone()
    return ok(row)



def _room_media_access(conn,room_type_id,user_id):
    return conn.execute(
        """select rt.id,rt.property_id,p.organization_id,om.role
           from room_types rt
           join properties p on p.id=rt.property_id
           join organization_members om on om.organization_id=p.organization_id
           where rt.id=%s and om.user_id=%s and om.status='active'""",
        (str(room_type_id),user_id),
    ).fetchone()


@bp.post("/api/v1/room-types/<uuid:room_type_id>/images")
@login_required
def upload_room_image(room_type_id):
    user=current_identity(required=True)
    with db_connection() as conn:
        access=_room_media_access(conn,room_type_id,user.user_id)
    if not access or access["role"] not in {"owner","manager"}:
        raise RoyaError("FORBIDDEN","Only hotel owners and managers can manage room photos.",403)

    file=request.files.get("file")
    try:
        raw,extension=read_image_upload(file)
    except ValueError as exc:
        messages={
            "IMAGE_REQUIRED":"An image file is required.",
            "IMAGE_TYPE":"Only JPEG, PNG and WebP images are accepted.",
            "IMAGE_TOO_LARGE":"Image must be 4 MB or smaller.",
        }
        raise RoyaError("VALIDATION_ERROR",messages.get(str(exc),"Invalid image."),422) from exc

    alt_text=(request.form.get("alt_text") or "").strip() or None
    if alt_text and len(alt_text)>300:
        raise RoyaError("VALIDATION_ERROR","Alt text must be 300 characters or fewer.",422)

    path=f"{room_type_id}/{uuidlib.uuid4().hex}{extension}"
    storage=supabase_admin_client().storage.from_("room-images")
    try:
        storage.upload(path,raw,{"content-type":file.mimetype,"upsert":"false"})
    except Exception as exc:
        raise RoyaError("STORAGE_UPLOAD_FAILED","Room image upload failed.",502) from exc

    try:
        public_url=storage.get_public_url(path)
        with db_connection() as conn:
            row=conn.execute(
                """insert into room_images(room_type_id,path,alt_text,sort_order)
                   values(%s,%s,%s,coalesce((select max(sort_order)+1 from room_images where room_type_id=%s),0))
                   returning *""",
                (str(room_type_id),public_url,alt_text,str(room_type_id)),
            ).fetchone()
            conn.commit()
    except Exception:
        try:
            storage.remove([path])
        except Exception:
            current_app.logger.exception("Could not clean up failed room image upload")
        raise
    return ok(row,201)


@bp.put("/api/v1/room-types/<uuid:room_type_id>/images/<uuid:image_id>")
@login_required
def update_room_image(room_type_id,image_id):
    try:
        body=RoomImageUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid room image details.",422,{"errors":exc.errors()}) from exc

    user=current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            access=_room_media_access(conn,room_type_id,user.user_id)
            if not access or access["role"] not in {"owner","manager"}:
                raise RoyaError("FORBIDDEN","Only hotel owners and managers can manage room photos.",403)
            image=conn.execute(
                """select * from room_images
                   where id=%s and room_type_id=%s
                   for update""",
                (str(image_id),str(room_type_id)),
            ).fetchone()
            if not image:
                raise RoyaError("IMAGE_NOT_FOUND","Room image not found.",404)
            row=conn.execute(
                """update room_images set alt_text=%s,sort_order=%s
                   where id=%s returning *""",
                ((body.alt_text or "").strip() or None,body.sort_order,str(image_id)),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'room.image_updated','room_image',%s,%s::jsonb,%s::jsonb)""",
                (
                    user.user_id,access["organization_id"],access["property_id"],str(image_id),
                    json.dumps({"alt_text":image["alt_text"],"sort_order":image["sort_order"]}),
                    json.dumps({"alt_text":row["alt_text"],"sort_order":row["sort_order"]}),
                ),
            )
    return ok(row)


@bp.delete("/api/v1/room-types/<uuid:room_type_id>/images/<uuid:image_id>")
@login_required
def delete_room_image(room_type_id,image_id):
    user=current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            access=_room_media_access(conn,room_type_id,user.user_id)
            if not access or access["role"] not in {"owner","manager"}:
                raise RoyaError("FORBIDDEN","Only hotel owners and managers can manage room photos.",403)
            image=conn.execute(
                """select * from room_images
                   where id=%s and room_type_id=%s
                   for update""",
                (str(image_id),str(room_type_id)),
            ).fetchone()
            if not image:
                raise RoyaError("IMAGE_NOT_FOUND","Room image not found.",404)
            conn.execute("delete from room_images where id=%s",(str(image_id),))
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'room.image_deleted','room_image',%s,%s::jsonb,'{}'::jsonb)""",
                (
                    user.user_id,access["organization_id"],access["property_id"],str(image_id),
                    json.dumps({"path":image["path"],"alt_text":image["alt_text"],"sort_order":image["sort_order"]}),
                ),
            )

    storage_cleanup=True
    object_path=storage_object_path(image["path"],"room-images")
    if object_path:
        try:
            supabase_admin_client().storage.from_("room-images").remove([object_path])
        except Exception:
            storage_cleanup=False

    return ok({"deleted":True,"image_id":str(image_id),"storage_cleanup":storage_cleanup})
