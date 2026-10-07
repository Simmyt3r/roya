import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError


HANDOVER_WRITE_ROLES={"owner","manager","reservations"}
HANDOVER_PRIORITIES={"normal","important","urgent"}


def handover_snapshot(user_id,property_id=None,limit=20):
    try:
        limit=max(1,min(int(limit or 20),50))
    except (TypeError,ValueError) as exc:
        raise RoyaError("VALIDATION_ERROR","Handover limit is invalid.",422) from exc

    with db_connection() as conn:
        properties=[
            dict(row) for row in conn.execute(
                """select p.id,p.name,p.organization_id,om.role
                   from properties p
                   join organization_members om on om.organization_id=p.organization_id
                   where om.user_id=%s and om.status='active'
                   order by p.name""",
                (user_id,),
            ).fetchall()
        ]
        requested=str(property_id or "").strip()
        selected=next(
            (item for item in properties if str(item["id"])==requested),
            None,
        ) if requested else None
        if requested and not selected:
            raise RoyaError("NOT_FOUND","Property not found.",404)
        selected_property_id=str(selected["id"]) if selected else None

        where=["om.user_id=%s","om.status='active'","hn.status='open'"]
        params=[user_id]
        if selected_property_id:
            where.append("hn.property_id=%s")
            params.append(selected_property_id)
        params.append(limit)

        notes=[
            dict(row) for row in conn.execute(
                f"""select
                      hn.id,hn.organization_id,hn.property_id,hn.note,hn.priority,hn.status,
                      hn.created_by,hn.created_at,p.name property_name,om.role member_role,
                      coalesce(nullif(trim(pr.name),''),u.email,'Hotel teammate') created_by_name
                   from private.hotel_handover_notes hn
                   join properties p on p.id=hn.property_id
                   join organization_members om on om.organization_id=hn.organization_id
                   left join profiles pr on pr.id=hn.created_by
                   left join auth.users u on u.id=hn.created_by
                   where {' and '.join(where)}
                   order by
                     case hn.priority when 'urgent' then 0 when 'important' then 1 else 2 end,
                     hn.created_at desc
                   limit %s""",
                tuple(params),
            ).fetchall()
        ]

    writable_properties=[
        item for item in properties if item["role"] in HANDOVER_WRITE_ROLES
    ]
    return {
        "notes":notes,
        "properties":properties,
        "writable_properties":writable_properties,
        "selected_property_id":selected_property_id,
        "selected_property":selected,
        "can_write":bool(writable_properties),
    }


def create_handover_note(user_id,property_id,note,priority="normal"):
    property_id=str(property_id or "").strip()
    note=(note or "").strip()
    priority=(priority or "normal").strip().lower()
    if not property_id:
        raise RoyaError("VALIDATION_ERROR","Choose the hotel this note belongs to.",422)
    if not note or len(note)>1000:
        raise RoyaError("VALIDATION_ERROR","Handover note must be between 1 and 1000 characters.",422)
    if priority not in HANDOVER_PRIORITIES:
        raise RoyaError("VALIDATION_ERROR","Invalid handover priority.",422)

    with db_connection() as conn:
        with conn.transaction():
            access=conn.execute(
                """select p.id,p.organization_id,om.role
                   from properties p
                   join organization_members om on om.organization_id=p.organization_id
                   where p.id=%s and om.user_id=%s and om.status='active'
                   for update of p""",
                (property_id,user_id),
            ).fetchone()
            if not access:
                raise RoyaError("NOT_FOUND","Property not found.",404)
            if access["role"] not in HANDOVER_WRITE_ROLES:
                raise RoyaError("FORBIDDEN","Your hotel role cannot create handover notes.",403)

            row=conn.execute(
                """insert into private.hotel_handover_notes(
                     organization_id,property_id,note,priority,status,created_by
                   ) values(%s,%s,%s,%s,'open',%s)
                   returning id,organization_id,property_id,note,priority,status,created_by,created_at""",
                (access["organization_id"],property_id,note,priority,user_id),
            ).fetchone()

            conn.execute(
                """insert into audit_logs(
                     actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
                   ) values(%s,%s,%s,'handover.created','handover_note',%s,%s::jsonb)""",
                (
                    user_id,access["organization_id"],property_id,str(row["id"]),
                    json.dumps({"priority":priority,"note":note}),
                ),
            )
    return dict(row)


def resolve_handover_note(user_id,note_id):
    with db_connection() as conn:
        with conn.transaction():
            row=conn.execute(
                """select hn.*,om.role
                   from private.hotel_handover_notes hn
                   join organization_members om on om.organization_id=hn.organization_id
                   where hn.id=%s and om.user_id=%s and om.status='active'
                   for update of hn""",
                (str(note_id),user_id),
            ).fetchone()
            if not row:
                raise RoyaError("NOT_FOUND","Handover note not found.",404)
            if row["role"] not in HANDOVER_WRITE_ROLES:
                raise RoyaError("FORBIDDEN","Your hotel role cannot resolve handover notes.",403)
            if row["status"]=="resolved":
                return dict(row)

            resolved=conn.execute(
                """update private.hotel_handover_notes
                   set status='resolved',resolved_by=%s,resolved_at=now(),updated_at=now()
                   where id=%s
                   returning id,organization_id,property_id,note,priority,status,
                             created_by,created_at,resolved_by,resolved_at""",
                (user_id,str(note_id)),
            ).fetchone()

            conn.execute(
                """insert into audit_logs(
                     actor_user_id,organization_id,property_id,action,entity_type,entity_id,
                     before_json,after_json
                   ) values(%s,%s,%s,'handover.resolved','handover_note',%s,%s::jsonb,%s::jsonb)""",
                (
                    user_id,row["organization_id"],row["property_id"],str(note_id),
                    json.dumps({"status":row["status"]}),
                    json.dumps({"status":"resolved"}),
                ),
            )
    return dict(resolved)
