from types import SimpleNamespace
from uuid import uuid4

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.organizations import routes as organization_routes
from roya.organizations.operations_service import build_daily_actions, hotel_operations_snapshot


def _identity():
    return SimpleNamespace(user_id=str(uuid4()),email="ops@example.com")


def _snapshot():
    property_id=str(uuid4())
    return {
        "organizations":[{"id":str(uuid4()),"name":"Example Group","role":"manager"}],
        "properties":[{"id":property_id,"name":"Example Hotel","organization_id":str(uuid4())}],
        "selected_property_id":None,
        "selected_property":None,
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
    captured={}
    def fake_snapshot(user_id,horizon_days=7,property_id=None):
        captured["property_id"]=property_id
        return {**snapshot,"horizon_days":int(horizon_days),"selected_property_id":property_id}
    monkeypatch.setattr(
        organization_routes,
        "hotel_operations_snapshot",
        fake_snapshot,
    )

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    property_id=snapshot["properties"][0]["id"]
    response=app.test_client().get(f"/api/v1/partner/operations/summary?days=14&property_id={property_id}")
    assert response.status_code==200
    data=response.get_json()["data"]
    assert data["summary"]["arrivals_today"]==2
    assert data["summary"]["in_house"]==4
    assert data["horizon_days"]==14
    assert data["selected_property_id"]==property_id
    assert captured["property_id"]==property_id


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


def test_operations_horizon_invalid_value_falls_back_to_seven(monkeypatch):
    class _Conn:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,*args,**kwargs):
            class _Result:
                def fetchall(self): return []
            return _Result()
    monkeypatch.setattr("roya.organizations.operations_service.db_connection",lambda:_Conn())
    snapshot=hotel_operations_snapshot(str(uuid4()),horizon_days="nonsense")
    assert snapshot["horizon_days"]==7


def test_partner_dashboard_operations_horizon_selector_renders():
    snapshot=_snapshot()
    snapshot["horizon_days"]=14
    snapshot["selected_property_id"]=snapshot["properties"][0]["id"]
    snapshot["selected_property"]=snapshot["properties"][0]
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context(f"/partner?days=14&property_id={snapshot['selected_property_id']}"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            properties=[],pending_reservations=[],partner_reservations=[],partner_refunds=[],
            team_members=[],pending_invites=[],manageable_organizations=[],
            finance_organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            hotel_operations=snapshot,
        )
    assert 'name="days"' in html
    assert 'name="property_id"' in html
    assert '>14 days</option>' in html
    assert "Example Hotel" in html
    assert "Showing Example Hotel only." in html
