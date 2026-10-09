from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.rooms import routes as room_routes


class _Result:
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _HousekeepingConnection:
    def __init__(self,properties=None,rooms=None):
        self.properties=properties if properties is not None else [{
            "id":"10000000-0000-4000-8000-000000000001",
            "name":"Example Hotel",
            "city":"Makurdi",
            "state":"Benue",
            "organization_name":"Example Group",
            "member_role":"staff",
        }]
        self.rooms=rooms if rooms is not None else [
            {
                "id":"90000000-0000-4000-8000-000000000001",
                "room_type_id":"30000000-0000-4000-8000-000000000001",
                "room_number":"101",
                "floor":"1",
                "status":"active",
                "housekeeping_status":"dirty",
                "current_reservation_id":None,
                "housekeeping_updated_at":"2026-10-09 12:00",
                "room_type_name":"Deluxe",
                "total_inventory":3,
                "property_id":"10000000-0000-4000-8000-000000000001",
                "property_name":"Example Hotel",
                "member_role":"staff",
                "current_reservation_reference":None,
                "current_guest_name":None,
                "current_check_out":None,
                "departure_due_today":False,
                "arrivals_today":2,
                "arrivals_tomorrow":1,
                "ready_for_type":1,
            },
            {
                "id":"90000000-0000-4000-8000-000000000002",
                "room_type_id":"30000000-0000-4000-8000-000000000001",
                "room_number":"102",
                "floor":"1",
                "status":"active",
                "housekeeping_status":"cleaning",
                "current_reservation_id":None,
                "housekeeping_updated_at":"2026-10-09 12:05",
                "room_type_name":"Deluxe",
                "total_inventory":3,
                "property_id":"10000000-0000-4000-8000-000000000001",
                "property_name":"Example Hotel",
                "member_role":"staff",
                "current_reservation_reference":None,
                "current_guest_name":None,
                "current_check_out":None,
                "departure_due_today":False,
                "arrivals_today":2,
                "arrivals_tomorrow":1,
                "ready_for_type":1,
            },
            {
                "id":"90000000-0000-4000-8000-000000000003",
                "room_type_id":"30000000-0000-4000-8000-000000000001",
                "room_number":"103",
                "floor":"1",
                "status":"active",
                "housekeeping_status":"ready",
                "current_reservation_id":None,
                "housekeeping_updated_at":"2026-10-09 12:10",
                "room_type_name":"Deluxe",
                "total_inventory":3,
                "property_id":"10000000-0000-4000-8000-000000000001",
                "property_name":"Example Hotel",
                "member_role":"staff",
                "current_reservation_reference":None,
                "current_guest_name":None,
                "current_check_out":None,
                "departure_due_today":False,
                "arrivals_today":2,
                "arrivals_tomorrow":1,
                "ready_for_type":1,
            },
            {
                "id":"90000000-0000-4000-8000-000000000004",
                "room_type_id":"30000000-0000-4000-8000-000000000002",
                "room_number":"201",
                "floor":"2",
                "status":"active",
                "housekeeping_status":"ready",
                "current_reservation_id":"50000000-0000-4000-8000-000000000001",
                "housekeeping_updated_at":"2026-10-09 11:00",
                "room_type_name":"Executive",
                "total_inventory":2,
                "property_id":"10000000-0000-4000-8000-000000000001",
                "property_name":"Example Hotel",
                "member_role":"staff",
                "current_reservation_reference":"RYA-CHECKOUT",
                "current_guest_name":"Ada Guest",
                "current_check_out":"2026-10-09",
                "departure_due_today":True,
                "arrivals_today":0,
                "arrivals_tomorrow":1,
                "ready_for_type":1,
            },
        ]

    def execute(self,sql,params=None):
        if "from properties p" in sql and "organization_name" in sql:
            return _Result(rows=self.properties)
        if "from physical_rooms pr" in sql and "arrivals_today" in sql:
            return _Result(rows=self.rooms)
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def test_housekeeping_workspace_groups_and_prioritizes_arrivals(monkeypatch):
    connection=_HousekeepingConnection()
    monkeypatch.setattr(room_routes,"db_connection",lambda:_db(connection)())

    workspace=room_routes.housekeeping_workspace(
        "60000000-0000-4000-8000-000000000001"
    )

    assert workspace["summary"]=={
        "dirty":1,
        "cleaning":1,
        "ready":1,
        "occupied":1,
        "out_of_service":0,
        "arrival_priority":2,
    }
    assert workspace["groups"]["dirty"][0]["arrival_pressure"] is True
    assert workspace["groups"]["cleaning"][0]["arrival_pressure"] is True
    assert workspace["groups"]["occupied"][0]["departure_due_today"] is True


