from datetime import date
import json
import uuid as uuidlib
from flask import Blueprint, current_app, redirect, render_template, request
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import account_type_for_user, current_identity, login_required
from roya.common.db import db_connection, supabase_admin_client
from roya.common.errors import RoyaError
from roya.common.media import read_image_upload, storage_object_path
from roya.common.response import ok
from roya.common.slug import slugify
from roya.organizations.service import require_organization_member
from .repository import get_property_by_slug, search_properties

bp = Blueprint("properties", __name__)


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR", "Dates must use YYYY-MM-DD.", 422) from exc


@bp.get("/health")
def health():
    configured=bool(current_app.config.get("DATABASE_URL"))
    reachable=False
    if configured:
        try:
            with db_connection() as conn:
                reachable=bool(conn.execute("select 1 as ok").fetchone())
        except Exception:
            reachable=False
    return ok({
        "service":"iroya",
        "status":"ok" if reachable or not configured else "degraded",
        "database_configured":configured,
        "database_reachable":reachable,
        "integrations":{
            "storage_admin_configured":bool(current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")),
            "payments_configured":bool(current_app.config.get("PAYSTACK_SECRET_KEY")),
            "notifications_configured":bool(
                current_app.config.get("SMTP_HOST")
                and current_app.config.get("SMTP_FROM")
            ),
        },
    })


@bp.get("/")
def home():
    return render_template("public/home.html")


@bp.get("/search")
def search_page():
    city=(request.args.get("city") or "").strip() or None
    check_in=_date(request.args.get("check_in")); check_out=_date(request.args.get("check_out"))
    guests=max(int(request.args.get("guests","1")),1)
    if check_in and check_out and check_out<=check_in:
        raise RoyaError("VALIDATION_ERROR","Check-out must be after check-in.",422)
    rows=search_properties(city,check_in,check_out,guests)
    return render_template("public/search.html",properties=rows,city=city,check_in=check_in,check_out=check_out,guests=guests)


@bp.get("/api/v1/properties")
def search_api():
    city=(request.args.get("city") or "").strip() or None
    check_in=_date(request.args.get("check_in")); check_out=_date(request.args.get("check_out"))
    guests=max(int(request.args.get("guests","1")),1)
    if check_in and check_out and check_out<=check_in:
        raise RoyaError("VALIDATION_ERROR","Check-out must be after check-in.",422)
    return ok(search_properties(city,check_in,check_out,guests))


@bp.get("/hotels/<slug>")
def property_page(slug):
    check_in=_date(request.args.get("check_in")); check_out=_date(request.args.get("check_out"))
    guests=max(int(request.args.get("guests","1")),1)
    prop,images,rooms=get_property_by_slug(slug,check_in,check_out,guests)
    if not prop:
        raise RoyaError("PROPERTY_NOT_FOUND","Property not found.",404)
    with db_connection() as conn:
        amenities=list(conn.execute(
            """select a.code,a.name,a.category
               from amenities a join property_amenities pa on pa.amenity_id=a.id
               where pa.property_id=%s order by coalesce(a.category,''),a.name""",
            (prop["id"],),
        ).fetchall())
    return render_template("public/property.html",property=prop,images=images,rooms=rooms,amenities=amenities,check_in=check_in,check_out=check_out,guests=guests)


@bp.get("/partner/properties/new")
@login_required
def new_property_page():
    identity=current_identity(required=True)
    if account_type_for_user(identity.user_id)!="hotel":
        return redirect("/partner/start")

    with db_connection() as conn:
        organizations=list(conn.execute(
            """select o.id,o.name,om.role
               from organizations o
               join organization_members om on om.organization_id=o.id
               where om.user_id=%s and om.status='active' and om.role in ('owner','manager')
               order by o.name""",
            (identity.user_id,),
        ).fetchall())

    if not organizations:
        return redirect("/partner/start")

    return render_template("partner/property_new.html",organizations=organizations)


@bp.get("/partner/properties/<uuid:property_id>")
@login_required
def manage_property_page(property_id):
    identity=current_identity(required=True)

    with db_connection() as conn:
        access=conn.execute(
            """select p.*,o.name organization_name,om.role member_role
               from properties p
               join organizations o on o.id=p.organization_id
               join organization_members om on om.organization_id=o.id
               where p.id=%s and om.user_id=%s and om.status='active'""",
            (str(property_id),identity.user_id),
        ).fetchone()
        if not access:
            raise RoyaError("FORBIDDEN","You do not have access to this property.",403)

        rooms=[dict(row) for row in conn.execute(
            """select id,name,description,capacity_adults,capacity_children,base_occupancy,
                      total_inventory,bed_configuration,status
               from room_types
               where property_id=%s
               order by created_at""",
            (str(property_id),),
        ).fetchall()]

        rates=list(conn.execute(
            """select rp.*,rt.name room_type_name
               from rate_plans rp
               join room_types rt on rt.id=rp.room_type_id
               where rt.property_id=%s
               order by rt.created_at,rp.base_price_minor""",
            (str(property_id),),
        ).fetchall())

        inventory_rows=list(conn.execute(
            """select room_type_id,
                      count(*) filter(where date>=current_date and date<current_date+30) days_loaded,
                      min(total_inventory-held_inventory-sold_inventory)
                        filter(where date>=current_date and date<current_date+30 and stop_sell=false) min_available,
                      max(date) max_date
               from inventory_days
               where room_type_id in (select id from room_types where property_id=%s)
               group by room_type_id""",
            (str(property_id),),
        ).fetchall())

        readiness_row=conn.execute(
            """select
                 exists(select 1 from room_types rt where rt.property_id=%s and rt.status='active') has_room,
                 exists(select 1 from rate_plans rp join room_types rt on rt.id=rp.room_type_id
                        where rt.property_id=%s and rt.status='active' and rp.status='active') has_rate,
                 exists(select 1 from inventory_days i join room_types rt on rt.id=i.room_type_id
                        where rt.property_id=%s and rt.status='active' and i.date>=current_date
                          and i.stop_sell=false and (i.total_inventory-i.held_inventory-i.sold_inventory)>0) has_inventory""",
            (str(property_id),str(property_id),str(property_id)),
        ).fetchone()
        amenities=list(conn.execute(
            """select a.id,a.code,a.name,a.category,
                      exists(select 1 from property_amenities pa where pa.property_id=%s and pa.amenity_id=a.id) selected
               from amenities a
               order by coalesce(a.category,''),a.name""",
            (str(property_id),),
        ).fetchall())
        images=list(conn.execute(
            """select id,path,alt_text,sort_order,created_at
               from property_images where property_id=%s
               order by sort_order,created_at""",
            (str(property_id),),
        ).fetchall())
        room_images=list(conn.execute(
            """select ri.id,ri.room_type_id,ri.path,ri.alt_text,ri.sort_order,ri.created_at
               from room_images ri
               join room_types rt on rt.id=ri.room_type_id
               where rt.property_id=%s
               order by rt.created_at,ri.sort_order,ri.created_at""",
            (str(property_id),),
        ).fetchall())
        calendar_rows=list(conn.execute(
            """select i.room_type_id,i.date,i.total_inventory,i.held_inventory,i.sold_inventory,
                      greatest(0,i.total_inventory-i.held_inventory-i.sold_inventory) available_inventory,
                      i.stop_sell,i.closed_to_arrival,i.closed_to_departure,i.min_stay,i.price_override_minor
               from inventory_days i
               join room_types rt on rt.id=i.room_type_id
               where rt.property_id=%s and i.date>=current_date and i.date<current_date+30
               order by rt.created_at,i.date""",
            (str(property_id),),
        ).fetchall())

    rates_by_room={}
    for rate in rates:
        rates_by_room.setdefault(str(rate["room_type_id"]),[]).append(rate)
    inventory_by_room={str(row["room_type_id"]):row for row in inventory_rows}
    calendar_by_room={}
    for row in calendar_rows:
        calendar_by_room.setdefault(str(row["room_type_id"]),[]).append(row)

    room_images_by_room={}
    for image in room_images:
        room_images_by_room.setdefault(str(image["room_type_id"]),[]).append(image)

    for room in rooms:
        room["rates"]=rates_by_room.get(str(room["id"]),[])
        room["inventory_summary"]=inventory_by_room.get(str(room["id"]))
        room["calendar"]=calendar_by_room.get(str(room["id"]),[])
        room["images"]=room_images_by_room.get(str(room["id"]),[])

    return render_template(
        "partner/property_manage.html",
        property=access,
        rooms=rooms,
        can_manage=access["member_role"] in {"owner","manager","reservations"},
        can_edit_property=access["member_role"] in {"owner","manager"},
        amenities=amenities,
        images=images,
        readiness={
            "has_room":bool(readiness_row["has_room"]),
            "has_rate":bool(readiness_row["has_rate"]),
            "has_inventory":bool(readiness_row["has_inventory"]),
            "ready":bool(readiness_row["has_room"] and readiness_row["has_rate"] and readiness_row["has_inventory"]),
        },
    )


class PropertyCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=2,max_length=180)
    description: str = Field(default="",max_length=5000)
    address: str = Field(min_length=3,max_length=300)
    city: str = Field(min_length=2,max_length=100)
    state: str = Field(min_length=2,max_length=100)
    country: str = Field(default="Nigeria",min_length=2,max_length=100)
    phone: str|None = Field(default=None,max_length=30)
    email: str|None = Field(default=None,max_length=200)
    latitude: float|None=None
    longitude: float|None=None
    check_in_time: str="14:00"
    check_out_time: str="12:00"


