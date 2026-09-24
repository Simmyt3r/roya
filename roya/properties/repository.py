from datetime import date
from roya.common.db import db_connection


def search_properties(
    city: str | None,
    check_in: date | None,
    check_out: date | None,
    guests: int,
    limit: int = 30,
    *,
    min_price_minor: int | None = None,
    max_price_minor: int | None = None,
    refundable_only: bool = False,
    meal_plan: str | None = None,
    guarantee_type: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 25,
    sort: str = "recommended",
):
    params=[]
    where=[
        "p.status='active'",
        "p.verification_status='verified'",
        "rt.status='active'",
        "rp.status='active'",
        "rt.capacity_adults >= %s",
    ]
    params.append(guests)

    if city:
        where.append("(p.city ilike %s or p.state ilike %s or p.name ilike %s or p.address ilike %s)")
        needle=f"%{city}%"
        params.extend([needle,needle,needle,needle])

    if min_price_minor is not None:
        where.append("rp.base_price_minor >= %s")
        params.append(min_price_minor)
    if max_price_minor is not None:
        where.append("rp.base_price_minor <= %s")
        params.append(max_price_minor)
    if refundable_only:
        where.append("rp.refundable=true")
    if meal_plan:
        where.append("rp.meal_plan=%s")
        params.append(meal_plan)
    if guarantee_type:
        where.append("rp.guarantee_type=%s")
        params.append(guarantee_type)

    if check_in and check_out:
        nights=(check_out-check_in).days
        where.append(
            """(
                select count(*)
                from inventory_days i
                where i.room_type_id=rt.id
                  and i.date >= %s
                  and i.date < %s
                  and i.stop_sell=false
                  and i.min_stay<=%s
                  and (i.total_inventory-i.held_inventory-i.sold_inventory)>0
              )=%s"""
        )
        params.extend([check_in,check_out,nights,nights])
        where.append(
            """not exists(
                select 1 from inventory_days i
                where i.room_type_id=rt.id
                  and i.date=%s
                  and i.closed_to_arrival
              )"""
        )
        params.append(check_in)
        where.append(
            """not exists(
                select 1 from inventory_days i
                where i.room_type_id=rt.id
                  and i.date=(%s::date-1)
                  and i.closed_to_departure
              )"""
        )
        params.append(check_out)

    has_origin=latitude is not None and longitude is not None
    if has_origin:
        where.append(
            """p.location is not null and
               st_dwithin(
                 p.location,
                 st_setsrid(st_makepoint(%s,%s),4326)::geography,
                 %s
               )"""
        )
        params.extend([longitude,latitude,radius_km*1000])

    distance_sql="null::double precision"
    select_params=[]
    if has_origin:
        distance_sql="""st_distance(
          p.location,
          st_setsrid(st_makepoint(%s,%s),4326)::geography
        )/1000.0"""
        select_params.extend([longitude,latitude])

    order_sql="p.featured desc,rating desc,p.created_at desc"
    if sort=="price_asc":
        order_sql="m.from_price_minor asc,p.featured desc,rating desc"
    elif sort=="price_desc":
        order_sql="m.from_price_minor desc,p.featured desc,rating desc"
    elif sort=="rating":
        order_sql="rating desc,p.featured desc,m.from_price_minor asc"
    elif sort=="distance" and has_origin:
        order_sql="distance_km asc,p.featured desc,rating desc"

    sql=f"""
      with matching as (
        select p.id property_id,min(rp.base_price_minor) from_price_minor
        from properties p
        join room_types rt on rt.property_id=p.id
        join rate_plans rp on rp.room_type_id=rt.id
        where {' and '.join(where)}
        group by p.id
      )
      select p.id,p.name,p.slug,p.city,p.state,p.country,p.description,p.address,
        (select pi.path from property_images pi where pi.property_id=p.id order by pi.sort_order,pi.created_at limit 1) cover_image,
        m.from_price_minor,
        coalesce((select round(avg(r.rating)::numeric,1) from reviews r where r.property_id=p.id and r.is_visible),0) rating,
        {distance_sql} distance_km
      from matching m
      join properties p on p.id=m.property_id
      order by {order_sql}
      limit %s
    """
    query_params=params+select_params+[limit]
    with db_connection() as conn:
        return list(conn.execute(sql,query_params).fetchall())


def get_property_by_slug(slug: str, check_in: date | None=None, check_out: date | None=None, guests: int=1):
    with db_connection() as conn:
        prop=conn.execute(
            """select p.*,coalesce((select round(avg(r.rating)::numeric,1) from reviews r where r.property_id=p.id and r.is_visible),0) rating
               from properties p where p.slug=%s and p.status='active' and p.verification_status='verified'""",(slug,)
        ).fetchone()
        if not prop: return None,[],[]
        images=list(conn.execute("select id,path,alt_text from property_images where property_id=%s order by sort_order,created_at",(prop["id"],)).fetchall())
        rooms=list(conn.execute(
            """select rt.id,rt.name,rt.description,rt.capacity_adults,rt.capacity_children,rt.total_inventory,
                      rp.id rate_plan_id,rp.name rate_plan_name,rp.base_price_minor,rp.currency,rp.guarantee_type,
                      rp.refundable,rp.meal_plan,rp.cancellation_policy,
                      (select ri.path from room_images ri where ri.room_type_id=rt.id order by ri.sort_order,ri.created_at limit 1) cover_image,
                      (select ri.alt_text from room_images ri where ri.room_type_id=rt.id order by ri.sort_order,ri.created_at limit 1) cover_alt
               from room_types rt join rate_plans rp on rp.room_type_id=rt.id and rp.status='active'
               where rt.property_id=%s and rt.status='active' and rt.capacity_adults >= %s order by rp.base_price_minor""",(prop["id"],guests)
        ).fetchall())
        if check_in and check_out:
            nights=(check_out-check_in).days; filtered=[]
            for room in rooms:
                row=conn.execute(
                    """select count(*) night_count,min(total_inventory-held_inventory-sold_inventory) min_available
                       from inventory_days where room_type_id=%s and date >= %s and date < %s and stop_sell=false""",
                    (room["id"],check_in,check_out),
                ).fetchone()
                if row and row["night_count"]==nights and (row["min_available"] or 0)>0: filtered.append(room)
            rooms=filtered
        return prop,images,rooms
