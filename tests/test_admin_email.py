from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from roya import create_app
from roya.admin import routes as admin_routes
from roya.admin import service as admin_service


@contextmanager
def _admin_lookup(role):
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


def test_non_admin_cannot_send_marketing_email(monkeypatch):
    client=_client(monkeypatch,role="user")
    response=client.post("/api/v1/admin/email/campaigns",json={
        "audience":"custom",
        "subject":"Hello",
        "body":"Welcome to iRoya",
        "custom_recipients":["outside@example.com"],
    })
    assert response.status_code==403


def test_custom_campaign_rejects_invalid_external_email(monkeypatch):
    client=_client(monkeypatch)
    monkeypatch.setattr(admin_routes,"integration_status",lambda _provider:{"configured":True})
    response=client.post("/api/v1/admin/email/campaigns",json={
        "audience":"custom",
        "subject":"Hello",
        "body":"Welcome to iRoya",
        "custom_recipients":["not-an-email"],
    })
    assert response.status_code==422
    assert response.json["error"]["code"]=="VALIDATION_ERROR"


def test_admin_campaign_queues_registered_audience(monkeypatch):
    client=_client(monkeypatch)
    captured={}
    monkeypatch.setattr(admin_routes,"integration_status",lambda _provider:{"configured":True})

    def fake_queue(**kwargs):
        captured.update(kwargs)
        return {
            "campaign_id":str(uuid4()),
            "audience":kwargs["audience"],
            "queued":12,
            "immediate_delivery":{"sent":5},
            "remaining_queued":7,
        }

    monkeypatch.setattr(admin_routes,"queue_campaign",fake_queue)
    response=client.post("/api/v1/admin/email/campaigns",json={
        "audience":"registered_hotels",
        "subject":"Hotel update",
        "body":"Hello {{name}}",
        "custom_recipients":[],
    })
    assert response.status_code==200
    assert response.json["data"]["queued"]==12
    assert captured["audience"]=="registered_hotels"
    assert captured["custom_recipients"]==[]



def test_record_marketing_consent_requires_explicit_confirmation(monkeypatch):
    client=_client(monkeypatch)
    response=client.post("/api/v1/admin/email/subscribers",json={
        "email":"outside@example.com",
        "consent_confirmed":False,
    })
    assert response.status_code==422
    assert response.json["error"]["code"]=="VALIDATION_ERROR"


def test_admin_can_record_confirmed_marketing_consent(monkeypatch):
    client=_client(monkeypatch)
    captured={}

    def fake_record(**kwargs):
        captured.update(kwargs)
        return {
            "id":str(uuid4()),
            "email":kwargs["email"],
            "linked_registered_user":False,
            "consent_at":"2026-09-26T12:00:00+00:00",
        }

    monkeypatch.setattr(admin_routes,"record_marketing_consent",fake_record)
    response=client.post("/api/v1/admin/email/subscribers",json={
        "email":"outside@example.com",
        "consent_confirmed":True,
    })
    assert response.status_code==200
    assert captured["email"]=="outside@example.com"


def test_campaign_requires_smtp(monkeypatch):
    client=_client(monkeypatch)
    monkeypatch.setattr(admin_routes,"integration_status",lambda _provider:{"configured":False})
    response=client.post("/api/v1/admin/email/campaigns",json={
        "audience":"registered_all",
        "subject":"Hello",
        "body":"An update",
        "custom_recipients":[],
    })
    assert response.status_code==409
    assert response.json["error"]["code"]=="SMTP_NOT_CONFIGURED"


def test_admin_dashboard_renders_email_workspace(monkeypatch):
    client=_client(monkeypatch)

    class DashboardConnection:
        def __enter__(self):
            return self

        def __exit__(self,*_args):
            return False

        def execute(self,*_args,**_kwargs):
            return self

        def fetchone(self):
            return SimpleNamespace(
                pending_properties=0,
                verified_properties=0,
                reservations_this_month=0,
                volume_this_month_minor=0,
            )

        def fetchall(self):
            return []

    monkeypatch.setattr(admin_routes,"db_connection",lambda:DashboardConnection())
    monkeypatch.setattr(admin_routes,"list_templates",lambda:[{
        "id":str(uuid4()),
        "name":"Hotel partner outreach",
        "subject":"Join iRoya",
        "body":"Hello {{name}}",
        "category":"hotel_outreach",
    }])
    monkeypatch.setattr(admin_routes,"recent_campaigns",lambda:[])
    monkeypatch.setattr(admin_routes,"subscriber_counts",lambda:{"active_total":3,"active_registered":2,"active_external":1})
    monkeypatch.setattr(admin_routes,"integration_status",lambda _provider:{
        "configured":True,
        "source":"dashboard",
        "mode":"test",
        "public_key":"pk_test_example",
        "has_secret":True,
        "host":"smtp.example.com",
        "port":587,
        "security":"starttls",
        "sender":"admin@example.com",
        "username":"admin@example.com",
        "has_password":True,
    })

    response=client.get("/admin")
    assert response.status_code==200
    assert b"Campaigns &amp; templates" in response.data
    assert b'data-email-campaign' in response.data
    assert b"All consented external / non-registered subscribers" in response.data
    assert b"Hotel partner outreach" in response.data
    assert b"Marketing consent" in response.data
    assert b"admin-email-template-data" in response.data
