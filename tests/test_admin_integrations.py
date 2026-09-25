from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.admin import routes as admin_routes
from roya.admin import service as admin_service
from roya.common import integrations
from roya.payments.paystack import PaystackProvider
from roya.notifications import smtp as smtp_module


@contextmanager
def _admin_lookup(role):
    class Connection:
        def execute(self, *_):
            return self

        def fetchone(self):
            return {"platform_role":role,"status":"active"}

    yield Connection()


def _client(monkeypatch, role="admin"):
    monkeypatch.setattr(admin_service,"current_identity",lambda required=False: SimpleNamespace(user_id=str(uuid4())))
    monkeypatch.setattr(admin_service,"db_connection",lambda: _admin_lookup(role))
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    return app.test_client()


def test_non_admin_cannot_save_or_check_credentials(monkeypatch):
    client=_client(monkeypatch,role="user")
    for method,url in (
        ("put","/api/v1/admin/integrations/paystack"),
        ("put","/api/v1/admin/integrations/smtp"),
        ("post","/api/v1/admin/integrations/paystack/test"),
    ):
        response=getattr(client,method)(url,json={})
        assert response.status_code==403
        assert response.headers["Cache-Control"]=="private, no-store"


def test_admin_save_returns_status_without_echoing_paystack_secret(monkeypatch):
    client=_client(monkeypatch)
    saved=[]
    monkeypatch.setattr(admin_routes,"save_integration",lambda *args:saved.append(args))
    monkeypatch.setattr(admin_routes,"integration_status",lambda provider:{
        "configured":True,"source":"dashboard","mode":"test","public_key":"pk_test_example",
    })
    secret="sk_test_private_example"
    response=client.put("/api/v1/admin/integrations/paystack",json={
        "public_key":"pk_test_example","secret_key":secret,
    })
    assert response.status_code==200
    assert saved[0][0]=="paystack"
    assert saved[0][2]==secret
    assert secret.encode() not in response.data


def test_key_mode_mismatch_is_rejected_before_storage(monkeypatch):
    client=_client(monkeypatch)
    monkeypatch.setattr(admin_routes,"save_integration",lambda *args:pytest.fail("unexpected save"))
    response=client.put("/api/v1/admin/integrations/paystack",json={
        "public_key":"pk_live_example","secret_key":"sk_test_private_example",
    })
    assert response.status_code==422
    assert response.json["error"]["code"]=="KEY_MODE_MISMATCH"


def test_validation_response_never_repeats_submitted_credential(monkeypatch):
    client=_client(monkeypatch)
    secret="sk_test_sensitive_password"
    response=client.put("/api/v1/admin/integrations/paystack",json={
        "public_key":"bad","secret_key":secret,
    })
    assert response.status_code==422
    assert secret.encode() not in response.data


def test_admin_dashboard_renders_configuration_without_secrets(monkeypatch):
    client=_client(monkeypatch)

    class DashboardConnection:
        def __enter__(self):
            return self

        def __exit__(self,*args):
            return False

        def execute(self,sql,*args):
            self.statement=sql
            return self

        def fetchone(self):
            return SimpleNamespace(
                pending_properties=0,verified_properties=0,
                reservations_this_month=0,volume_this_month_minor=0,
            )

        def fetchall(self):
            return []

    monkeypatch.setattr(admin_routes,"db_connection",lambda:DashboardConnection())
    monkeypatch.setattr(admin_routes,"integration_status",lambda provider:{
        "configured":True,"source":"dashboard","mode":"test",
        "public_key":"pk_test_example","has_secret":True,
        "host":"smtp.example.com","port":587,"security":"starttls",
        "sender":"admin@example.com","username":"admin@example.com","has_password":True,
    })
    response=client.get("/admin")
    assert response.status_code==200
    assert b'data-admin-integration="smtp"' in response.data
    assert b'data-admin-integration="paystack"' in response.data
    assert b"sk_test_" not in response.data
    assert b"saved password" in response.data


