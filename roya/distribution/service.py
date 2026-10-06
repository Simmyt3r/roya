import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from .base import DirectBookingChannel,RoyaMarketplaceChannel


DISTRIBUTION_ROLES={"owner","manager"}
BUILT_IN_CHANNELS={
    "direct_booking":{
        "label":"Direct Booking",
        "description":"Bookings made on iRoya and hotel mini-domains using canonical inventory.",
        "adapter":DirectBookingChannel,
    },
    "roya_marketplace":{
        "label":"Roya Marketplace",
        "description":"iRoya marketplace discovery using the same room, rate and inventory source.",
        "adapter":RoyaMarketplaceChannel,
    },
}
FUTURE_CHANNELS=(
    {
        "key":"booking_com",
        "label":"Booking.com",
        "description":"OTA connectivity remains disabled until provider onboarding and credentials exist.",
    },
    {
        "key":"google_hotels",
        "label":"Google Hotels",
        "description":"Hotel-feed connectivity remains a future adapter until provider onboarding exists.",
    },
    {
        "key":"pms",
        "label":"PMS / channel manager",
        "description":"External PMS integrations will plug into the same adapter contract later.",
    },
)


def partner_distribution_scope(user_id):
    with db_connection() as conn:
        rows=conn.execute(
            """select o.id,o.name,om.role
               from organizations o
               join organization_members om on om.organization_id=o.id
               where om.user_id=%s
                 and om.status='active'
                 and om.role=any(%s::text[])
               order by o.name""",
            (user_id,list(DISTRIBUTION_ROLES)),
        ).fetchall()
    return [dict(row) for row in rows]


def distribution_dashboard(user_id,organization_id=None,property_id=None):
    organizations=partner_distribution_scope(user_id)
    if not organizations:
        raise RoyaError(
            "FORBIDDEN",
            "Distribution management requires an owner or manager role.",
            403,
        )

    allowed_ids={str(row["id"]) for row in organizations}
    if organization_id and str(organization_id) not in allowed_ids:
        raise RoyaError("FORBIDDEN","You do not manage distribution for that organization.",403)

    selected_ids=[str(organization_id)] if organization_id else sorted(allowed_ids)

    with db_connection() as conn:
        properties=[
            dict(row) for row in conn.execute(
                """select
                     p.id,p.organization_id,p.name,p.city,p.state,p.status,p.verification_status,
                     exists(
                       select 1 from room_types rt
                       where rt.property_id=p.id and rt.status='active'
                     ) has_room,
                     exists(
                       select 1 from rate_plans rp
                       join room_types rt on rt.id=rp.room_type_id
                       where rt.property_id=p.id
                         and rt.status='active'
                         and rp.status='active'
                     ) has_rate,
                     exists(
                       select 1 from inventory_days i
                       join room_types rt on rt.id=i.room_type_id
                       where rt.property_id=p.id
                         and rt.status='active'
                         and i.date>=current_date
                         and i.stop_sell=false
                         and (i.total_inventory-i.held_inventory-i.sold_inventory)>0
                     ) has_inventory
                   from properties p
                   where p.organization_id=any(%s::uuid[])
                     and (%s::uuid is null or p.id=%s)
                   order by p.name""",
                (selected_ids,property_id,property_id),
            ).fetchall()
        ]

        if property_id and not properties:
            raise RoyaError("FORBIDDEN","You do not manage distribution for that property.",403)

        property_ids=[str(row["id"]) for row in properties]
        connections=[]
        logs=[]
        if property_ids:
            connections=[
                dict(row) for row in conn.execute(
                    """select id,organization_id,property_id,channel,status,last_synced_at,created_at,updated_at
                       from channel_connections
                       where property_id=any(%s::uuid[])
                         and channel=any(%s::text[])
                       order by created_at asc""",
                    (property_ids,list(BUILT_IN_CHANNELS)),
                ).fetchall()
            ]
            logs=[
                dict(row) for row in conn.execute(
                    """select l.id,l.connection_id,l.direction,l.resource_type,l.status,l.detail,l.created_at,
                              c.channel,c.property_id,p.name property_name
                       from channel_sync_logs l
                       join channel_connections c on c.id=l.connection_id
                       join properties p on p.id=c.property_id
                       where c.property_id=any(%s::uuid[])
                       order by l.created_at desc
                       limit 80""",
                    (property_ids,),
                ).fetchall()
            ]

    connection_map={}
    for row in connections:
        connection_map.setdefault((str(row["property_id"]),row["channel"]),row)

    property_cards=[]
    for prop in properties:
        prop=dict(prop)
        prop["ready"]=bool(
            prop["status"]=="active"
            and prop["verification_status"]=="verified"
            and prop["has_room"]
            and prop["has_rate"]
            and prop["has_inventory"]
        )
        channels=[]
        for key,meta in BUILT_IN_CHANNELS.items():
            connection=connection_map.get((str(prop["id"]),key))
            channels.append({
                "key":key,
                "label":meta["label"],
                "description":meta["description"],
                "connection_id":str(connection["id"]) if connection else "",
                "status":connection["status"] if connection else "not_initialized",
                "last_synced_at":connection["last_synced_at"] if connection else None,
            })
        prop["channels"]=channels
        property_cards.append(prop)

    return {
        "organizations":organizations,
        "properties":property_cards,
        "logs":logs,
        "future_channels":list(FUTURE_CHANNELS),
        "selected_organization_id":str(organization_id) if organization_id else "",
        "selected_property_id":str(property_id) if property_id else "",
    }


