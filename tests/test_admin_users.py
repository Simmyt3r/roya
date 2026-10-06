from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.admin import routes as admin_routes
from roya.admin import service as admin_service
from roya.auth import service as auth_service
from roya.auth.service import Identity
from roya.common.errors import RoyaError


@contextmanager
def _admin_lookup(role="admin"):
    class Connection:
        def execute(self,*_args,**_kwargs):
            return self

        def fetchone(self):
            return {"platform_role":role,"status":"active"}

    yield Connection()


def _admin_client(monkeypatch,role="admin"):
    monkeypatch.setattr(
        admin_service,
        "current_identity",
        lambda required=False:SimpleNamespace(user_id=str(uuid4())),
    )
    monkeypatch.setattr(admin_service,"db_connection",lambda:_admin_lookup(role))
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    return app.test_client()


def test_non_admin_cannot_open_user_management(monkeypatch):
    client=_admin_client(monkeypatch,role="user")
    response=client.get("/admin/users")
    assert response.status_code==403


def test_admin_user_management_renders_accounts(monkeypatch):
    client=_admin_client(monkeypatch)
    user_id=str(uuid4())
    monkeypatch.setattr(admin_routes,"search_user_accounts",lambda query="",status="":[{
        "id":user_id,
        "name":"Guest Example",
        "email":"guest@example.com",
        "phone":"+2348000000000",
        "account_type":"guest",
        "platform_role":"user",
        "status":"active",
        "created_at":"2026-10-03",
        "updated_at":"2026-10-03",
        "last_sign_in_at":"2026-10-03",
        "reservation_count":2,
        "organization_count":0,
    }])
    monkeypatch.setattr(admin_routes,"user_account_counts",lambda:{
        "total":1,"active":1,"suspended":0,"pending_verification":0,"guests":1,"hotels":0,
        "platform_support":0,"platform_finance":0,
    })
    response=client.get("/admin/users?q=guest")
    assert response.status_code==200
    assert b"User accounts" in response.data
    assert b"guest@example.com" in response.data
    assert b"Suspend" in response.data


def test_admin_can_suspend_user_through_status_endpoint(monkeypatch):
    client=_admin_client(monkeypatch)
    user_id=uuid4()
    captured={}

    def fake_change(user_id,status,actor_user_id):
        captured.update({
            "user_id":user_id,
            "status":status,
            "actor_user_id":actor_user_id,
        })
        return {
            "id":user_id,
            "status":status,
            "previous_status":"active",
            "revoked_sessions":2,
        }

    monkeypatch.setattr(admin_routes,"change_user_status",fake_change)
    response=client.put(
        f"/api/v1/admin/users/{user_id}/status",
        json={"status":"suspended"},
    )
    assert response.status_code==200
    assert response.json["data"]["status"]=="suspended"
    assert response.json["data"]["revoked_sessions"]==2
    assert captured["user_id"]==str(user_id)


class _StatusConnection:
    def __init__(self,status):
        self.status=status
        self.revoked=False
        self.committed=False
        self.sql=""

    def execute(self,sql,_params=None):
        self.sql=sql
        if "update private.app_sessions" in sql:
            self.revoked=True
        return self

    def fetchone(self):
        if "select status from profiles" in self.sql:
            return {"status":self.status}
        return None

    def commit(self):
        self.committed=True


def _status_db(connection):
    @contextmanager
    def context():
        yield connection
    return context


def test_suspended_identity_is_blocked_and_sessions_revoked(monkeypatch):
    user_id=str(uuid4())
    connection=_StatusConnection("suspended")
    monkeypatch.setattr(auth_service,"db_connection",lambda:_status_db(connection)())
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})

    with app.test_request_context("/account"):
        auth_service.session["sid"]="opaque-session"
        with pytest.raises(RoyaError) as raised:
            auth_service.ensure_account_not_suspended(
                Identity(user_id=user_id,email="guest@example.com"),
                "opaque-session",
            )
        assert raised.value.code=="ACCOUNT_SUSPENDED"
        assert raised.value.status_code==403
        assert connection.revoked is True
        assert connection.committed is True
        assert "sid" not in auth_service.session


def test_active_identity_remains_allowed(monkeypatch):
    identity=Identity(user_id=str(uuid4()),email="guest@example.com")
    connection=_StatusConnection("active")
    monkeypatch.setattr(auth_service,"db_connection",lambda:_status_db(connection)())

    result=auth_service.ensure_account_not_suspended(identity)
    assert result==identity
    assert connection.revoked is False


def test_current_identity_preserves_suspension_error(monkeypatch):
    user_id=str(uuid4())
    identity=Identity(user_id=user_id,email="guest@example.com")
    monkeypatch.setattr(
        auth_service,
        "_extract_access_context",
        lambda:("valid-token",False,None,None),
    )
    monkeypatch.setattr(auth_service,"supabase_anon_client",lambda:object())
    monkeypatch.setattr(auth_service,"_identity_from_token",lambda _client,_token:identity)

    def suspended(_identity,_raw_session_id=None):
        raise RoyaError("ACCOUNT_SUSPENDED","Suspended.",403)

    monkeypatch.setattr(auth_service,"ensure_account_not_suspended",suspended)
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/api/v1/auth/me"):
        with pytest.raises(RoyaError) as raised:
            auth_service.current_identity(required=True)
    assert raised.value.code=="ACCOUNT_SUSPENDED"
    assert raised.value.status_code==403


def test_admin_can_assign_platform_finance_role(monkeypatch):
    client=_admin_client(monkeypatch)
    user_id=uuid4()
    captured={}

    def fake_change(user_id,platform_role,actor_user_id):
        captured.update({
            "user_id":user_id,
            "platform_role":platform_role,
            "actor_user_id":actor_user_id,
        })
        return {
            "id":user_id,
            "platform_role":platform_role,
            "previous_platform_role":"user",
            "revoked_sessions":1,
        }

    monkeypatch.setattr(admin_routes,"change_platform_role",fake_change)
    response=client.put(
        f"/api/v1/admin/users/{user_id}/platform-role",
        json={"platform_role":"finance"},
    )
    assert response.status_code==200
    assert response.json["data"]["platform_role"]=="finance"
    assert response.json["data"]["revoked_sessions"]==1
    assert captured["user_id"]==str(user_id)


def test_admin_role_cannot_be_assigned_through_staff_endpoint(monkeypatch):
    client=_admin_client(monkeypatch)
    response=client.put(
        f"/api/v1/admin/users/{uuid4()}/platform-role",
        json={"platform_role":"admin"},
    )
    assert response.status_code==422


def test_support_role_cannot_manage_user_accounts(monkeypatch):
    client=_admin_client(monkeypatch,role="support")
    response=client.get("/admin/users")
    assert response.status_code==403
