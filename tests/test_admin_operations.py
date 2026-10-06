from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from roya import create_app
from roya.admin import routes as admin_routes
from roya.admin import service as admin_service
from roya.common import security as security_module
from roya.internal import routes as internal_routes


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


def test_operations_scan_rejects_invalid_vault_bearer(monkeypatch):
    @contextmanager
    def vault_lookup():
        class Connection:
            def execute(self,*_args,**_kwargs):
                return self

            def fetchone(self):
                return {"decrypted_secret":"correct-secret"}

        yield Connection()

    monkeypatch.setattr(security_module,"db_connection",lambda:vault_lookup())
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    client=app.test_client()
    response=client.get(
        "/api/internal/cron/operations-scan",
        headers={"Authorization":"Bearer wrong-secret"},
    )
    assert response.status_code==403


def test_operations_scan_accepts_vault_bearer_and_runs_recovery(monkeypatch):
    @contextmanager
    def vault_lookup():
        class Connection:
            def execute(self,*_args,**_kwargs):
                return self

            def fetchone(self):
                return {"decrypted_secret":"correct-secret"}

        yield Connection()

    class FakePaymentService:
        def reconcile_pending(self):
            return {"reconciled":1,"pending":0,"errors":0}

        def reconcile_refunds(self):
            return {"processed":1,"failed":0,"errors":0}

    class FakeNotificationService:
        def __init__(self,*_args,**_kwargs):
            pass

        def deliver_pending_emails(self,limit=100):
            return {"checked":0,"sent":0,"retrying":0,"failed":0,"suppressed":0}

    monkeypatch.setattr(security_module,"db_connection",lambda:vault_lookup())
    monkeypatch.setattr(internal_routes,"PaymentService",FakePaymentService)
    monkeypatch.setattr(internal_routes,"NotificationService",FakeNotificationService)
    monkeypatch.setattr(internal_routes,"SmtpNotificationAdapter",lambda:object())
    monkeypatch.setattr(internal_routes,"expire_overdue_holds",lambda:{"expired":0})
    monkeypatch.setattr(internal_routes,"sync_operational_alerts",lambda:{
        "new_alerts":0,"reopened_alerts":0,"resolved_alerts":0,
    })

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    client=app.test_client()
    response=client.get(
        "/api/internal/cron/operations-scan",
        headers={"Authorization":"Bearer correct-secret"},
    )
    assert response.status_code==200
    assert response.json["data"]["money"]["payments"]["reconciled"]==1
    assert response.json["data"]["money"]["refunds"]["processed"]==1


def test_admin_readiness_endpoint(monkeypatch):
    client=_client(monkeypatch)
    monkeypatch.setattr(admin_routes,"booking_readiness_snapshot",lambda:{
        "database_configured":True,
        "database_reachable":True,
        "booking_ready":True,
        "schema":{"create_reservation":True},
        "integrations":{"payments_configured":True},
        "operations":{"inventory_anomalies":0,"operations_scan_active":True},
        "activity":{},
    })
    response=client.get("/api/v1/admin/readiness")
    assert response.status_code==200
    assert response.json["data"]["booking_ready"] is True


def _healthy_operations():
    return {
        "counts":{
            "stuck_payments":0,
            "stuck_refunds":0,
            "overdue_holds":0,
            "expiring_holds":0,
            "failed_email_24h":0,
            "overdue_email_queue":0,
            "inventory_anomalies":0,
            "active_hotels_without_30d_inventory":0,
        },
        "issues":[],
        "critical":0,
        "warning":0,
        "healthy":True,
    }


def test_support_role_can_open_read_only_workspace(monkeypatch):
    client=_client(monkeypatch,role="support")
    monkeypatch.setattr(admin_routes,"operations_snapshot",lambda limit=30:_healthy_operations())
    response=client.get("/support")
    assert response.status_code==200
    assert b"Support operations" in response.data
    assert b"Find reservation" in response.data
    assert b"Reconcile money" not in response.data


def test_finance_role_cannot_open_support_workspace(monkeypatch):
    client=_client(monkeypatch,role="finance")
    response=client.get("/support")
    assert response.status_code==403


def test_support_can_search_reservation_cases(monkeypatch):
    client=_client(monkeypatch,role="support")
    reservation_id=str(uuid4())
    monkeypatch.setattr(admin_routes,"search_reservation_cases",lambda query:[{
        "id":reservation_id,
        "reference":"RYA-SUPPORT1",
        "guest_name":"Guest Example",
        "guest_email":"guest@example.com",
        "check_in":"2026-10-10",
        "check_out":"2026-10-12",
        "status":"confirmed",
        "payment_status":"paid",
        "amount_paid_minor":2500000,
        "currency":"NGN",
        "property_name":"Example Hotel",
        "created_at":"2026-10-06",
    }])
    response=client.get("/support/reservations?q=RYA-SUPPORT1")
    assert response.status_code==200
    assert b"RYA-SUPPORT1" in response.data
    assert f"/support/reservations/{reservation_id}".encode() in response.data


def test_support_cannot_run_admin_recovery_actions(monkeypatch):
    client=_client(monkeypatch,role="support")
    assert client.post("/api/v1/admin/operations/scan").status_code==403
    assert client.post("/api/v1/admin/operations/expire-holds").status_code==403
    assert client.post("/api/v1/admin/operations/reconcile-money").status_code==403
