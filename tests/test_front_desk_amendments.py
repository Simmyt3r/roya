from contextlib import contextmanager
from datetime import date,timedelta
from types import SimpleNamespace

import pytest
from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.reservations import routes as reservation_routes
from roya.reservations import service as reservation_service
from roya.reservations.schemas import PartnerReservationAmend
from roya.reservations.service import ReservationService


class _Txn:
    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False


class _Result:
    def __init__(self,row=None):
        self.row=row

    def fetchone(self):
        return self.row


class _AmendConnection:
    def __init__(self,row=None,error=None):
        self.row=row or {
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "reference":"RYA-FRONT123",
            "check_in":date.today()+timedelta(days=3),
            "check_out":date.today()+timedelta(days=5),
            "nights":2,
            "total_price_minor":5000000,
            "net_paid_minor":1000000,
            "recordable_balance_minor":4000000,
            "payment_status":"partially_paid",
            "idempotent":False,
        }
        self.error=error
        self.calls=[]

    def transaction(self):
        return _Txn()

    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if self.error:
            raise Exception(self.error)
        if "private.amend_partner_reservation" in sql:
            return _Result(self.row)
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def _payload():
    check_in=date.today()+timedelta(days=3)
    return PartnerReservationAmend(
        check_in=check_in,
        check_out=check_in+timedelta(days=2),
        adults=2,
        children=1,
        guest_name="Ada Updated",
        guest_email="ada@example.com",
        guest_phone="08012345678",
    )


def test_partner_amend_calls_private_atomic_function(monkeypatch):
    connection=_AmendConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    result=ReservationService().partner_amend(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        _payload(),
        "frontdesk-amend-request-1",
    )

    assert result["recordable_balance_minor"]==4000000
    sql,params=connection.calls[0]
    assert "private.amend_partner_reservation" in sql
    assert params[0]=="60000000-0000-4000-8000-000000000001"
    assert params[1]=="50000000-0000-4000-8000-000000000001"
    assert params[6]=="Ada Updated"
    assert params[7]=="ada@example.com"
    assert params[9]=="frontdesk-amend-request-1"


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","FORBIDDEN",403),
        ("PARTNER_AMEND_SOURCE_UNSUPPORTED","PARTNER_AMEND_SOURCE_UNSUPPORTED",409),
        ("RESERVATION_NOT_AMENDABLE","RESERVATION_NOT_AMENDABLE",409),
        ("MULTI_ITEM_AMEND_UNSUPPORTED","MULTI_ITEM_AMEND_UNSUPPORTED",409),
        ("REFUND_REQUIRED","REFUND_REQUIRED",409),
        ("BOOKING_CONFLICT","BOOKING_CONFLICT",409),
        ("RATE_NOT_AVAILABLE","RATE_NOT_FOUND",409),
        ("CAPACITY_EXCEEDED","VALIDATION_ERROR",422),
        ("PAST_CHECK_IN","VALIDATION_ERROR",422),
        ("CURRENCY_CHANGE_UNSUPPORTED","CURRENCY_CHANGE_UNSUPPORTED",409),
    ],
)
def test_partner_amend_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_AmendConnection(error=db_error)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().partner_amend(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            _payload(),
            "frontdesk-amend-request-2",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_partner_amend_requires_idempotency_before_database(monkeypatch):
    connection=_AmendConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().partner_amend(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            _payload(),
            "",
        )

    assert raised.value.code=="IDEMPOTENCY_KEY_REQUIRED"
    assert connection.calls==[]


def test_partner_amend_api_forwards_payload_and_idempotency(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="desk@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _amend(reservation_id,user_id,payload,key):
        captured.update({
            "reservation_id":reservation_id,
            "user_id":user_id,
            "payload":payload,
            "key":key,
        })
        return {
            "reservation_id":reservation_id,
            "reference":"RYA-FRONT123",
            "total_price_minor":5000000,
        }

    monkeypatch.setattr(reservation_routes.service,"partner_amend",_amend)

    check_in=date.today()+timedelta(days=3)
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/partner/reservations/50000000-0000-4000-8000-000000000001/amend",
        headers={"Idempotency-Key":"frontdesk-amend-api-1"},
        json={
            "check_in":check_in.isoformat(),
            "check_out":(check_in+timedelta(days=2)).isoformat(),
            "adults":2,
            "children":1,
            "guest_name":"Ada Updated",
            "guest_email":"ada@example.com",
            "guest_phone":"08012345678",
        },
    )

    assert response.status_code==200
    assert captured["user_id"]==identity.user_id
    assert captured["payload"].guest_name=="Ada Updated"
    assert captured["key"]=="frontdesk-amend-api-1"
    assert response.get_json()["data"]["redirect_to"]=="/partner/reservations/50000000-0000-4000-8000-000000000001"


def _workspace(role="reservations",source="front_desk",status="confirmed",items=1):
    check_in=date.today()+timedelta(days=2)
    reservation={
        "id":"50000000-0000-4000-8000-000000000001",
        "reference":"RYA-FRONT123",
        "property_id":"10000000-0000-4000-8000-000000000001",
        "property_name":"Example Hotel",
        "property_city":"Makurdi",
        "property_state":"Benue",
        "guest_name":"Ada Guest",
        "guest_email":"ada@example.com",
        "guest_phone":"08012345678",
        "adults":2,
        "children":0,
        "check_in":check_in,
        "check_out":check_in+timedelta(days=2),
        "nights":2,
        "check_in_time":"14:00",
        "check_out_time":"11:00",
        "status":status,
        "payment_status":"partially_paid",
        "currency":"NGN",
        "total_price_minor":5000000,
        "amount_paid_minor":1000000,
        "amount_refunded_minor":0,
        "source_channel":source,
        "member_role":role,
    }
    room_items=[{
        "id":"80000000-0000-4000-8000-000000000001",
        "quantity":1,
        "unit_price_minor":2500000,
        "total_price_minor":5000000,
        "room_type_name":"Deluxe",
        "rate_plan_name":"Standard",
        "guarantee_type":"pay_at_property",
    }]
    if items>1:
        room_items.append({
            "id":"80000000-0000-4000-8000-000000000002",
            "quantity":1,
            "unit_price_minor":2000000,
            "total_price_minor":4000000,
            "room_type_name":"Executive",
            "rate_plan_name":"Standard",
            "guarantee_type":"pay_at_property",
        })
    return {
        "reservation":reservation,
        "items":room_items,
        "transactions":[],
        "refunds":[],
        "audit":[],
        "assigned_rooms":[],
        "room_readiness":{"tracked":False,"ready":True,"items":[]},
    }


def _patch_identity(monkeypatch,identity):
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)


