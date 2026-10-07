from types import SimpleNamespace
from uuid import uuid4

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.organizations import routes as organization_routes
from roya.organizations.operations_service import (
    build_daily_actions,
    hotel_operations_snapshot,
    normalize_horizon_days,
    scope_action_links,
    select_property_scope,
)


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



def test_operations_scope_helpers_normalize_and_validate_property():
    first={"id":str(uuid4()),"name":"First Hotel"}
    second={"id":str(uuid4()),"name":"Second Hotel"}
    assert normalize_horizon_days("nonsense")==7
    assert normalize_horizon_days(1)==3
    assert normalize_horizon_days(99)==14

    selected_id,selected=select_property_scope([first,second],second["id"])
    assert selected_id==second["id"]
    assert selected["name"]=="Second Hotel"

    invalid_id,invalid=select_property_scope([first,second],str(uuid4()))
    assert invalid_id is None
    assert invalid is None


def test_scope_action_links_preserves_selected_property_and_external_routes():
    property_id=str(uuid4())
    tasks=[
        {"href":"/partner#recent-reservations","title":"Stay"},
        {"href":"/partner/distribution","title":"Distribution"},
    ]
    scoped=scope_action_links(tasks,property_id,14)
    assert scoped[0]["href"]==f"/partner?property_id={property_id}&days=14#recent-reservations"
    assert scoped[1]["href"]=="/partner/distribution"
    assert tasks[0]["href"]=="/partner#recent-reservations"


def test_partner_dashboard_front_desk_actions_render():
    snapshot=_snapshot()
    property_name=snapshot["properties"][0]["name"]
    snapshot["arrivals"]=[{
        "id":str(uuid4()),
        "reference":"RYA-ARRIVE",
        "guest_name":"Ada Guest",
        "property_name":property_name,
        "payment_status":"paid",
        "source_channel":"direct_booking",
        "status":"confirmed",
        "member_role":"owner",
    }]
    snapshot["departures"]=[{
        "id":str(uuid4()),
        "reference":"RYA-LEAVE",
        "guest_name":"Ben Guest",
        "property_name":property_name,
        "payment_status":"paid",
        "check_out":"2026-10-07",
        "status":"checked_in",
        "member_role":"reservations",
    }]
    snapshot["overdue"]=[{
        "id":str(uuid4()),
        "reference":"RYA-LATE",
        "guest_name":"Chi Guest",
        "property_name":property_name,
        "payment_status":"paid",
        "check_in":"2026-10-05",
        "check_out":"2026-10-06",
        "status":"confirmed",
        "member_role":"manager",
        "overdue_type":"arrival",
    }]
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            properties=[],pending_reservations=[],partner_reservations=[],partner_refunds=[],
            team_members=[],pending_invites=[],manageable_organizations=[],
            finance_organizations=[{"id":str(uuid4()),"name":"Example Group","role":"owner"}],
            hotel_operations=snapshot,
        )
    assert html.count('data-reservation-status="checked_in"')>=2
    assert 'data-reservation-status="no_show"' in html
    assert 'data-reservation-status="checked_out"' in html
    assert "RYA-ARRIVE" in html
    assert "RYA-LEAVE" in html
    assert "RYA-LATE" in html



def test_front_desk_actions_hidden_for_read_only_role():
    snapshot=_snapshot()
    snapshot["arrivals"]=[{
        "id":str(uuid4()),
        "reference":"RYA-READONLY",
        "guest_name":"Finance User View",
        "property_name":"Example Hotel",
        "payment_status":"paid",
        "source_channel":"direct_booking",
        "status":"confirmed",
        "member_role":"finance",
    }]
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        html=render_template(
            "partner/dashboard.html",
            organizations=[{"id":str(uuid4()),"name":"Example Group","role":"finance"}],
            properties=[],pending_reservations=[],partner_reservations=[],partner_refunds=[],
            team_members=[],pending_invites=[],manageable_organizations=[],
            finance_organizations=[{"id":str(uuid4()),"name":"Example Group","role":"finance"}],
            hotel_operations=snapshot,
        )
    assert "RYA-READONLY" in html
    assert 'data-reservation-status="checked_in"' not in html
