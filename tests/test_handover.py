from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.organizations import handover_service
from roya.organizations import routes as organization_routes
from roya.organizations.handover_service import (
    create_handover_note,
    handover_snapshot,
    resolve_handover_note,
)


class _Txn:
    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False


class _Result:
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


def test_handover_snapshot_is_membership_and_property_scoped(monkeypatch):
    property_id=str(uuid4())
    note_id=str(uuid4())
    captured=[]

    class _Connection:
        def execute(self,sql,params):
            captured.append((sql,params))
            if "select p.id,p.name,p.organization_id,om.role" in sql:
                return _Result(rows=[{
                    "id":property_id,
                    "name":"Example Hotel",
                    "organization_id":"org-1",
                    "role":"reservations",
                }])
            if "from private.hotel_handover_notes hn" in sql:
                return _Result(rows=[{
                    "id":note_id,
                    "organization_id":"org-1",
                    "property_id":property_id,
                    "note":"Guest in 204 requested a late wake-up call.",
                    "priority":"important",
                    "status":"open",
                    "created_by":"user-2",
                    "created_at":"2026-10-07 14:00",
                    "property_name":"Example Hotel",
                    "member_role":"reservations",
                    "created_by_name":"Desk Agent",
                }])
            raise AssertionError(sql)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(handover_service,"db_connection",lambda:_connection())
    snapshot=handover_snapshot("user-1",property_id=property_id)

    assert snapshot["selected_property_id"]==property_id
    assert snapshot["can_write"] is True
    assert snapshot["notes"][0]["priority"]=="important"

    note_sql,note_params=captured[-1]
    assert "om.user_id=%s" in note_sql
    assert "om.status='active'" in note_sql
    assert "hn.property_id=%s" in note_sql
    assert note_params[0:2]==("user-1",property_id)


def test_handover_snapshot_rejects_inaccessible_property(monkeypatch):
    allowed_property=str(uuid4())

    class _Connection:
        def execute(self,sql,params):
            return _Result(rows=[{
                "id":allowed_property,
                "name":"Allowed Hotel",
                "organization_id":"org-1",
                "role":"staff",
            }])

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(handover_service,"db_connection",lambda:_connection())
    with pytest.raises(RoyaError) as raised:
        handover_snapshot("user-1",property_id=str(uuid4()))
    assert raised.value.code=="NOT_FOUND"


class _MutationConnection:
    def __init__(self,role="reservations",status="open"):
        self.role=role
        self.status=status
        self.audit_actions=[]

    def transaction(self):
        return _Txn()

    def execute(self,sql,params=None):
        if "select p.id,p.organization_id,om.role" in sql:
            return _Result(row={
                "id":"property-1",
                "organization_id":"org-1",
                "role":self.role,
            })
        if "insert into private.hotel_handover_notes" in sql:
            return _Result(row={
                "id":"note-1",
                "organization_id":"org-1",
                "property_id":"property-1",
                "note":params[2],
                "priority":params[3],
                "status":"open",
                "created_by":params[4],
                "created_at":"2026-10-07 14:00",
            })
        if "select hn.*,om.role" in sql:
            return _Result(row={
                "id":"note-1",
                "organization_id":"org-1",
                "property_id":"property-1",
                "note":"Follow up with room 204.",
                "priority":"normal",
                "status":self.status,
                "created_by":"user-2",
                "role":self.role,
            })
        if "update private.hotel_handover_notes" in sql:
            self.status="resolved"
            return _Result(row={
                "id":"note-1",
                "organization_id":"org-1",
                "property_id":"property-1",
                "note":"Follow up with room 204.",
                "priority":"normal",
                "status":"resolved",
                "created_by":"user-2",
                "created_at":"2026-10-07 14:00",
                "resolved_by":params[0],
                "resolved_at":"2026-10-07 14:15",
            })
        if "insert into audit_logs" in sql:
            self.audit_actions.append(params[3])
            return _Result()
        raise AssertionError(sql)