def test_edit_page_renders_current_front_desk_stay(monkeypatch):
    identity=SimpleNamespace(user_id="60000000-0000-4000-8000-000000000001",email="desk@example.com")
    _patch_identity(monkeypatch,identity)
    monkeypatch.setattr(reservation_routes.service,"get_for_partner",lambda *_args,**_kwargs:_workspace())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        "/partner/reservations/50000000-0000-4000-8000-000000000001/edit"
    )

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "Change stay" in html
    assert "Deluxe" in html
    assert "Standard" in html
    assert "Ada Guest" in html
    assert "Saving is atomic" in html
    assert 'data-front-desk-amendment' in html


@pytest.mark.parametrize(
    "role,source,status,items,expected_status",
    [
        ("finance","front_desk","confirmed",1,403),
        ("staff","front_desk","confirmed",1,403),
        ("reservations","direct_booking","confirmed",1,409),
        ("reservations","front_desk","checked_in",1,409),
        ("reservations","front_desk","confirmed",2,409),
    ],
)
def test_edit_page_enforces_amendment_scope(monkeypatch,role,source,status,items,expected_status):
    identity=SimpleNamespace(user_id="60000000-0000-4000-8000-000000000001",email="desk@example.com")
    _patch_identity(monkeypatch,identity)
    monkeypatch.setattr(
        reservation_routes.service,
        "get_for_partner",
        lambda *_args,**_kwargs:_workspace(role=role,source=source,status=status,items=items),
    )

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        "/partner/reservations/50000000-0000-4000-8000-000000000001/edit"
    )
    assert response.status_code==expected_status


def test_confirmed_front_desk_detail_shows_change_stay_link():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=_workspace())
    assert "Change stay" in html
    assert "/partner/reservations/50000000-0000-4000-8000-000000000001/edit" in html


@pytest.mark.parametrize(
    "source,status",
    [
        ("direct_booking","confirmed"),
        ("roya_marketplace","confirmed"),
        ("front_desk","checked_in"),
        ("front_desk","cancelled"),
    ],
)
def test_change_stay_link_hidden_outside_eligible_state(source,status):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(source=source,status=status),
        )
    assert "Change stay" not in html