class PropertyUpdate(BaseModel):
    name: str = Field(min_length=2,max_length=180)
    description: str = Field(default="",max_length=5000)
    address: str = Field(min_length=3,max_length=300)
    city: str = Field(min_length=2,max_length=100)
    state: str = Field(min_length=2,max_length=100)
    country: str = Field(default="Nigeria",min_length=2,max_length=100)
    phone: str|None = Field(default=None,max_length=30)
    email: str|None = Field(default=None,max_length=200)
    check_in_time: str="14:00"
    check_out_time: str="12:00"


class AmenityUpdate(BaseModel):
    codes: list[str] = Field(default_factory=list,max_length=50)


class ImageMetadataUpdate(BaseModel):
    alt_text: str|None = Field(default=None,max_length=300)
    sort_order: int = Field(default=0,ge=0,le=10000)


@bp.post("/api/v1/properties")
def create_property_api():
    try:
        body=PropertyCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid property details.",422,{"errors":exc.errors()}) from exc
    identity=current_identity(required=True)
    require_organization_member(identity.user_id,body.organization_id,{"owner","manager"})
    slug=f"{slugify(body.name)}-{uuidlib.uuid4().hex[:6]}"
    with db_connection() as conn:
        row=conn.execute(
            """insert into properties(organization_id,name,slug,description,address,city,state,country,phone,email,latitude,longitude,location,check_in_time,check_out_time,verification_status,status,created_by_user_id)
               values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                 case when %s is not null and %s is not null then st_setsrid(st_makepoint(%s,%s),4326)::geography else null end,
                 %s::time,%s::time,'pending','draft',%s) returning *""",
            (body.organization_id,body.name,slug,body.description,body.address,body.city,body.state,body.country,body.phone,body.email,
             body.latitude,body.longitude,body.longitude,body.latitude,body.longitude,body.latitude,body.check_in_time,body.check_out_time,identity.user_id),
        ).fetchone()
        conn.commit()
    return ok({**dict(row),"redirect_to":f"/partner/properties/{row['id']}"},201)


