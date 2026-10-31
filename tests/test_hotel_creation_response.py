"""Regression tests for hotel creation responses using real PostgreSQL time values.

A successful INSERT must not become a 500 response during JSON serialization.
"""
from contextlib import contextmanager
from datetime import datetime, time, timezone
from uuid import uuid4

from roya import create_app
from roya.auth import service as auth_service
from roya.auth.service import Identity
from roya.properties import routes as property_routes


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row, before=None):
        self.row = row
        self.before = before
        self.commit_calls = 0
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "insert into properties" in sql or "update properties set" in sql:
            return FakeCursor(self.row)
        if "select p.*,om.role member_role" in sql:
            return FakeCursor(self.before)
        return FakeCursor()

    def commit(self):
        self.commit_calls += 1

    @contextmanager
    def transaction(self):
        yield self


def _client(monkeypatch, conn):
    identity = Identity(user_id=str(uuid4()), email="owner@example.com")

    @contextmanager
    def fake_db():
        yield conn

    monkeypatch.setattr(property_routes, "db_connection", fake_db)
    monkeypatch.setattr(property_routes, "current_identity", lambda required=False: identity)
    monkeypatch.setattr(auth_service, "current_identity", lambda required=False: identity)
    monkeypatch.setattr(property_routes, "require_organization_member", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(property_routes, "allocate_mini_domain", lambda *_: "example-hotel")

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "DATABASE_URL": "",
        "SUPABASE_URL": "",
        "SUPABASE_PUBLISHABLE_KEY": "",
    })
    return app.test_client(), identity


def _record(org_id, property_id):
    return {
        "id": property_id,
        "organization_id": org_id,
        "name": "Example Hotel",
        "slug": "example-hotel-ab1234",
        "mini_domain": "example-hotel",
        "description": "",
        "address": "1 Hotel Road",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "latitude": None,
        "longitude": None,
        "location": "0101000020E6100000",
        "check_in_time": time(14, 0),
        "check_out_time": time(12, 0),
        "status": "draft",
        "verification_status": "pending",
        "created_at": datetime.now(timezone.utc),
    }


def _payload(org_id):
    return {
        "organization_id": org_id,
        "name": "Example Hotel",
        "address": "1 Hotel Road",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "check_in_time": "14:00",
        "check_out_time": "12:00",
    }


def test_hotel_creation_succeeds_even_when_sql_returns_time_objects(monkeypatch):
    org_id, property_id = str(uuid4()), str(uuid4())
    conn = FakeConnection(_record(org_id, property_id))
    client, _ = _client(monkeypatch, conn)

    response = client.post("/api/v1/properties", json=_payload(org_id))

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["id"] == property_id
    assert data["redirect_to"] == f"/partner/properties/{property_id}"
    assert data["check_in_time"] == "14:00:00"
    assert data["check_out_time"] == "12:00:00"
    assert "location" not in data
    assert conn.commit_calls == 1
    assert any("insert into properties" in sql for sql, _ in conn.executed)


def test_hotel_update_succeeds_and_remains_json_serializable(monkeypatch):
    org_id, property_id = str(uuid4()), str(uuid4())
    row = _record(org_id, property_id)
    before = {
        **row,
        "member_role": "owner",
    }
    conn = FakeConnection(row, before)
    client, _ = _client(monkeypatch, conn)

    response = client.put(
        f"/api/v1/properties/{property_id}",
        json={k: v for k, v in _payload(org_id).items() if k != "organization_id"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["check_in_time"] == "14:00:00"
    assert data["check_out_time"] == "12:00:00"
    assert data["requires_reverification"] is False
    assert "location" not in data
    assert any("insert into audit_logs" in sql for sql, _ in conn.executed)
