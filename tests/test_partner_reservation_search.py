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