@bp.put("/api/v1/properties/<uuid:property_id>")
@login_required
def update_property_api(property_id):
    try:
        body=PropertyUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid property details.",422,{"errors":exc.errors()}) from exc

    identity=current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            before=conn.execute(
                """select p.*,om.role member_role
                   from properties p
                   join organization_members om on om.organization_id=p.organization_id
                   where p.id=%s and om.user_id=%s and om.status='active'
                   for update of p""",
                (str(property_id),identity.user_id),
            ).fetchone()
            if not before:
                raise RoyaError("PROPERTY_NOT_FOUND","Property not found or access denied.",404)
            if before["member_role"] not in {"owner","manager"}:
                raise RoyaError("FORBIDDEN","Only hotel owners and managers can edit property details.",403)

            identity_changed=any([
                before["name"]!=body.name,
                before["address"]!=body.address,
                before["city"]!=body.city,
                before["state"]!=body.state,
                before["country"]!=body.country,
            ])
            needs_reverify=bool(before["verification_status"]=="verified" and identity_changed)

            row=conn.execute(
                """update properties set
                     name=%s,description=%s,address=%s,city=%s,state=%s,country=%s,
                     phone=%s,email=%s,check_in_time=%s::time,check_out_time=%s::time,
                     verification_status=case when %s then 'pending' else verification_status end,
                     status=case when %s then 'draft' else status end,
                     updated_at=now()
                   where id=%s returning *""",
                (body.name,body.description,body.address,body.city,body.state,body.country,
                 body.phone,body.email,body.check_in_time,body.check_out_time,
                 needs_reverify,needs_reverify,str(property_id)),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'property.updated','property',%s,%s::jsonb,%s::jsonb)""",
                (identity.user_id,before["organization_id"],str(property_id),str(property_id),
                 json.dumps(dict(before),default=str),json.dumps(dict(row),default=str)),
            )

    return ok({**dict(row),"requires_reverification":needs_reverify})


@bp.put("/api/v1/properties/<uuid:property_id>/amenities")
@login_required
def update_property_amenities(property_id):
    try:
        body=AmenityUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid amenity selection.",422,{"errors":exc.errors()}) from exc

    identity=current_identity(required=True)
    codes=list(dict.fromkeys(body.codes))
    with db_connection() as conn:
        with conn.transaction():
            access=conn.execute(
                """select p.organization_id,om.role
                   from properties p join organization_members om on om.organization_id=p.organization_id
                   where p.id=%s and om.user_id=%s and om.status='active'
                   for update of p""",
                (str(property_id),identity.user_id),
            ).fetchone()
            if not access:
                raise RoyaError("PROPERTY_NOT_FOUND","Property not found or access denied.",404)
            if access["role"] not in {"owner","manager"}:
                raise RoyaError("FORBIDDEN","Only hotel owners and managers can edit amenities.",403)

            previous=[row["code"] for row in conn.execute(
                """select a.code from amenities a join property_amenities pa on pa.amenity_id=a.id
                   where pa.property_id=%s order by a.code""",
                (str(property_id),),
            ).fetchall()]
            selected=[]
            if codes:
                selected=list(conn.execute(
                    "select id,code from amenities where code=any(%s::text[]) order by code",
                    (codes,),
                ).fetchall())
                found={row["code"] for row in selected}
                unknown=[code for code in codes if code not in found]
                if unknown:
                    raise RoyaError("VALIDATION_ERROR","One or more amenities are not supported.",422,{"unknown":unknown})

            conn.execute("delete from property_amenities where property_id=%s",(str(property_id),))
            for amenity in selected:
                conn.execute(
                    "insert into property_amenities(property_id,amenity_id) values(%s,%s) on conflict do nothing",
                    (str(property_id),amenity["id"]),
                )
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'property.amenities_updated','property',%s,%s::jsonb,%s::jsonb)""",
                (identity.user_id,access["organization_id"],str(property_id),str(property_id),
                 json.dumps({"amenities":previous}),json.dumps({"amenities":[row["code"] for row in selected]})),
            )

    return ok({"property_id":str(property_id),"amenities":[row["code"] for row in selected]})


