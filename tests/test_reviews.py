from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.reviews import routes as review_routes
from roya.reviews import service as review_service
from roya.reviews.schemas import ReviewCreate
from roya.reviews.service import ReviewService


def _client(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="guest@example.com")
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(review_routes,"current_identity",lambda required=False:identity)
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    return app.test_client(),identity


def test_review_rating_validation_rejects_out_of_range(monkeypatch):
    client,_identity=_client(monkeypatch)
    response=client.post("/api/v1/reviews",json={
        "reservation_id":str(uuid4()),
        "rating":6,
        "comment":"Impossible rating",
    })
    assert response.status_code==422
    assert response.json["error"]["code"]=="VALIDATION_ERROR"


def test_checked_out_review_route_creates_verified_review(monkeypatch):
    client,identity=_client(monkeypatch)
    reservation_id=uuid4()
    captured={}

    def fake_create(user_id,payload):
        captured["user_id"]=user_id
        captured["payload"]=payload
        return {
            "id":str(uuid4()),
            "reservation_id":str(payload.reservation_id),
            "rating":payload.rating,
            "comment":payload.comment,
            "is_visible":True,
        }

    monkeypatch.setattr(review_routes.service,"create",fake_create)
    response=client.post("/api/v1/reviews",json={
        "reservation_id":str(reservation_id),
        "rating":5,
        "comment":"Clean room and helpful staff.",
    })
    assert response.status_code==201
    assert response.json["data"]["rating"]==5
    assert captured["user_id"]==identity.user_id
    assert str(captured["payload"].reservation_id)==str(reservation_id)


def test_public_review_endpoint_returns_summary_and_visible_reviews(monkeypatch):
    client,_identity=_client(monkeypatch)
    property_id=uuid4()
    monkeypatch.setattr(review_routes.service,"summary",lambda _property_id:{
        "review_count":2,"average_rating":4.5,
    })
    monkeypatch.setattr(review_routes.service,"list_public",lambda _property_id,limit=20:[{
        "id":str(uuid4()),"rating":5,"comment":"Lovely stay.","reviewer_name":"Ada",
    }])
    response=client.get(f"/api/v1/properties/{property_id}/reviews?limit=12")
    assert response.status_code==200
    assert response.json["data"]["summary"]["review_count"]==2
    assert response.json["data"]["reviews"][0]["reviewer_name"]=="Ada"


class _Transaction:
    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False


class _ReviewConnection:
    def __init__(self,reservation,existing=None):
        self.reservation=reservation
        self.existing=existing

    def transaction(self):
        return _Transaction()

    def execute(self,sql,_params=None):
        self.sql=sql
        return self

    def fetchone(self):
        if "from reservations r" in self.sql:
            return self.reservation
        if "select id from reviews" in self.sql:
            return self.existing
        return None


def _review_db(connection):
    @contextmanager
    def context():
        yield connection
    return context


def test_review_service_requires_completed_checkout(monkeypatch):
    user_id=str(uuid4())
    reservation_id=uuid4()
    connection=_ReviewConnection({
        "id":str(reservation_id),
        "property_id":str(uuid4()),
        "organization_id":str(uuid4()),
        "status":"confirmed",
        "user_id":user_id,
        "property_name":"Example Hotel",
    })
    monkeypatch.setattr(review_service,"db_connection",lambda:_review_db(connection)())

    payload=ReviewCreate(reservation_id=reservation_id,rating=5,comment="Nice")
    with pytest.raises(RoyaError) as raised:
        ReviewService().create(user_id,payload)
    assert raised.value.code=="REVIEW_NOT_ELIGIBLE"
    assert raised.value.status_code==409


def test_review_service_rejects_duplicate_stay_review(monkeypatch):
    user_id=str(uuid4())
    reservation_id=uuid4()
    connection=_ReviewConnection({
        "id":str(reservation_id),
        "property_id":str(uuid4()),
        "organization_id":str(uuid4()),
        "status":"checked_out",
        "user_id":user_id,
        "property_name":"Example Hotel",
    },existing={"id":str(uuid4())})
    monkeypatch.setattr(review_service,"db_connection",lambda:_review_db(connection)())

    payload=ReviewCreate(reservation_id=reservation_id,rating=4,comment="Good stay")
    with pytest.raises(RoyaError) as raised:
        ReviewService().create(user_id,payload)
    assert raised.value.code=="REVIEW_ALREADY_SUBMITTED"
    assert raised.value.status_code==409
