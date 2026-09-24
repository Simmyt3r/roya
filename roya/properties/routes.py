from datetime import date
import uuid as uuidlib
from flask import Blueprint, current_app, redirect, render_template, request
from pydantic import BaseModel, Field, ValidationError

from roya.auth.service import account_type_for_user, current_identity, login_required
from roya.common.db import db_connection, supabase_admin_client
from roya.common.errors import RoyaError
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
    return ok({"service":"roya","status":"ok","database_configured":bool(current_app.config.get("DATABASE_URL"))})


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
    return render_template("public/property.html",property=prop,images=images,rooms=rooms,check_in=check_in,check_out=check_out,guests=guests)


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

    rates_by_room={}
    for rate in rates:
        rates_by_room.setdefault(str(rate["room_type_id"]),[]).append(rate)
    inventory_by_room={str(row["room_type_id"]):row for row in inventory_rows}

    for room in rooms:
        room["rates"]=rates_by_room.get(str(room["id"]),[])
        room["inventory_summary"]=inventory_by_room.get(str(room["id"]))

    return render_template(
        "partner/property_manage.html",
        property=access,
        rooms=rooms,
        can_manage=access["member_role"] in {"owner","manager","reservations"},
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


@bp.post("/api/v1/properties/<uuid:property_id>/images")
def upload_property_image(property_id):
    identity=current_identity(required=True)
    with db_connection() as conn:
        prop=conn.execute("select organization_id from properties where id=%s",(str(property_id),)).fetchone()
    if not prop:
        raise RoyaError("PROPERTY_NOT_FOUND","Property not found.",404)
    require_organization_member(identity.user_id,str(prop["organization_id"]),{"owner","manager"})
    file=request.files.get("file")
    if not file or not file.filename:
        raise RoyaError("VALIDATION_ERROR","An image file is required.",422)
    allowed={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}
    if file.mimetype not in allowed:
        raise RoyaError("VALIDATION_ERROR","Only JPEG, PNG and WebP images are accepted.",422)
    raw=file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:
        raise RoyaError("VALIDATION_ERROR","Image must be 10 MB or smaller.",422)
    path=f"{property_id}/{uuidlib.uuid4().hex}{allowed[file.mimetype]}"
    client=supabase_admin_client()
    try:
        client.storage.from_("property-images").upload(path,raw,{"content-type":file.mimetype,"upsert":"false"})
    except Exception as exc:
        raise RoyaError("STORAGE_UPLOAD_FAILED","Image upload failed.",502) from exc
    public_url=client.storage.from_("property-images").get_public_url(path)
    with db_connection() as conn:
        row=conn.execute(
            "insert into property_images(property_id,path,sort_order) values(%s,%s,coalesce((select max(sort_order)+1 from property_images where property_id=%s),0)) returning *",
            (str(property_id),public_url,str(property_id)),
        ).fetchone(); conn.commit()
    return ok(row,201)