@bp.post("/api/v1/properties/<uuid:property_id>/images")
@login_required
def upload_property_image(property_id):
    identity=current_identity(required=True)
    with db_connection() as conn:
        prop=conn.execute("select organization_id from properties where id=%s",(str(property_id),)).fetchone()
    if not prop:
        raise RoyaError("PROPERTY_NOT_FOUND","Property not found.",404)
    require_organization_member(identity.user_id,str(prop["organization_id"]),{"owner","manager"})

    file=request.files.get("file")
    try:
        raw,extension=read_image_upload(file)
    except ValueError as exc:
        messages={
            "IMAGE_REQUIRED":"An image file is required.",
            "IMAGE_TYPE":"Only JPEG, PNG and WebP images are accepted.",
            "IMAGE_TOO_LARGE":"Image must be 10 MB or smaller.",
        }
        raise RoyaError("VALIDATION_ERROR",messages.get(str(exc),"Invalid image."),422) from exc

    path=f"{property_id}/{uuidlib.uuid4().hex}{extension}"
    client=supabase_admin_client()
    try:
        client.storage.from_("property-images").upload(path,raw,{"content-type":file.mimetype,"upsert":"false"})
    except Exception as exc:
        raise RoyaError("STORAGE_UPLOAD_FAILED","Image upload failed.",502) from exc

    public_url=client.storage.from_("property-images").get_public_url(path)
    alt_text=(request.form.get("alt_text") or "").strip() or None
    if alt_text and len(alt_text)>300:
        raise RoyaError("VALIDATION_ERROR","Alt text must be 300 characters or fewer.",422)

    with db_connection() as conn:
        row=conn.execute(
            """insert into property_images(property_id,path,alt_text,sort_order)
               values(%s,%s,%s,coalesce((select max(sort_order)+1 from property_images where property_id=%s),0))
               returning *""",
            (str(property_id),public_url,alt_text,str(property_id)),
        ).fetchone()
        conn.commit()
    return ok(row,201)


