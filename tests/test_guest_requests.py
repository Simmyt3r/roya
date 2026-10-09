from contextlib import contextmanager
from datetime import date,time,timedelta
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
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []
    def fetchone(self):
        return self.row
    def fetchall(self):
        return self.rows


class _GuestRequestConnection:
    def __init__(self,row=None,error=None):
        self.row=row or {
            "note_id":"70000000-0000-4000-8000-000000000001",
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "body":"We expect to arrive around 10:30 PM.",
            "status":"open",
            "origin":"guest",
            "created_at":"2026-10-09 04:30",
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
        if "private.add_guest_reservation_request" in sql:
            return _Result(row=self.row)
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


class _GuestRequestNotifier:
    calls=[]

    def notify_guest_request(self,note_id):
        self.__class__.calls.append(note_id)
        return {"created":1}


def test_guest_request_calls_owned_private_function_and_notifies(monkeypatch):
    connection=_GuestRequestConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())
    monkeypatch.setattr(reservation_service,"NotificationService",_GuestRequestNotifier)
    _GuestRequestNotifier.calls=[]

    result=ReservationService().add_guest_request(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        "We expect to arrive around 10:30 PM.",
        "guest-request-unique-1",
    )

    assert result["origin"]=="guest"
    sql,params=connection.calls[0]
    assert "private.add_guest_reservation_request" in sql
    assert params==(
        "60000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        "We expect to arrive around 10:30 PM.",
        "guest-request-unique-1",
    )
    assert _GuestRequestNotifier.calls==["70000000-0000-4000-8000-000000000001"]


def test_idempotent_guest_request_does_not_notify_twice(monkeypatch):
    connection=_GuestRequestConnection(row={
        "note_id":"70000000-0000-4000-8000-000000000001",
        "reservation_id":"50000000-0000-4000-8000-000000000001",
        "body":"Late arrival",
        "status":"open",
        "origin":"guest",
        "created_at":"2026-10-09 04:30",
        "idempotent":True,
    })
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())
    monkeypatch.setattr(reservation_service,"NotificationService",_GuestRequestNotifier)
    _GuestRequestNotifier.calls=[]

    ReservationService().add_guest_request(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        "Late arrival",
        "guest-request-unique-2",
    )

    assert _GuestRequestNotifier.calls==[]


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","NOT_FOUND",404),
        ("REQUEST_NOT_ALLOWED","REQUEST_NOT_ALLOWED",409),
        ("TOO_MANY_OPEN_REQUESTS","TOO_MANY_OPEN_REQUESTS",409),
        ("VALIDATION_ERROR","VALIDATION_ERROR",422),
    ],
)
def test_guest_request_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_GuestRequestConnection(error=db_error)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().add_guest_request(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            "Late arrival",
            "guest-request-unique-3",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_guest_request_route_forwards_identity_and_idempotency(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="guest@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _add(reservation_id,user_id,body,key):
        captured.update({
            "reservation_id":reservation_id,
            "user_id":user_id,
            "body":body,
            "key":key,
        })
        return {
            "note_id":"70000000-0000-4000-8000-000000000001",
            "status":"open",
        }

    monkeypatch.setattr(reservation_routes.service,"add_guest_request",_add)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/reservations/50000000-0000-4000-8000-000000000001/requests",
        headers={"Idempotency-Key":"guest-request-api-1"},
        json={"body":"Airport pickup around 9 PM"},
    )

    assert response.status_code==201
    assert captured=={
        "reservation_id":"50000000-0000-4000-8000-000000000001",
        "user_id":identity.user_id,
        "body":"Airport pickup around 9 PM",
        "key":"guest-request-api-1",
    }


class _GuestReservationConnection:
    def __init__(self):
        self.calls=[]

    def __enter__(self):
        return self
    def __exit__(self,*_args):
        return False

    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if "select r.*,p.name property_name" in sql:
            check_in=date.today()+timedelta(days=2)
            return _Result(row={
                "id":"50000000-0000-4000-8000-000000000001",
                "reference":"RYA-GUEST123",
                "user_id":"60000000-0000-4000-8000-000000000001",
                "property_name":"Example Hotel",
                "check_in_time":time(14,0),
                "room_type_name":"Deluxe",
                "rate_plan_name":"Standard",
                "refundable":True,
                "cancellation_policy":{},
                "check_in":check_in,
                "check_out":check_in+timedelta(days=2),
            })
        if "from private.reservation_notes rn" in sql:
            assert "rn.kind='guest_request'" in sql
            return _Result(rows=[
                {
                    "id":"70000000-0000-4000-8000-000000000001",
                    "body":"Late arrival",
                    "status":"open",
                    "origin":"guest",
                    "created_at":"2026-10-09 04:30",
                    "resolved_at":None,
                }
            ])
        raise AssertionError(sql)


def test_guest_reservation_payload_only_loads_guest_requests(monkeypatch):
    connection=_GuestReservationConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:connection)

    result=ReservationService().get_for_user(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
    )

    assert len(result["guest_requests"])==1
    assert result["guest_requests"][0]["body"]=="Late arrival"
    assert all("staff_note" not in sql for sql,_params in connection.calls)


def _reservation(status="confirmed"):
    check_in=date.today()+timedelta(days=2)
    return {
        "id":"50000000-0000-4000-8000-000000000001",
        "reference":"RYA-GUEST123",
        "property_name":"Example Hotel",
        "room_type_name":"Deluxe",
        "rate_plan_name":"Standard",
        "check_in":check_in,
        "check_out":check_in+timedelta(days=2),
        "nights":2,
        "adults":2,
        "children":0,
        "guest_name":"Ada Guest",
        "guest_email":"ada@example.com",
        "guest_phone":"08012345678",
        "guarantee_type":"pay_at_property",
        "status":status,
        "payment_status":"unpaid",
        "currency":"NGN",
        "total_price_minor":5000000,
        "amount_due_minor":0,
        "amount_paid_minor":0,
        "refund_status":None,
        "refund_amount_minor":None,
        "cancellation_policy_view":{
            "summary":"Free cancellation",
            "free_until":None,
            "refund_eligible":True,
        },
        "guest_requests":[
            {
                "id":"70000000-0000-4000-8000-000000000001",
                "body":"Airport pickup around 9 PM",
                "status":"open",
                "origin":"guest",
                "created_at":"2026-10-09 04:30",
                "resolved_at":None,
            },
            {
                "id":"70000000-0000-4000-8000-000000000002",
                "body":"Quiet room if available",
                "status":"resolved",
                "origin":"hotel",
                "created_at":"2026-10-09 04:40",
                "resolved_at":"2026-10-09 05:00",
            },
        ],
    }


def test_active_guest_reservation_renders_requests_and_form():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/reservation/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "guest/reservation.html",
            reservation=_reservation(),
            review=None,
        )

    assert "Special requests" in html
    assert "Airport pickup around 9 PM" in html
    assert "Sent by you" in html
    assert "Quiet room if available" in html
    assert "Recorded by the hotel" in html
    assert 'data-guest-request-form' in html
    assert "staff note" not in html.lower()


@pytest.mark.parametrize("status",["cancelled","expired","checked_out","no_show"])
def test_closed_guest_reservation_hides_request_form(status):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/reservation/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "guest/reservation.html",
            reservation=_reservation(status=status),
            review=None,
        )
    assert 'data-guest-request-form' not in html
    assert "New requests are closed" in html
