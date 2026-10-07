from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.reservations import routes as reservation_routes
from roya.reservations import service as reservation_service
from roya.reservations.service import ReservationService


class _Rows:
    def __init__(self,rows):
        self.rows=rows

    def fetchall(self):
        return self.rows


def test_partner_search_is_membership_and_property_scoped(monkeypatch):
    captured={}
    class _Connection:
        def execute(self,sql,params):
            captured["sql"]=sql
            captured["params"]=params
            return _Rows([{
                "id":"reservation-1",
                "reference":"RYA-SEARCH1",
                "guest_name":"Ada Guest",
                "property_name":"Example Hotel",
                "member_role":"reservations",
            }])

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(reservation_service,"db_connection",lambda:_connection())
    rows=ReservationService().search_for_partner(
        "user-1",
        "Ada",
        property_id="property-1",
        limit=20,
    )

    assert rows[0]["reference"]=="RYA-SEARCH1"
    assert "om.user_id=%s" in captured["sql"]
    assert "om.status='active'" in captured["sql"]
    assert "r.property_id::text=%s" in captured["sql"]
    assert "r.guest_phone" in captured["sql"]
    assert "srt.name ilike %s" in captured["sql"]
    assert captured["params"][0:2]==("user-1","property-1")
    assert captured["params"][-1]==20


def test_partner_search_rejects_invalid_limit():
    with pytest.raises(RoyaError) as exc:
        ReservationService().search_for_partner("user-1","Ada",limit="many")
    assert exc.value.code=="VALIDATION_ERROR"


def test_partner_search_api_forwards_query_and_property(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="desk@example.com")
    captured={}

    def fake_search(user_id,query,property_id=None,limit=20):
        captured.update({
            "user_id":user_id,
            "query":query,
            "property_id":property_id,
            "limit":limit,
        })
        return [{
            "id":str(uuid4()),
            "reference":"RYA-API1",
            "guest_name":"Ada Guest",
            "property_name":"Example Hotel",
            "member_role":"reservations",
        }]

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes.service,"search_for_partner",fake_search)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        "/api/v1/partner/reservations/search?q=Ada&property_id=property-1&limit=12"
    )

    assert response.status_code==200
    assert response.get_json()["data"][0]["reference"]=="RYA-API1"
    assert captured["user_id"]==identity.user_id
    assert captured["query"]=="Ada"
    assert captured["property_id"]=="property-1"
    assert captured["limit"]=="12"