@bp.put("/api/v1/properties/<uuid:property_id>/images/<uuid:image_id>")
@login_required
def update_property_image(property_id,image_id):
    try:
        body=ImageMetadataUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError("VALIDATION_ERROR","Invalid image details.",422,{"errors":exc.errors()}) from exc

    identity=current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            image=conn.execute(
                """select pi.*,p.organization_id
                   from property_images pi join properties p on p.id=pi.property_id
                   where pi.id=%s and pi.property_id=%s
                   for update of pi""",
                (str(image_id),str(property_id)),
            ).fetchone()
            if not image:
                raise RoyaError("IMAGE_NOT_FOUND","Property image not found.",404)
            require_organization_member(identity.user_id,str(image["organization_id"]),{"owner","manager"})
            row=conn.execute(
                """update property_images
                   set alt_text=%s,sort_order=%s
                   where id=%s returning *""",
                ((body.alt_text or "").strip() or None,body.sort_order,str(image_id)),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'property.image_updated','property_image',%s,%s::jsonb,%s::jsonb)""",
                (
                    identity.user_id,image["organization_id"],str(property_id),str(image_id),
                    json.dumps({"alt_text":image["alt_text"],"sort_order":image["sort_order"]}),
                    json.dumps({"alt_text":row["alt_text"],"sort_order":row["sort_order"]}),
                ),
            )
    return ok(row)


@bp.delete("/api/v1/properties/<uuid:property_id>/images/<uuid:image_id>")
@login_required
def delete_property_image(property_id,image_id):
    identity=current_identity(required=True)
    with db_connection() as conn:
        with conn.transaction():
            image=conn.execute(
                """select pi.*,p.organization_id
                   from property_images pi join properties p on p.id=pi.property_id
                   where pi.id=%s and pi.property_id=%s
                   for update of pi""",
                (str(image_id),str(property_id)),
            ).fetchone()
            if not image:
                raise RoyaError("IMAGE_NOT_FOUND","Property image not found.",404)
            require_organization_member(identity.user_id,str(image["organization_id"]),{"owner","manager"})
            conn.execute("delete from property_images where id=%s",(str(image_id),))
            conn.execute(
                """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,%s,%s,'property.image_deleted','property_image',%s,%s::jsonb,'{}'::jsonb)""",
                (
                    identity.user_id,image["organization_id"],str(property_id),str(image_id),
                    json.dumps({"path":image["path"],"alt_text":image["alt_text"],"sort_order":image["sort_order"]}),
                ),
            )

    storage_cleanup=True
    object_path=storage_object_path(image["path"],"property-images")
    if object_path:
        try:
            supabase_admin_client().storage.from_("property-images").remove([object_path])
        except Exception:
            storage_cleanup=False

    return ok({"deleted":True,"image_id":str(image_id),"storage_cleanup":storage_cleanup})
