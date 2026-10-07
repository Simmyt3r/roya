from datetime import date,timedelta
from types import SimpleNamespace

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.reservations import routes as reservation_routes


def _workspace():
    check_in=date.today()+timedelta(days=3)
    return {
        "reservation":{
            "id":"50000000-0000-4000-8000-000000000001",
            "reference":"RYA-FRONT123",
            "property_id":"10000000-0000-4000-8000-000000000001",
            "property_name":"Example Hotel",
            "property_address":"1 Example Road",
            "property_city":"Makurdi",
            "property_state":"Benue",
            "property_country":"Nigeria",
            "property_phone":"08030000000",
            "property_email":"stay@example.com",
            "organization_name":"Example Group",
            "guest_name":"Ada Guest",
            "guest_email":"ada@example.com",
            "guest_phone":"08012345678",
            "adults":2,
            "children":1,
            "check_in":check_in,
            "check_out":check_in+timedelta(days=2),
            "nights":2,
            "check_in_time":"14:00",
            "check_out_time":"11:00",
            "status":"confirmed",
            "payment_status":"partially_paid",
            "currency":"NGN",
            "total_price_minor":5000000,
            "amount_paid_minor":3000000,
            "amount_refunded_minor":500000,
            "source_channel":"front_desk",
            "member_role":"reservations",
        },
        "items":[{
            "id":"80000000-0000-4000-8000-000000000001",
            "room_type_id":"30000000-0000-4000-8000-000000000001",
            "rate_plan_id":"40000000-0000-4000-8000-000000000001",
            "quantity":1,
            "unit_price_minor":2500000,
            "total_price_minor":5000000,
            "room_type_name":"Deluxe",
            "rate_plan_name":"Standard",
            "guarantee_type":"pay_at_property",
        }],
        "transactions":[],
        "refunds":[],
        "audit":[],
        "assigned_rooms":[],
        "room_readiness":{"tracked":False,"ready":True,"items":[]},
    }


def test_partner_confirmation_route_uses_member_scoped_workspace(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="desk@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _workspace_for_partner(reservation_id,user_id):
        captured["reservation_id"]=reservation_id
        captured["user_id"]=user_id
        return _workspace()

    monkeypatch.setattr(
        reservation_routes.service,
        "get_for_partner",
        _workspace_for_partner,
    )

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        "/partner/reservations/50000000-0000-4000-8000-000000000001/confirmation"
    )

    assert response.status_code==200
    assert captured["reservation_id"]=="50000000-0000-4000-8000-000000000001"
    assert captured["user_id"]==identity.user_id


def test_confirmation_renders_live_stay_and_payment_summary():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context(
        "/partner/reservations/50000000-0000-4000-8000-000000000001/confirmation"
    ):
        html=render_template(
            "partner/reservation_confirmation.html",
            workspace=_workspace(),
        )

    assert "Booking confirmation" in html
    assert "RYA-FRONT123" in html
    assert "Example Hotel" in html
    assert "1 Example Road" in html
    assert "08030000000" in html
    assert "Ada Guest" in html
    assert "Deluxe" in html
    assert "Standard" in html
    assert "NGN 50000.00" in html
    assert "NGN 30000.00" in html
    assert "NGN 5000.00" in html
    assert "NGN 25000.00" in html
    assert 'data-copy-confirmation' in html
    assert 'data-share-confirmation' in html
    assert 'data-print-confirmation' in html
    assert 'data-confirmation-text' in html


def test_reservation_workspace_links_guest_confirmation():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context(
        "/partner/reservations/50000000-0000-4000-8000-000000000001"
    ):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(),
        )

    assert "Guest confirmation" in html
    assert (
        "/partner/reservations/50000000-0000-4000-8000-000000000001/confirmation"
        in html
    )
