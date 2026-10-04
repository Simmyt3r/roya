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


def test_non_admin_cannot_open_review_moderation(monkeypatch):
    client=_client(monkeypatch,role="user")
    response=client.get("/admin/reviews")
    assert response.status_code==403


def test_admin_review_moderation_renders_verified_review(monkeypatch):
    client=_client(monkeypatch)
    review_id=str(uuid4())
    reservation_id=str(uuid4())
    property_id=str(uuid4())
    monkeypatch.setattr(admin_routes,"list_reviews",lambda query="",visibility="":[{
        "id":review_id,
        "rating":5,
        "comment":"Excellent stay.",
        "is_visible":True,
        "created_at":"2026-10-04",
        "updated_at":"2026-10-04",
        "reservation_id":reservation_id,
        "reservation_reference":"IRY-ABC123",
        "property_id":property_id,
        "property_name":"Example Hotel",
        "user_id":str(uuid4()),
        "reviewer_name":"Ada",
        "reviewer_email":"ada@example.com",
    }])
    monkeypatch.setattr(admin_routes,"review_counts",lambda:{
        "total":1,"visible":1,"hidden":0,"average_visible":5.0,
    })
    response=client.get("/admin/reviews?q=Example")
    assert response.status_code==200
    assert b"Review moderation" in response.data
    assert b"Example Hotel" in response.data
    assert b"IRY-ABC123" in response.data
    assert b"Hide review" in response.data


def test_admin_can_hide_review(monkeypatch):
    client=_client(monkeypatch)
    review_id=uuid4()
    captured={}

    def fake_set(review_id,is_visible,actor_user_id):
        captured["review_id"]=review_id
        captured["is_visible"]=is_visible
        captured["actor_user_id"]=actor_user_id
        return {
            "id":review_id,
            "is_visible":is_visible,
            "property_name":"Example Hotel",
            "reservation_reference":"IRY-ABC123",
        }

    monkeypatch.setattr(admin_routes,"set_review_visibility",fake_set)
    response=client.put(
        f"/api/v1/admin/reviews/{review_id}/visibility",
        json={"is_visible":False},
    )
    assert response.status_code==200
    assert response.json["data"]["is_visible"] is False
    assert captured["review_id"]==str(review_id)
    assert captured["is_visible"] is False


def test_review_visibility_payload_requires_boolean(monkeypatch):
    client=_client(monkeypatch)
    review_id=uuid4()
    response=client.put(
        f"/api/v1/admin/reviews/{review_id}/visibility",
        json={"is_visible":"not-a-boolean"},
    )
    assert response.status_code==422
