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


def test_non_admin_cannot_open_audit_trail(monkeypatch):
    client=_client(monkeypatch,role="user")
    response=client.get("/admin/audit")
    assert response.status_code==403


def test_admin_audit_trail_renders_event(monkeypatch):
    client=_client(monkeypatch)
    event_id=str(uuid4())
    reservation_id=str(uuid4())

    monkeypatch.setattr(admin_routes,"list_audit_events",lambda **_kwargs:[{
        "id":event_id,
        "actor_user_id":str(uuid4()),
        "organization_id":str(uuid4()),
        "property_id":str(uuid4()),
        "action":"reservation.confirmed",
        "entity_type":"reservation",
        "entity_id":reservation_id,
        "before_json":{"status":"pending_confirmation"},
        "after_json":{"status":"confirmed"},
        "ip_address":"127.0.0.1",
        "user_agent":"pytest",
        "created_at":"2026-10-04 05:30:00+00",
        "actor_name":"Admin User",
        "actor_email":"admin@example.com",
        "organization_name":"Example Hotels",
        "property_name":"Example Hotel",
    }])
    monkeypatch.setattr(admin_routes,"audit_filter_options",lambda:{
        "entity_types":["reservation"],
        "actions":["reservation.confirmed"],
    })
    monkeypatch.setattr(admin_routes,"audit_counts",lambda:{
        "total":1,"last_24h":1,"actors":1,"properties":1,
    })

    response=client.get("/admin/audit?entity_type=reservation&since_days=7")
    assert response.status_code==200
    assert b"Audit trail" in response.data
    assert b"reservation.confirmed" in response.data
    assert b"Example Hotel" in response.data
    assert reservation_id.encode() in response.data
    assert b"pending_confirmation" in response.data


def test_admin_audit_rejects_invalid_range(monkeypatch):
    client=_client(monkeypatch)
    response=client.get("/admin/audit?since_days=2")
    assert response.status_code==422
