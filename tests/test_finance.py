from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.admin import service as admin_service
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.finance import routes as finance_routes


def _sample_snapshot():
    org_id=str(uuid4())
    property_id=str(uuid4())
    reservation_id=str(uuid4())
    return {
        "metrics":{
            "booking_count":1,
            "gross_booking_value_minor":1000000,
            "collected_minor":400000,
            "refunded_minor":100000,
            "net_collected_minor":300000,
            "deposits_collected_minor":400000,
            "outstanding_balance_minor":600000,
            "due_at_property_minor":0,
            "payment_attention_count":1,
            "average_booking_value_minor":1000000,
            "platform_fee_minor":0,
            "platform_fee_configured":False,
            "settlement_execution_enabled":False,
        },
        "organizations":[{"id":org_id,"name":"Example Group","role":"finance"}],
        "properties":[{"id":property_id,"name":"Example Hotel","organization_id":org_id}],
        "selected_organization_id":"",
        "selected_property_id":"",
        "ledger":[{
            "id":reservation_id,
            "reference":"RYA-FINANCE",
            "created_at":"2026-10-06",
            "check_in":"2026-10-10",
            "check_out":"2026-10-12",
            "guest_name":"Guest Example",
            "guest_email":"guest@example.com",
            "status":"confirmed",
            "payment_status":"partially_paid",
            "guarantee_type":"deposit",
            "currency":"NGN",
            "total_price_minor":1000000,
            "amount_due_minor":400000,
            "amount_paid_minor":400000,
            "organization_id":org_id,
            "organization_name":"Example Group",
            "property_id":property_id,
            "property_name":"Example Hotel",
            "refunded_minor":100000,
            "net_collected_minor":300000,
            "outstanding_minor":600000,
            "latest_provider":"",
            "latest_provider_reference":"",
            "latest_transaction_status":"",
        }],
        "activity":[],
        "refund_queue":[],
        "top_hotels":[{
            "id":property_id,
            "name":"Example Hotel",
            "organization_name":"Example Group",
            "booking_count":1,
            "gross_minor":1000000,
            "collected_minor":400000,
        }],
    }


def _identity():
    return SimpleNamespace(user_id=str(uuid4()),email="finance@example.com")


def test_csv_cells_neutralize_spreadsheet_formulas():
    assert finance_routes._csv_cell("=HYPERLINK(\"https://evil.test\")").startswith("'=")
    assert finance_routes._csv_cell("+123").startswith("'+")
    assert finance_routes._csv_cell("Normal guest")=="Normal guest"


def test_partner_finance_page_renders_for_authorized_hotel_member(monkeypatch):
    identity=_identity()
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(finance_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(finance_routes,"partner_finance_dashboard",lambda *args,**kwargs:_sample_snapshot())

    class _Refunds:
        def list_for_partner(self,*args,**kwargs):
            return []

    monkeypatch.setattr(finance_routes,"PaymentService",lambda:_Refunds())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/finance?start=2026-10-01&end=2026-10-31")
    assert response.status_code==200
    assert b"Finance center" in response.data
    assert b"RYA-FINANCE" in response.data
    assert b"Refunds" in response.data
    assert b"Settlement execution is not enabled yet" in response.data


def test_partner_finance_export_returns_csv(monkeypatch):
    identity=_identity()
    snapshot=_sample_snapshot()
    snapshot["ledger"][0]["guest_name"]="=2+2"
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(finance_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(finance_routes,"partner_finance_dashboard",lambda *args,**kwargs:snapshot)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/finance/export.csv?start=2026-10-01&end=2026-10-31")
    assert response.status_code==200
    assert response.mimetype=="text/csv"
    assert "attachment;" in response.headers["Content-Disposition"]
    assert "'=2+2" in response.get_data(as_text=True)


def test_finance_filters_reject_reverse_dates():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/finance?start=2026-10-31&end=2026-10-01"):
        with pytest.raises(RoyaError) as raised:
            finance_routes._filters()
    assert raised.value.code=="VALIDATION_ERROR"


@contextmanager
def _platform_lookup(role):
    class Connection:
        def execute(self,*_args,**_kwargs):
            return self

        def fetchone(self):
            return {"platform_role":role,"status":"active"}

    yield Connection()


def _platform_client(monkeypatch,role):
    identity=_identity()
    monkeypatch.setattr(admin_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(admin_service,"db_connection",lambda:_platform_lookup(role))
    monkeypatch.setattr(finance_routes,"platform_finance_dashboard",lambda *args,**kwargs:_sample_snapshot())
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    return app.test_client()


def test_platform_finance_role_can_open_finance_console(monkeypatch):
    client=_platform_client(monkeypatch,"finance")
    response=client.get("/admin/finance?start=2026-10-01&end=2026-10-31")
    assert response.status_code==200
    assert b"Finance console" in response.data
    assert b"Example Hotel" in response.data


def test_platform_support_role_cannot_open_finance_console(monkeypatch):
    client=_platform_client(monkeypatch,"support")
    response=client.get("/admin/finance?start=2026-10-01&end=2026-10-31")
    assert response.status_code==403


def test_platform_admin_can_open_finance_console(monkeypatch):
    client=_platform_client(monkeypatch,"admin")
    response=client.get("/admin/finance?start=2026-10-01&end=2026-10-31")
    assert response.status_code==200


def test_partner_finance_refund_focus_renders_action_queue(monkeypatch):
    identity=_identity()
    snapshot=_sample_snapshot()
    property_id=snapshot["properties"][0]["id"]
    refund_id=str(uuid4())
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(finance_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(finance_routes,"partner_finance_dashboard",lambda *args,**kwargs:snapshot)

    class _Refunds:
        def list_for_partner(self,user_id,organization_id=None,property_id=None,limit=50):
            captured.update({
                "user_id":user_id,
                "organization_id":organization_id,
                "property_id":property_id,
                "limit":limit,
            })
            return [{
                "id":refund_id,
                "reservation_id":str(uuid4()),
                "amount_minor":350000,
                "currency":"NGN",
                "status":"requested",
                "reason":"Guest cancellation",
                "created_at":"2026-10-07",
                "reservation_reference":"RYA-REFUND1",
                "guest_name":"Ada Guest",
                "guest_email":"ada@example.com",
                "property_name":"Example Hotel",
                "organization_name":"Example Group",
                "member_role":"finance",
            }]

    monkeypatch.setattr(finance_routes,"PaymentService",lambda:_Refunds())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        f"/partner/finance?start=2026-10-01&end=2026-10-31"
        f"&property_id={property_id}&focus=refunds"
    )

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert 'id="refunds"' in html
    assert "is-focused" in html
    assert "RYA-REFUND1" in html
    assert "Ada Guest" in html
    assert "NGN 3500.00" in html
    assert f'data-refund-process="{refund_id}"' in html
    assert captured["property_id"]==property_id
    assert captured["limit"]==100