def test_front_desk_search_renders_actionable_results():
    property_id=str(uuid4())
    snapshot={
        "organizations":[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
        "properties":[{"id":property_id,"name":"Example Hotel","organization_id":str(uuid4())}],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel"},
        "summary":{},
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
    results=[
        {
            "id":str(uuid4()),
            "reference":"RYA-PENDING",
            "guest_name":"Ada Guest",
            "guest_email":"ada@example.com",
            "guest_phone":"08012345678",
            "property_name":"Example Hotel",
            "room_type_names":"Deluxe Room",
            "check_in":"2026-10-07",
            "check_out":"2026-10-09",
            "status":"pending_confirmation",
            "payment_status":"unpaid",
            "currency":"NGN",
            "total_price_minor":4500000,
            "member_role":"reservations",
        },
        {
            "id":str(uuid4()),
            "reference":"RYA-CONFIRMED",
            "guest_name":"Ben Guest",
            "guest_email":"ben@example.com",
            "guest_phone":None,
            "property_name":"Example Hotel",
            "room_type_names":"Standard Room",
            "check_in":"2026-10-07",
            "check_out":"2026-10-08",
            "status":"confirmed",
            "payment_status":"paid",
            "currency":"NGN",
            "total_price_minor":2500000,
            "member_role":"owner",
        },
    ]

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner?front_desk_q=Ada"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            properties=[],
            pending_reservations=[],
            partner_reservations=[],
            partner_refunds=[],
            front_desk_query="Ada",
            front_desk_results=results,
            team_members=[],
            pending_invites=[],
            manageable_organizations=[],
            finance_organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            hotel_operations=snapshot,
        )

    assert "Find a guest or reservation" in html
    assert "RYA-PENDING" in html
    assert "08012345678" in html
    assert "Deluxe Room" in html
    assert 'data-reservation-decision="approve"' in html
    assert 'data-reservation-status="checked_in"' in html
    assert 'name="property_id"' in html


class _Result:
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


def test_partner_reservation_workspace_is_membership_scoped(monkeypatch):
    captured=[]
    reservation_id=str(uuid4())

    class _Connection:
        def execute(self,sql,params):
            captured.append((sql,params))
            if "from reservations r" in sql and "organization_members om" in sql:
                return _Result(row={
                    "id":reservation_id,
                    "reference":"RYA-WORK1",
                    "property_id":"property-1",
                    "organization_id":"org-1",
                    "guest_name":"Ada Guest",
                    "guest_email":"ada@example.com",
                    "guest_phone":"08012345678",
                    "adults":2,
                    "children":0,
                    "check_in":"2026-10-07",
                    "check_out":"2026-10-09",
                    "nights":2,
                    "status":"confirmed",
                    "payment_status":"paid",
                    "currency":"NGN",
                    "total_price_minor":4500000,
                    "amount_paid_minor":4500000,
                    "source_channel":"direct_booking",
                    "property_name":"Example Hotel",
                    "property_city":"Makurdi",
                    "property_state":"Benue",
                    "check_in_time":"14:00",
                    "check_out_time":"11:00",
                    "organization_name":"Example Group",
                    "member_role":"reservations",
                })
            return _Result(rows=[])

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(reservation_service,"db_connection",lambda:_connection())
    workspace=ReservationService().get_for_partner(reservation_id,"user-1")

    assert workspace["reservation"]["reference"]=="RYA-WORK1"
    first_sql,first_params=captured[0]
    assert "om.user_id=%s" in first_sql
    assert "om.status='active'" in first_sql
    assert first_params==(reservation_id,"user-1")


def test_partner_reservation_workspace_page_renders_primary_action(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="desk@example.com")
    reservation_id=uuid4()
    workspace={
        "reservation":{
            "id":str(reservation_id),
            "reference":"RYA-WORK2",
            "property_id":str(uuid4()),
            "guest_name":"Ada Guest",
            "guest_email":"ada@example.com",
            "guest_phone":"08012345678",
            "adults":2,
            "children":0,
            "property_name":"Example Hotel",
            "check_in":"2026-10-07",
            "check_out":"2026-10-09",
            "nights":2,
            "check_in_time":"14:00",
            "check_out_time":"11:00",
            "status":"confirmed",
            "payment_status":"paid",
            "currency":"NGN",
            "total_price_minor":4500000,
            "amount_paid_minor":4500000,
            "source_channel":"direct_booking",
            "member_role":"reservations",
        },
        "items":[{
            "id":str(uuid4()),
            "quantity":1,
            "unit_price_minor":2250000,
            "total_price_minor":4500000,
            "room_type_name":"Deluxe Room",
            "rate_plan_name":"Standard",
            "guarantee_type":"pay_now",
        }],
        "transactions":[],
        "refunds":[],
        "audit":[],
    }

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes.service,"get_for_partner",lambda reservation_id,user_id:workspace)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(f"/partner/reservations/{reservation_id}")

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "RYA-WORK2" in html
    assert "Deluxe Room" in html
    assert "Check in guest" in html
    assert 'data-reservation-status="checked_in"' in html
    assert "Email guest" in html


def test_hotel_navigation_uses_task_language():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/"):
        from flask import session
        session["sid"]="session-1"
        session["account_type"]="hotel"
        session["can_view_hotel_reports"]=True
        html=render_template("base.html")

    for label in ("Home","Reservations","Rooms","Guests","Reports","Settings"):
        assert f">{label}<" in html
    assert ">Dashboard<" not in html


def test_hotel_navigation_hides_reports_for_non_finance_roles():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/"):
        from flask import session
        session["sid"]="session-1"
        session["account_type"]="hotel"
        session["can_view_hotel_reports"]=False
        html=render_template("base.html")

    assert ">Reports<" not in html


