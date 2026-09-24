from datetime import date
from roya.common.db import db_connection


def search_properties(city: str | None, check_in: date | None, check_out: date | None, guests: int, limit: int = 30):
    params=[]
    where=["p.status='active'","p.verification_status='verified'"]
    if city:
        where.append("(p.city ilike %s or p.state ilike %s or p.name ilike %s)")
        needle=f"%{city}%"; params.extend([needle,needle,needle])
    availability_sql=""
    if check_in and check_out:
        availability_sql="""
          and exists(
            select 1 from room_types rt
            join rate_plans rp on rp.room_type_id=rt.id and rp.status='active'
            where rt.property_id=p.id and rt.status='active' and rt.capacity_adults >= %s
              and (
                select count(*) from inventory_days i
                where i.room_type_id=rt.id and i.date >= %s and i.date < %s
                  and i.stop_sell=false and (i.total_inventory-i.held_inventory-i.sold_inventory)>0
              )=(%s::date-%s::date)
          )
        """
        params.extend([guests,check_in,check_out,check_out,check_in])
    params.append(limit)
    sql=f"""
      select p.id,p.name,p.slug,p.city,p.state,p.country,p.description,p.address,
        (select pi.path from property_images pi where pi.property_id=p.id order by pi.sort_order,pi.created_at limit 1) cover_image,
        (select min(rp.base_price_minor) from room_types rt join rate_plans rp on rp.room_type_id=rt.id where rt.property_id=p.id and rt.status='active' and rp.status='active') from_price_minor,
        coalesce((select round(avg(r.rating)::numeric,1) from reviews r where r.property_id=p.id and r.is_visible),0) rating
      from properties p
      where {' and '.join(where)}
      {availability_sql}
      order by p.featured desc,p.created_at desc
      limit %s
    """
    with db_connection() as conn:
        return list(conn.execute(sql,params).fetchall())


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
                      rp.id rate_plan_id,rp.name rate_plan_name,rp.base_price_minor,rp.currency,rp.guarantee_type,\n                      rp.refundable,rp.meal_plan,rp.cancellation_policy
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
