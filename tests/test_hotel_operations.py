from types import SimpleNamespace
from uuid import uuid4

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.organizations import routes as organization_routes
from roya.organizations.operations_service import build_daily_actions


def _identity():
    return SimpleNamespace(user_id=str(uuid4()),email="ops@example.com")


def _snapshot():
    return {
        "organizations":[{"id":str(uuid4()),"name":"Example Group","role":"manager"}],
        "summary":{
            "arrivals_today":2,
            "departures_today":1,
            "in_house":4,
            "pending_approvals":1,
            "overdue_arrivals":0,
            "overdue_departures":0,
            "active_next_24h":5,
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


def test_daily_actions_prioritize_operational_exceptions():
    tasks=build_daily_actions(
        {
            "pending_approvals":2,
            "overdue_arrivals":1,
            "overdue_departures":1,
            "arrivals_today":3,
            "departures_today":2,
            "refund_attention":1,
        },
        [{"room_type_name":"Suite"}],
        [{"channel":"direct_booking"}],
    )
    assert tasks[0]["priority"]=="critical"
    assert "overdue arrival" in tasks[0]["title"]
    assert tasks[1]["priority"]=="critical"
    assert "overdue departure" in tasks[1]["title"]
    assert any(task["href"]=="/partner#reservations" for task in tasks)
    assert any(task["href"]=="/partner/distribution" for task in tasks)


def test_daily_actions_empty_when_nothing_needs_attention():
    tasks=build_daily_actions(
        {
            "pending_approvals":0,
            "overdue_arrivals":0,
            "overdue_departures":0,
            "arrivals_today":0,
            "departures_today":0,
            "refund_attention":0,
        },
        [],
        [],
    )
    assert tasks==[]


def test_partner_operations_summary_api(monkeypatch):
    identity=_identity()
    snapshot=_snapshot()
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(organization_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(
        organization_routes,
        "hotel_operations_snapshot",
        lambda user_id:snapshot,
    )

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/api/v1/partner/operations/summary")
    assert response.status_code==200
    data=response.get_json()["data"]
    assert data["summary"]["arrivals_today"]==2
    assert data["summary"]["in_house"]==4
    assert data["horizon_days"]==7


def test_partner_dashboard_operations_section_renders():
    snapshot=_snapshot()
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            properties=[],
            pending_reservations=[],
            partner_reservations=[],
            partner_refunds=[],
            team_members=[],
            pending_invites=[],
            manageable_organizations=[],
            finance_organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            hotel_operations=snapshot,
        )
    assert "Hotel operations" in html
    assert "7-day occupancy" in html
    assert "Arrivals today" in html
    assert "Booking source" in html