def test_partner_reservation_workspace_filters_by_tab_property_and_query(monkeypatch):
    property_id=str(uuid4())
    captured=[]

    class _Connection:
        def execute(self,sql,params):
            captured.append((sql,params))
            if "from organization_members" in sql and "select 1" in sql:
                return _Result(row={"?column?":1})
            if "select distinct p.id,p.name,p.city" in sql:
                return _Result(rows=[{"id":property_id,"name":"Example Hotel","city":"Makurdi"}])
            if "count(*) filter" in sql:
                return _Result(row={
                    "today":2,
                    "upcoming":3,
                    "pending":1,
                    "in_house":1,
                    "completed":8,
                })
            if "string_agg(distinct rt.name" in sql:
                return _Result(rows=[{
                    "id":str(uuid4()),
                    "reference":"RYA-FILTER1",
                    "property_id":property_id,
                    "guest_name":"Ada Guest",
                    "guest_email":"ada@example.com",
                    "guest_phone":"08012345678",
                    "check_in":"2026-10-08",
                    "check_out":"2026-10-10",
                    "nights":2,
                    "total_price_minor":4000000,
                    "amount_paid_minor":4000000,
                    "currency":"NGN",
                    "status":"confirmed",
                    "payment_status":"paid",
                    "guarantee_type":"pay_now",
                    "source_channel":"direct_booking",
                    "expires_at":None,
                    "created_at":"2026-10-07",
                    "property_name":"Example Hotel",
                    "member_role":"reservations",
                    "room_type_names":"Deluxe Room",
                }])
            raise AssertionError(sql)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(reservation_service,"db_connection",lambda:_connection())
    workspace=ReservationService().workspace_for_partner(
        "user-1",
        tab="upcoming",
        property_id=property_id,
        query="Ada",
        limit=25,
    )

    assert workspace["tab"]=="upcoming"
    assert workspace["selected_property_id"]==property_id
    assert workspace["counts"]["upcoming"]==3
    assert workspace["reservations"][0]["reference"]=="RYA-FILTER1"

    list_sql,list_params=captured[-1]
    assert "r.status='confirmed'" in list_sql
    assert "r.check_in>current_date" in list_sql
    assert "r.property_id=%s" in list_sql
    assert "r.guest_name ilike %s" in list_sql
    assert list_params[0:2]==("user-1",property_id)
    assert list_params[-1]==25


def test_partner_reservation_workspace_rejects_unknown_tab():
    with pytest.raises(RoyaError) as exc:
        ReservationService().workspace_for_partner("user-1",tab="mystery")
    assert exc.value.code=="VALIDATION_ERROR"


def test_partner_reservation_workspace_requires_membership(monkeypatch):
    class _Connection:
        def execute(self,sql,params):
            return _Result(row=None)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(reservation_service,"db_connection",lambda:_connection())
    with pytest.raises(RoyaError) as exc:
        ReservationService().workspace_for_partner("user-1")
    assert exc.value.code=="FORBIDDEN"


def test_partner_reservations_page_renders_tabs_and_actions(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="desk@example.com")
    property_id=str(uuid4())
    reservation_id=str(uuid4())
    workspace={
        "tab":"today",
        "query":"",
        "properties":[{"id":property_id,"name":"Example Hotel","city":"Makurdi"}],
        "selected_property_id":property_id,
        "selected_property":{"id":property_id,"name":"Example Hotel","city":"Makurdi"},
        "counts":{"today":1,"upcoming":2,"pending":1,"in_house":1,"completed":5},
        "reservations":[{
            "id":reservation_id,
            "reference":"RYA-TODAY1",
            "property_id":property_id,
            "guest_name":"Ada Guest",
            "guest_email":"ada@example.com",
            "guest_phone":"08012345678",
            "check_in":"2026-10-07",
            "check_out":"2026-10-09",
            "nights":2,
            "total_price_minor":4500000,
            "amount_paid_minor":4500000,
            "currency":"NGN",
            "status":"confirmed",
            "payment_status":"paid",
            "guarantee_type":"pay_now",
            "source_channel":"direct_booking",
            "expires_at":None,
            "created_at":"2026-10-06",
            "property_name":"Example Hotel",
            "member_role":"reservations",
            "room_type_names":"Deluxe Room",
        }],
    }

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes.service,"workspace_for_partner",lambda *args,**kwargs:workspace)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(f"/partner/reservations?tab=today&property_id={property_id}")

    assert response.status_code==200
    html=response.get_data(as_text=True)
    for label in ("Today","Upcoming","Pending","In-house","Completed"):
        assert label in html
    assert "RYA-TODAY1" in html
    assert "Deluxe Room" in html
    assert 'data-reservation-status="checked_in"' in html
    assert f'/partner/reservations/{reservation_id}' in html


def test_hotel_navigation_links_to_dedicated_reservations_workspace():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/"):
        from flask import session
        session["sid"]="session-1"
        session["account_type"]="hotel"
        html=render_template("base.html")

    assert 'href="/partner/reservations">Reservations</a>' in html
    assert 'href="/partner#recent-reservations">Reservations</a>' not in html