def _mutation_db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def test_reservations_role_can_create_and_resolve_handover(monkeypatch):
    connection=_MutationConnection(role="reservations")
    monkeypatch.setattr(handover_service,"db_connection",lambda:_mutation_db(connection)())

    created=create_handover_note(
        "user-1","property-1","VIP arrival requested quiet room.","urgent"
    )
    assert created["priority"]=="urgent"
    assert connection.audit_actions[-1]=="handover.created"

    resolved=resolve_handover_note("user-1","note-1")
    assert resolved["status"]=="resolved"
    assert connection.audit_actions[-1]=="handover.resolved"


@pytest.mark.parametrize("role",["staff","finance"])
def test_read_only_roles_cannot_mutate_handover(monkeypatch,role):
    connection=_MutationConnection(role=role)
    monkeypatch.setattr(handover_service,"db_connection",lambda:_mutation_db(connection)())

    with pytest.raises(RoyaError) as create_error:
        create_handover_note("user-1","property-1","Attempted note.","normal")
    assert create_error.value.code=="FORBIDDEN"

    with pytest.raises(RoyaError) as resolve_error:
        resolve_handover_note("user-1","note-1")
    assert resolve_error.value.code=="FORBIDDEN"


def test_dashboard_handover_renders_note_and_form_for_writer():
    property_id=str(uuid4())
    snapshot={
        "notes":[{
            "id":str(uuid4()),
            "property_id":property_id,
            "note":"Room 204 AC needs engineering follow-up.",
            "priority":"urgent",
            "created_at":"2026-10-07 14:00",
            "property_name":"Example Hotel",
            "member_role":"reservations",
            "created_by_name":"Desk Agent",
        }],
        "writable_properties":[{
            "id":property_id,
            "name":"Example Hotel",
            "organization_id":str(uuid4()),
            "role":"reservations",
        }],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel"},
        "can_write":True,
    }
    operations={
        "properties":[{"id":property_id,"name":"Example Hotel"}],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel"},
        "summary":{
            "arrivals_today":0,"departures_today":0,"in_house":0,
            "active_next_24h":0,
        },
        "arrivals":[],"departures":[],"overdue":[],"forecast":[],"tasks":[],
        "horizon_days":7,
    }

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"reservations"}],
            hotel_operations=operations,
            handover=snapshot,
        )

    assert "Shift handover" in html
    assert "Room 204 AC needs engineering follow-up." in html
    assert 'data-handover-resolve' in html
    assert 'data-handover-form' in html
    assert f'value="{property_id}"' in html


def test_dashboard_handover_is_view_only_for_staff():
    property_id=str(uuid4())
    handover={
        "notes":[{
            "id":str(uuid4()),
            "property_id":property_id,
            "note":"Late arrival expected after midnight.",
            "priority":"important",
            "created_at":"2026-10-07 14:00",
            "property_name":"Example Hotel",
            "member_role":"staff",
            "created_by_name":"Manager",
        }],
        "writable_properties":[],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel"},
        "can_write":False,
    }
    operations={
        "properties":[{"id":property_id,"name":"Example Hotel"}],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel"},
        "summary":{
            "arrivals_today":0,"departures_today":0,"in_house":0,
            "active_next_24h":0,
        },
        "arrivals":[],"departures":[],"overdue":[],"forecast":[],"tasks":[],
        "horizon_days":7,
    }

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"staff"}],
            hotel_operations=operations,
            handover=handover,
        )

    assert "Late arrival expected after midnight." in html
    assert 'data-handover-resolve' not in html
    assert 'data-handover-form' not in html


def test_handover_api_forwards_validated_payload(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="desk@example.com")
    property_id=uuid4()
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(organization_routes,"current_identity",lambda required=False:identity)

    def _create(user_id,property_id_value,note,priority):
        captured.update({
            "user_id":user_id,
            "property_id":property_id_value,
            "note":note,
            "priority":priority,
        })
        return {"id":str(uuid4()),"status":"open"}

    monkeypatch.setattr(organization_routes,"create_handover_note",_create)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/partner/handover",
        json={
            "property_id":str(property_id),
            "note":"Call transport company before 6 PM.",
            "priority":"important",
        },
    )

    assert response.status_code==201
    assert captured["user_id"]==identity.user_id
    assert captured["property_id"]==str(property_id)
    assert captured["priority"]=="important"