def test_paystack_provider_uses_dashboard_secret_for_webhook(monkeypatch):
    app=create_app({"TESTING":True,"DATABASE_URL":""})
    monkeypatch.setattr("roya.payments.paystack.paystack_settings",lambda:{"secret_key":"sk_test_dashboard"})
    with app.app_context():
        provider=PaystackProvider()
        assert provider.secret=="sk_test_dashboard"
        assert provider.verify_webhook(b"{}","invalid") is False


def test_admin_status_does_not_include_vault_secret(monkeypatch):
    app=create_app({"TESTING":True,"DATABASE_URL":""})
    monkeypatch.setattr(integrations,"_stored",lambda provider:{
        "configuration":{"public_key":"pk_test_example","mode":"test"},
        "decrypted_secret":"sk_test_never_expose","secret_id":uuid4(),
    })
    with app.app_context():
        status=integrations.integration_status("paystack")
    assert status["configured"] is True
    assert "sk_test_never_expose" not in str(status)


def test_new_credential_is_written_only_to_vault(monkeypatch):
    credential="sk_test_secret_for_vault"
    calls=[]
    secret_id=uuid4()

    class Connection:
        @contextmanager
        def transaction(self):
            yield

        def execute(self,sql,params):
            calls.append((sql,params))
            return self

        def fetchone(self):
            sql=calls[-1][0]
            return {"secret_id":secret_id if "create_secret" in sql else None}

    @contextmanager
    def db():
        yield Connection()

    monkeypatch.setattr(integrations,"db_connection",db)
    integrations.save_integration(
        "paystack",{"public_key":"pk_test_example","mode":"test"},
        credential,str(uuid4()),
    )
    vault_calls=[params for sql,params in calls if "vault.create_secret" in sql]
    assert len(vault_calls)==1 and vault_calls[0][0]==credential
    settings_update=next(params for sql,params in calls if "update private.integration_settings" in sql)
    assert credential not in str(settings_update)
    audit=next(params for sql,params in calls if "insert into audit_logs" in sql)
    assert credential not in str(audit)


def test_smtp_connection_check_authenticates_without_sending(monkeypatch):
    calls=[]

    class FakeSMTP:
        def __init__(self,*args,**kwargs):
            calls.append("connect")

        def starttls(self,**kwargs):
            calls.append("starttls")

        def login(self,username,password):
            calls.append("login")

        def __enter__(self):
            return self

        def __exit__(self,*args):
            calls.append("close")

        def close(self):
            calls.append("close")

        def send_message(self,msg):
            calls.append("send")

    monkeypatch.setattr(smtp_module.smtplib,"SMTP",FakeSMTP)
    monkeypatch.setattr(smtp_module,"smtp_settings",lambda:{
        "host":"smtp.example.com","port":587,"security":"starttls",
        "username":"admin@example.com","password":"saved-secret","sender":"admin@example.com",
    })
    smtp_module.SmtpNotificationAdapter().test_connection()
    assert calls==["connect","starttls","login","close"]


def test_paystack_connection_check_only_reads_provider_setting(monkeypatch):
    calls=[]
    app=create_app({"TESTING":True,"DATABASE_URL":""})
    monkeypatch.setattr("roya.payments.paystack.paystack_settings",lambda:{"secret_key":"sk_test_dashboard"})

    def fake_get(url,**kwargs):
        calls.append((url,kwargs))
        return SimpleNamespace(ok=True,json=lambda:{"status":True,"data":{"payment_session_timeout":30}})

    monkeypatch.setattr("roya.payments.paystack.requests.get",fake_get)
    with app.app_context():
        assert PaystackProvider().test_connection() is True
    assert calls[0][0].endswith("/integration/payment_session_timeout")
    assert calls[0][1]["headers"]["Authorization"]=="Bearer sk_test_dashboard"