def sync_builtin_channel(user_id,property_id,channel):
    if channel not in BUILT_IN_CHANNELS:
        raise RoyaError(
            "CHANNEL_NOT_AVAILABLE",
            "That distribution channel is not operational in iRoya yet.",
            422,
        )

    with db_connection() as conn:
        access=conn.execute(
            """select p.id,p.organization_id,p.name,om.role
               from properties p
               join organization_members om on om.organization_id=p.organization_id
               where p.id=%s
                 and om.user_id=%s
                 and om.status='active'""",
            (property_id,user_id),
        ).fetchone()
        if not access or access["role"] not in DISTRIBUTION_ROLES:
            raise RoyaError("FORBIDDEN","You cannot manage distribution for this property.",403)

        with conn.transaction():
            conn.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (f"iroya:distribution:{property_id}:{channel}",),
            )
            connection=conn.execute(
                """select *
                   from channel_connections
                   where property_id=%s and channel=%s
                   order by created_at asc
                   limit 1
                   for update""",
                (property_id,channel),
            ).fetchone()
            if not connection:
                connection=conn.execute(
                    """insert into channel_connections(
                         organization_id,property_id,channel,status,settings
                       ) values(%s,%s,%s,'active',%s::jsonb)
                       returning *""",
                    (
                        access["organization_id"],property_id,channel,
                        json.dumps({"built_in":True,"managed_by":"iroya"}),
                    ),
                ).fetchone()
            else:
                connection=conn.execute(
                    """update channel_connections
                       set status='active',updated_at=now()
                       where id=%s
                       returning *""",
                    (connection["id"],),
                ).fetchone()

    adapter=BUILT_IN_CHANNELS[channel]["adapter"]()
    operations=(
        ("push","property",lambda:adapter.push_property(str(property_id))),
        ("push","rates",lambda:adapter.push_rates(str(property_id))),
        ("push","inventory",lambda:adapter.push_inventory(str(property_id))),
        ("pull","reservations",lambda:adapter.pull_reservations(str(property_id))),
    )

    results=[]
    failed=False
    try:
        health=adapter.health_check()
        if health.get("status")!="ok":
            failed=True
    except Exception as exc:
        health={"status":"error","message":str(exc)[:240]}
        failed=True

    for direction,resource_type,operation in operations:
        try:
            detail=operation()
            status="success"
        except Exception as exc:
            detail={"error":str(exc)[:240]}
            status="failed"
            failed=True
        results.append({
            "direction":direction,
            "resource_type":resource_type,
            "status":status,
            "detail":detail,
        })

    final_status="error" if failed else "active"
    with db_connection() as conn:
        with conn.transaction():
            for item in results:
                conn.execute(
                    """insert into channel_sync_logs(
                         connection_id,direction,resource_type,status,detail
                       ) values(%s,%s,%s,%s,%s::jsonb)""",
                    (
                        connection["id"],item["direction"],item["resource_type"],
                        item["status"],json.dumps(item["detail"]),
                    ),
                )
            row=conn.execute(
                """update channel_connections
                   set status=%s,
                       last_synced_at=case when %s='active' then now() else last_synced_at end,
                       settings=settings||%s::jsonb,
                       updated_at=now()
                   where id=%s
                   returning id,organization_id,property_id,channel,status,last_synced_at""",
                (
                    final_status,final_status,
                    json.dumps({"health":health}),
                    connection["id"],
                ),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(
                     actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
                   ) values(%s,%s,%s,'distribution.channel_synced','channel_connection',%s,%s::jsonb)""",
                (
                    user_id,access["organization_id"],property_id,str(connection["id"]),
                    json.dumps({
                        "channel":channel,
                        "status":final_status,
                        "resources":[
                            {
                                "direction":item["direction"],
                                "resource_type":item["resource_type"],
                                "status":item["status"],
                            }
                            for item in results
                        ],
                    }),
                ),
            )

    result=dict(row)
    result["health"]=health
    result["operations"]=results
    return result
