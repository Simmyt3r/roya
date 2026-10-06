from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.distribution import routes as distribution_routes
from roya.distribution.service import sync_builtin_channel


def _identity():
    return SimpleNamespace(user_id=str(uuid4()),email="owner@example.com")


def _dashboard():
    org_id=str(uuid4())
    property_id=str(uuid4())
    return {
        "organizations":[{"id":org_id,"name":"Example Group","role":"owner"}],
        "properties":[{
            "id":property_id,
            "organization_id":org_id,
            "name":"Example Hotel",
            "city":"Lagos",
            "state":"Lagos",
            "status":"active",
            "verification_status":"verified",
            "has_room":True,
            "has_rate":True,
            "has_inventory":True,
            "ready":True,
            "channels":[
                {
                    "key":"direct_booking",
                    "label":"Direct Booking",
                    "description":"Direct bookings.",
                    "connection_id":"",
                    "status":"not_initialized",
                    "last_synced_at":None,
                },
                {
                    "key":"roya_marketplace",
                    "label":"Roya Marketplace",
                    "description":"Marketplace discovery.",
                    "connection_id":"",
                    "status":"not_initialized",
                    "last_synced_at":None,
                },
            ],
        }],
        "logs":[],
        "future_channels":[
            {"key":"booking_com","label":"Booking.com","description":"Future OTA adapter."},
            {"key":"google_hotels","label":"Google Hotels","description":"Future hotel feed."},
        ],
        "selected_organization_id":"",
        "selected_property_id":"",
    }


def test_distribution_manager_renders_builtins_and_future_adapters(monkeypatch):
    identity=_identity()
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(distribution_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(distribution_routes,"distribution_dashboard",lambda *args,**kwargs:_dashboard())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/distribution")
    assert response.status_code==200
    assert b"Channel manager" in response.data
    assert b"Direct Booking" in response.data
    assert b"Roya Marketplace" in response.data
    assert b"Booking.com" in response.data
    assert b"Future adapter" in response.data


def test_distribution_sync_endpoint_uses_explicit_builtin_channel(monkeypatch):
    identity=_identity()
    property_id=uuid4()
    captured={}
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(distribution_routes,"current_identity",lambda required=False:identity)

    def fake_sync(user_id,property_id,channel):
        captured.update({"user_id":user_id,"property_id":property_id,"channel":channel})
        return {
            "id":str(uuid4()),
            "property_id":property_id,
            "channel":channel,
            "status":"active",
            "last_synced_at":"2026-10-06",
            "health":{"status":"ok"},
            "operations":[],
        }

    monkeypatch.setattr(distribution_routes,"sync_builtin_channel",fake_sync)
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        f"/api/v1/distribution/properties/{property_id}/direct_booking/sync",
        json={},
    )
    assert response.status_code==200
    assert response.json["data"]["status"]=="active"
    assert captured["channel"]=="direct_booking"
    assert captured["property_id"]==str(property_id)


def test_future_channel_cannot_be_synced():
    with pytest.raises(RoyaError) as raised:
        sync_builtin_channel(str(uuid4()),str(uuid4()),"booking_com")
    assert raised.value.code=="CHANNEL_NOT_AVAILABLE"
    assert raised.value.status_code==422
