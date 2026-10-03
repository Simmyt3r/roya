from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from roya import create_app
from roya.admin import routes as admin_routes
from roya.admin import service as admin_service


@contextmanager
def _admin_lookup(role="admin"):
    class Connection:
        def execute(self,*_args,**_kwargs):
            return self

        def fetchone(self):
            return {"platform_role":role,"status":"active"}

    yield Connection()


def _client(monkeypatch,role="admin"):
    monkeypatch.setattr(
        admin_service,
        "current_identity",
        lambda required=False:SimpleNamespace(user_id=str(uuid4())),
    )
    monkeypatch.setattr(admin_service,"db_connection",lambda:_admin_lookup(role))
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    return app.test_client()


def test_admin_operations_snapshot_endpoint(monkeypatch):
    client=_client(monkeypatch)
    monkeypatch.setattr(admin_routes,"operations_snapshot",lambda:{
        "counts":{"stuck_payments":0},
        "issues":[],
        "critical":0,
        "warning":0,
        "healthy":True,
    })
    response=client.get("/api/v1/admin/operations")
    assert response.status_code==200
    assert response.json["data"]["healthy"] is True


def test_non_admin_cannot_open_reservation_case_search(monkeypatch):
    client=_client(monkeypatch,role="user")
    response=client.get("/admin/reservations")
    assert response.status_code==403


def test_admin_can_search_reservation_cases(monkeypatch):
    client=_client(monkeypatch)
    reservation_id=str(uuid4())
    monkeypatch.setattr(admin_routes,"search_reservation_cases",lambda query:[{
        "id":reservation_id,
        "reference":"RYA-CASE123",
        "guest_name":"Guest Example",
        "guest_email":"guest@example.com",
        "check_in":"2026-10-10",
        "check_out":"2026-10-12",
        "status":"confirmed",
        "payment_status":"paid",
        "total_price_minor":5000000,
        "amount_paid_minor":5000000,
        "currency":"NGN",
        "property_name":"Example Hotel",
        "created_at":"2026-10-03",
    }])
    response=client.get("/admin/reservations?q=RYA-CASE123")
    assert response.status_code==200
    assert b"RYA-CASE123" in response.data
    assert b"Example Hotel" in response.data


def test_admin_reservation_case_renders_operational_history(monkeypatch):
    client=_client(monkeypatch)
    reservation_id=uuid4()
    monkeypatch.setattr(admin_routes,"reservation_case",lambda _reservation_id:{
        "reservation":{
            "id":str(reservation_id),"reference":"RYA-CASE123","property_name":"Example Hotel",
            "property_city":"Lagos","property_state":"Lagos","organization_name":"Example Group",
            "guest_name":"Guest Example","guest_email":"guest@example.com","guest_phone":"+2348000000000",
            "check_in":"2026-10-10","check_out":"2026-10-12","nights":2,"adults":2,"children":0,
            "status":"confirmed","payment_status":"paid","guarantee_type":"pay_now",
            "currency":"NGN","total_price_minor":5000000,"amount_due_minor":5000000,
            "amount_paid_minor":5000000,"created_at":"2026-10-03","expires_at":None,
        },
        "items":[{"room_type_name":"King Room","rate_plan_name":"Standard","guarantee_type":"pay_now","quantity":1,"total_price_minor":5000000}],
        "transactions":[{"provider_reference":"roya_case","provider":"paystack","created_at":"2026-10-03","paid_at":"2026-10-03","status":"successful","currency":"NGN","amount_minor":5000000}],
        "refunds":[],
        "notifications":[{"event_type":"reservation.created","channel":"email","recipient":"guest@example.com","created_at":"2026-10-03","last_error":None,"status":"sent","attempts":1}],
        "audit":[{"action":"reservation.checked_in","created_at":"2026-10-10","actor_user_id":None}],
    })
    response=client.get(f"/admin/reservations/{reservation_id}")
    assert response.status_code==200
    assert b"Provider transactions" in response.data
    assert b"roya_case" in response.data
    assert b"Delivery trail" in response.data


def test_admin_can_run_operational_scan(monkeypatch):
    client=_client(monkeypatch)
    monkeypatch.setattr(admin_routes,"sync_operational_alerts",lambda:{
        "new_alerts":1,"reopened_alerts":0,"resolved_alerts":2,
    })
    response=client.post("/api/v1/admin/operations/scan")
    assert response.status_code==200
    assert response.json["data"]["new_alerts"]==1


def test_admin_can_acknowledge_operational_alert(monkeypatch):
    client=_client(monkeypatch)
    alert_id=uuid4()
    captured={}

    def fake_ack(alert_id,actor_user_id):
        captured["alert_id"]=alert_id
        captured["actor_user_id"]=actor_user_id
        return {"id":alert_id,"status":"acknowledged"}

    monkeypatch.setattr(admin_routes,"acknowledge_operational_alert",fake_ack)
    response=client.post(f"/api/v1/admin/operations/alerts/{alert_id}/acknowledge")
    assert response.status_code==200
    assert response.json["data"]["status"]=="acknowledged"
    assert captured["alert_id"]==str(alert_id)