def test_housekeeping_workspace_rejects_inaccessible_property(monkeypatch):
    connection=_HousekeepingConnection()
    monkeypatch.setattr(room_routes,"db_connection",lambda:_db(connection)())

    try:
        room_routes.housekeeping_workspace(
            "60000000-0000-4000-8000-000000000001",
            property_id="10000000-0000-4000-8000-000000000099",
        )
        assert False,"expected property scope rejection"
    except Exception as exc:
        assert getattr(exc,"code",None)=="NOT_FOUND"
        assert getattr(exc,"status_code",None)==404


def test_housekeeping_page_renders_touch_actions_and_priority(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="housekeeping@example.com",
    )
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(room_routes,"current_identity",lambda required=False:identity)
    workspace={
        "properties":[{
            "id":"10000000-0000-4000-8000-000000000001",
            "name":"Example Hotel",
            "city":"Makurdi",
            "state":"Benue",
            "organization_name":"Example Group",
            "member_role":"staff",
        }],
        "selected_property_id":None,
        "selected_property":None,
        "rooms":[{"id":"90000000-0000-4000-8000-000000000001"}],
        "groups":{
            "dirty":[{
                "id":"90000000-0000-4000-8000-000000000001",
                "room_number":"101",
                "property_name":"Example Hotel",
                "room_type_name":"Deluxe",
                "floor":"1",
                "display_status":"dirty",
                "arrival_pressure":True,
                "departure_due_today":False,
                "arrivals_today":2,
                "arrivals_tomorrow":0,
                "current_reservation_id":None,
            }],
            "cleaning":[],
            "ready":[],
            "occupied":[],
            "out_of_service":[],
        },
        "summary":{
            "dirty":1,
            "cleaning":0,
            "ready":0,
            "occupied":0,
            "out_of_service":0,
            "arrival_priority":1,
        },
    }
    monkeypatch.setattr(room_routes,"housekeeping_workspace",lambda *_args,**_kwargs:workspace)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/housekeeping")

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "Housekeeping" in html
    assert "Arrival priority" in html
    assert "Start cleaning" in html
    assert 'data-housekeeping-status="cleaning"' in html
    assert 'data-housekeeping-room=' in html


def test_housekeeping_empty_state_points_to_room_setup():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    workspace={
        "properties":[],
        "selected_property_id":None,
        "selected_property":None,
        "rooms":[],
        "groups":{"dirty":[],"cleaning":[],"ready":[],"occupied":[],"out_of_service":[]},
        "summary":{"dirty":0,"cleaning":0,"ready":0,"occupied":0,"out_of_service":0,"arrival_priority":0},
    }
    with app.test_request_context("/partner/housekeeping"):
        html=render_template("partner/housekeeping.html",workspace=workspace)

    assert "No physical rooms configured" in html
    assert "/partner/rooms?focus=readiness" in html


def test_hotel_nav_links_housekeeping():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/"):
        from flask import session
        session["sid"]="sid"
        session["account_type"]="hotel"
        html=render_template("base.html")

    assert 'href="/partner/housekeeping"' in html
