from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.analytics import routes as analytics_routes


def _identity():
    return SimpleNamespace(user_id=str(uuid4()),email="owner@example.com")


def _snapshot():
    org_id=str(uuid4())
    property_id=str(uuid4())
    return {
        "metrics":{
            "capacity_room_nights":100,
            "sold_room_nights":50,
            "held_room_nights":5,
            "remaining_room_nights":45,
            "stopped_room_nights":0,
            "booked_room_nights":50,
            "room_revenue_minor":50000000,
            "active_bookings":20,
            "cancelled_bookings":2,
            "no_show_bookings":1,
            "resolved_bookings":23,
            "review_count":4,
            "average_rating":4.5,
            "occupancy_percent":50.0,
            "adr_minor":1000000,
            "revpar_minor":500000,
            "cancellation_rate_percent":8.7,
            "avg_lead_days":7.5,
            "avg_length_of_stay":2.5,
        },
        "daily":[{
            "date":date(2026,10,1),
            "capacity_room_nights":10,
            "sold_room_nights":5,
            "held_room_nights":1,
            "remaining_room_nights":4,
            "booked_room_nights":5,
            "room_revenue_minor":5000000,
            "occupancy_percent":50.0,
        }],
        "room_types":[{
            "room_type_id":str(uuid4()),
            "room_type_name":"Deluxe",
            "property_id":property_id,
            "property_name":"Example Hotel",
            "capacity_room_nights":100,
            "sold_room_nights":50,
            "held_room_nights":5,
            "booked_room_nights":50,
            "room_revenue_minor":50000000,
            "occupancy_percent":50.0,
            "adr_minor":1000000,
            "revpar_minor":500000,
        }],
        "property_performance":[{
            "property_id":property_id,
            "property_name":"Example Hotel",
            "capacity_room_nights":100,
            "sold_room_nights":50,
            "booked_room_nights":50,
            "room_revenue_minor":50000000,
            "occupancy_percent":50.0,
            "adr_minor":1000000,
            "revpar_minor":500000,
        }],
        "guarantee_mix":[{"guarantee_type":"deposit","booking_count":10,"booking_value_minor":25000000}],
        "status_mix":[{"status":"confirmed","booking_count":20}],
        "organizations":[{"id":org_id,"name":"Example Group","role":"owner"}],
        "properties":[{"id":property_id,"name":"Example Hotel","organization_id":org_id}],
        "selected_organization_id":"",
        "selected_property_id":"",
    }


def test_partner_analytics_page_renders(monkeypatch):
    identity=_identity()
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(analytics_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(analytics_routes,"partner_performance_dashboard",lambda *args,**kwargs:_snapshot())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/analytics?start=2026-10-01&end=2026-10-31")
    assert response.status_code==200
    assert b"Analytics" in response.data
    assert b"50.0%" in response.data
    assert b"RevPAR" in response.data
    assert b"Example Hotel" in response.data


def test_partner_analytics_export_returns_daily_csv(monkeypatch):
    identity=_identity()
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(analytics_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(analytics_routes,"partner_performance_dashboard",lambda *args,**kwargs:_snapshot())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/analytics/export.csv?start=2026-10-01&end=2026-10-31")
    assert response.status_code==200
    assert response.mimetype=="text/csv"
    body=response.get_data(as_text=True)
    assert "Occupancy %" in body
    assert "2026-10-01" in body
    assert "50.0" in body


def test_analytics_filters_reject_reverse_dates():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/analytics?start=2026-10-31&end=2026-10-01"):
        with pytest.raises(RoyaError) as raised:
            analytics_routes._filters()
    assert raised.value.code=="VALIDATION_ERROR"


def test_analytics_filters_reject_overlong_range():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/analytics?start=2025-01-01&end=2026-10-01"):
        with pytest.raises(RoyaError) as raised:
            analytics_routes._filters()
    assert raised.value.code=="VALIDATION_ERROR"
