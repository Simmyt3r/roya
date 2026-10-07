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


class _CancelConnection:
    def __init__(self,row=None,error=None):
        self.row=row or {
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "status":"cancelled",
            "payment_status":"unpaid",
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
        if "private.cancel_partner_reservation" in sql:
            return _Result(self.row)
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def test_partner_cancel_calls_private_atomic_function(monkeypatch):
    connection=_CancelConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    result=ReservationService().partner_cancel(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        "Guest cancelled",
        "frontdesk-cancel-request-1",
    )

    assert result["status"]=="cancelled"
    sql,params=connection.calls[0]
    assert "private.cancel_partner_reservation" in sql
    assert params==(
        "60000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        "Guest cancelled",
        "frontdesk-cancel-request-1",
    )


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","FORBIDDEN",403),
        ("PARTNER_CANCEL_SOURCE_UNSUPPORTED","PARTNER_CANCEL_SOURCE_UNSUPPORTED",409),
        ("REFUND_REQUIRED","REFUND_REQUIRED",409),
        ("RESERVATION_NOT_CANCELLABLE","RESERVATION_NOT_CANCELLABLE",409),
    ],
)
def test_partner_cancel_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_CancelConnection(error=db_error)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().partner_cancel(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            "Guest cancelled",
            "frontdesk-cancel-request-2",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_partner_cancel_route_forwards_reason_and_idempotency(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="desk@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _cancel(reservation_id,user_id,reason,key):
        captured.update({
            "reservation_id":reservation_id,
            "user_id":user_id,
            "reason":reason,
            "key":key,
        })
        return {"reservation_id":reservation_id,"status":"cancelled"}

    monkeypatch.setattr(reservation_routes.service,"partner_cancel",_cancel)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/partner/reservations/50000000-0000-4000-8000-000000000001/cancel",
        headers={"Idempotency-Key":"frontdesk-cancel-api-1"},
        json={"reason":"Guest cancelled by phone"},
    )

    assert response.status_code==200
    assert captured["user_id"]==identity.user_id
    assert captured["reason"]=="Guest cancelled by phone"
    assert captured["key"]=="frontdesk-cancel-api-1"


def _workspace(source="front_desk",role="reservations",paid=0,refunded=0,status="confirmed"):
    reservation={
        "id":"50000000-0000-4000-8000-000000000001",
        "reference":"RYA-FRONT123",
        "property_id":"10000000-0000-4000-8000-000000000001",
        "property_name":"Example Hotel",
        "property_city":"Makurdi",
        "property_state":"Benue",
        "guest_name":"Ada Guest",
        "guest_email":"",
        "guest_phone":"08012345678",
        "adults":1,
        "children":0,
        "check_in":date.today()+timedelta(days=1),
        "check_out":date.today()+timedelta(days=2),
        "nights":1,
        "check_in_time":"14:00",
        "check_out_time":"11:00",
        "status":status,
        "payment_status":"refunded" if paid and paid==refunded else ("paid" if paid else "unpaid"),
        "currency":"NGN",
        "total_price_minor":2500000,
        "amount_paid_minor":paid,
        "amount_refunded_minor":refunded,
        "source_channel":source,
        "member_role":role,
    }
    return {
        "reservation":reservation,
        "items":[{
            "room_type_name":"Deluxe",
            "rate_plan_name":"Standard",
            "quantity":1,
            "total_price_minor":2500000,
        }],
        "transactions":[],
        "refunds":[],
        "audit":[],
        "assigned_rooms":[],
        "room_readiness":{"tracked":False,"ready":True,"items":[]},
    }


@pytest.mark.parametrize("role",["owner","manager","reservations"])
def test_unpaid_front_desk_reservation_can_show_cancel(role):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=_workspace(role=role))
    assert "Cancel reservation" in html
    assert 'data-partner-reservation-cancel' in html
    assert "Cancellation locked" not in html


def test_paid_front_desk_reservation_requires_refund_before_cancel():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(paid=1000000),
        )
    assert "Cancellation locked" in html
    assert "Return and record NGN 10000.00 before cancelling" in html
    assert 'data-partner-reservation-cancel' not in html


def test_fully_refunded_front_desk_reservation_can_show_cancel():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(paid=1000000,refunded=1000000),
        )
    assert "Cancel reservation" in html
    assert 'data-partner-reservation-cancel' in html


def test_direct_booking_does_not_show_front_desk_cancel():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(source="direct_booking"),
        )
    assert 'data-partner-reservation-cancel' not in html
