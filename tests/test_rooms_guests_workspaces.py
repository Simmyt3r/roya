from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.properties import routes as property_routes
from roya.reservations import routes as reservation_routes
from roya.reservations import service as reservation_service
from roya.reservations.service import ReservationService


class _Result:
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


def test_rooms_workspace_is_membership_scoped_and_property_filterable(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="rooms@example.com")
    property_id=str(uuid4())
    room_id=str(uuid4())
    captured=[]

    class _Connection:
        def execute(self,sql,params):
            captured.append((sql,params))
            if "p.verification_status" in sql and "room_type_count" in sql:
                return _Result(rows=[{
                    "id":property_id,
                    "name":"Example Hotel",
                    "city":"Makurdi",
                    "state":"Benue",
                    "verification_status":"verified",
                    "status":"active",
                    "organization_name":"Example Hotels",
                    "member_role":"owner",
                    "room_type_count":1,
                    "room_units":4,
                    "active_rate_count":1,
                    "sellable_room_type_count":1,
                }])
            if "from room_types rt" in sql and "lowest_rate_minor" in sql:
                return _Result(rows=[{
                    "id":room_id,
                    "property_id":property_id,
                    "name":"Deluxe King",
                    "capacity_adults":2,
                    "capacity_children":1,
                    "total_inventory":4,
                    "bed_configuration":"1 King Bed",
                    "status":"active",
                    "property_name":"Example Hotel",
                    "member_role":"owner",
                    "active_rate_count":1,
                    "lowest_rate_minor":2500000,
                    "currency":"NGN",
                    "days_loaded":30,
                    "min_available":2,
                    "max_inventory_date":"2026-11-06",
                    "cover_image":None,
                    "cover_alt":None,
                }])
            raise AssertionError(sql)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(property_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(property_routes,"account_type_for_user",lambda user_id:"hotel")
    monkeypatch.setattr(property_routes,"db_connection",lambda:_connection())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(f"/partner/rooms?property_id={property_id}")

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "Deluxe King" in html
    assert "NGN 25000.00" in html
    assert "30/30 loaded" in html
    assert "2 rooms" in html
    assert f"/partner/properties/{property_id}#rooms" in html

    room_sql,room_params=next(
        (sql,params) for sql,params in captured
        if "from room_types rt" in sql and "lowest_rate_minor" in sql
    )
    assert "om.user_id=%s" in room_sql
    assert "om.status='active'" in room_sql
    assert "and p.id=%s" in room_sql
    assert room_params==(identity.user_id,property_id)


def test_rooms_workspace_rejects_inaccessible_property(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="rooms@example.com")
    allowed_property=str(uuid4())

    class _Connection:
        def execute(self,sql,params):
            return _Result(rows=[{
                "id":allowed_property,
                "name":"Allowed Hotel",
                "city":"Makurdi",
                "state":"Benue",
                "verification_status":"verified",
                "status":"active",
                "organization_name":"Example Hotels",
                "member_role":"owner",
                "room_type_count":0,
                "room_units":0,
                "active_rate_count":0,
                "sellable_room_type_count":0,
            }])

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(property_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(property_routes,"account_type_for_user",lambda user_id:"hotel")
    monkeypatch.setattr(property_routes,"db_connection",lambda:_connection())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(f"/partner/rooms?property_id={uuid4()}")
    assert response.status_code==404


def test_guest_workspace_separates_in_house_and_arrivals(monkeypatch):
    property_id=str(uuid4())
    captured=[]

    class _Connection:
        def execute(self,sql,params):
            captured.append((sql,params))
            if "select 1" in sql and "from organization_members" in sql:
                return _Result(row={"ok":1})
            if "select distinct p.id,p.name,p.city" in sql:
                return _Result(rows=[{"id":property_id,"name":"Example Hotel","city":"Makurdi"}])
            if "r.status='checked_in'" in sql and "r.check_in=current_date" in sql:
                return _Result(rows=[
                    {
                        "id":str(uuid4()),
                        "reference":"RYA-INHOUSE",
                        "property_id":property_id,
                        "guest_name":"Ada Guest",
                        "guest_email":"ada@example.com",
                        "guest_phone":"08012345678",
                        "check_in":"2026-10-06",
                        "check_out":"2026-10-08",
                        "status":"checked_in",
                        "payment_status":"paid",
                        "currency":"NGN",
                        "total_price_minor":5000000,
                        "property_name":"Example Hotel",
                        "member_role":"reservations",
                        "room_type_names":"Deluxe King",
                    },
                    {
                        "id":str(uuid4()),
                        "reference":"RYA-ARRIVAL",
                        "property_id":property_id,
                        "guest_name":"Ben Guest",
                        "guest_email":"ben@example.com",
                        "guest_phone":"08098765432",
                        "check_in":"2026-10-07",
                        "check_out":"2026-10-09",
                        "status":"confirmed",
                        "payment_status":"unpaid",
                        "currency":"NGN",
                        "total_price_minor":4500000,
                        "property_name":"Example Hotel",
                        "member_role":"owner",
                        "room_type_names":"Standard Room",
                    },
                ])
            raise AssertionError(sql)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(reservation_service,"db_connection",lambda:_connection())
    workspace=ReservationService().guest_workspace_for_partner(
        "user-1",
        property_id=property_id,
    )

    assert workspace["selected_property_id"]==property_id
    assert workspace["in_house"][0]["reference"]=="RYA-INHOUSE"
    assert workspace["arrivals"][0]["reference"]=="RYA-ARRIVAL"

    active_sql,active_params=captured[-1]
    assert "om.user_id=%s" in active_sql
    assert "om.status='active'" in active_sql
    assert "r.property_id=%s" in active_sql
    assert active_params[0:2]==("user-1",property_id)


def test_guests_route_renders_active_front_desk_actions(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="desk@example.com")
    property_id=str(uuid4())
    reservation_id=str(uuid4())
    workspace={
        "query":"",
        "query_too_short":False,
        "properties":[{"id":property_id,"name":"Example Hotel","city":"Makurdi"}],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel","city":"Makurdi"},
        "in_house":[{
            "id":reservation_id,
            "reference":"RYA-INHOUSE",
            "property_id":property_id,
            "guest_name":"Ada Guest",
            "guest_email":"ada@example.com",
            "guest_phone":"08012345678",
            "check_in":"2026-10-06",
            "check_out":"2026-10-08",
            "status":"checked_in",
            "payment_status":"paid",
            "currency":"NGN",
            "total_price_minor":5000000,
            "property_name":"Example Hotel",
            "member_role":"reservations",
            "room_type_names":"Deluxe King",
        }],
        "arrivals":[],
        "results":[],
    }

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(
        reservation_routes.service,
        "guest_workspace_for_partner",
        lambda *args,**kwargs:workspace,
    )

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(f"/partner/guests?property_id={property_id}")

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "In-house" in html
    assert "Ada Guest" in html
    assert "Deluxe King" in html
    assert 'data-reservation-status="checked_out"' in html
    assert f"/partner/reservations/{reservation_id}" in html


def test_hotel_navigation_uses_rooms_and_guests_workspaces():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        from flask import session
        session["sid"]="session-1"
        session["account_type"]="hotel"
        html=render_template("base.html")

    assert 'href="/partner/rooms">Rooms</a>' in html
    assert 'href="/partner/guests">Guests</a>' in html
    assert 'href="/partner#properties">Rooms</a>' not in html
    assert 'href="/partner#front-desk-search">Guests</a>' not in html


def test_hotel_home_no_longer_duplicates_rooms_or_guest_search():
    property_id=str(uuid4())
    snapshot={
        "organizations":[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
        "properties":[{"id":property_id,"name":"Example Hotel","organization_id":str(uuid4())}],
        "selected_property_id":None,
        "selected_property":None,
        "summary":{
            "arrivals_today":0,
            "departures_today":0,
            "in_house":0,
            "pending_approvals":0,
            "overdue_arrivals":0,
            "overdue_departures":0,
            "active_next_24h":0,
            "refund_attention":0,
        },
        "arrivals":[],
        "departures":[],
        "overdue":[],
        "forecast":[],
        "low_inventory":[],
        "source_mix":[],
        "channel_errors":[],
        "tasks":[],
        "horizon_days":7,
    }

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            partner_refunds=[],
            hotel_operations=snapshot,
        )

    assert 'id="front-desk-search"' not in html
    assert 'id="properties"' not in html
    assert "Find a guest or reservation" not in html
    assert "Your hotels" not in html
    assert "Hotel operations" in html
