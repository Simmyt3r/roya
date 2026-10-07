from contextlib import contextmanager
from datetime import date,timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.payments import routes as payment_routes
from roya.payments import service as payment_service
from roya.payments.service import PaymentService


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


class _PaymentConnection:
    def __init__(self,row=None,error=None):
        self.row=row or {
            "transaction_id":"70000000-0000-4000-8000-000000000001",
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "provider_reference":"hotel_rya-front123_abc123",
            "amount_minor":1000000,
            "amount_paid_minor":1000000,
            "outstanding_minor":1500000,
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
        if "private.record_partner_payment" in sql:
            return _Result(self.row)
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def test_manual_partner_payment_calls_private_atomic_function(monkeypatch):
    connection=_PaymentConnection()
    monkeypatch.setattr(payment_service,"db_connection",lambda:_db(connection)())

    result=PaymentService().record_partner_payment(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        1000000,
        "bank_transfer",
        "Transfer received",
        "hotel-payment-request-1",
    )

    assert result["payment_status"]=="partially_paid"
    sql,params=connection.calls[0]
    assert "private.record_partner_payment" in sql
    assert params==(
        "60000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        1000000,
        "bank_transfer",
        "Transfer received",
        "hotel-payment-request-1",
    )


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","FORBIDDEN",403),
        ("OFFLINE_PAYMENT_SOURCE_UNSUPPORTED","OFFLINE_PAYMENT_SOURCE_UNSUPPORTED",409),
        ("RESERVATION_NOT_PAYABLE","RESERVATION_NOT_PAYABLE",409),
        ("ALREADY_PAID","ALREADY_PAID",409),
        ("OVERPAYMENT","OVERPAYMENT",422),
    ],
)
def test_manual_partner_payment_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_PaymentConnection(error=db_error)
    monkeypatch.setattr(payment_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        PaymentService().record_partner_payment(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            1000000,
            "cash",
            None,
            "hotel-payment-request-2",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_manual_partner_payment_validates_method_and_amount_before_database(monkeypatch):
    connection=_PaymentConnection()
    monkeypatch.setattr(payment_service,"db_connection",lambda:_db(connection)())
    service=PaymentService()

    with pytest.raises(RoyaError) as amount_error:
        service.record_partner_payment(
            "reservation-1","user-1",0,"cash",None,"payment-key-123"
        )
    assert amount_error.value.code=="VALIDATION_ERROR"

    with pytest.raises(RoyaError) as method_error:
        service.record_partner_payment(
            "reservation-1","user-1",1000,"crypto",None,"payment-key-123"
        )
    assert method_error.value.code=="VALIDATION_ERROR"

    assert connection.calls==[]


def test_manual_partner_payment_route_forwards_idempotency(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="finance@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(payment_routes,"current_identity",lambda required=False:identity)

    def _record(reservation_id,user_id,amount_minor,method,note,key):
        captured.update({
            "reservation_id":reservation_id,
            "user_id":user_id,
            "amount_minor":amount_minor,
            "method":method,
            "note":note,
            "key":key,
        })
        return {
            "transaction_id":"70000000-0000-4000-8000-000000000001",
            "reservation_id":reservation_id,
            "payment_status":"paid",
            "outstanding_minor":0,
        }

    monkeypatch.setattr(payment_routes.service,"record_partner_payment",_record)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/partner/reservations/50000000-0000-4000-8000-000000000001/payments",
        headers={"Idempotency-Key":"hotel-payment-api-1"},
        json={
            "amount_minor":2500000,
            "method":"pos_card",
            "note":"POS approved",
        },
    )

    assert response.status_code==201
    assert captured["user_id"]==identity.user_id
    assert captured["amount_minor"]==2500000
    assert captured["method"]=="pos_card"
    assert captured["key"]=="hotel-payment-api-1"


def _workspace(source="front_desk",role="reservations",paid=0,status="confirmed",with_tx=False):
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
        "payment_status":"paid" if paid>=2500000 else ("partially_paid" if paid else "unpaid"),
        "currency":"NGN",
        "total_price_minor":2500000,
        "amount_paid_minor":paid,
        "source_channel":source,
        "member_role":role,
    }
    transactions=[]
    if with_tx:
        transactions=[{
            "provider":"hotel",
            "provider_reference":"hotel_rya-front123_abc",
            "amount_minor":1000000,
            "currency":"NGN",
            "status":"successful",
            "method":"cash",
            "paid_at":"2026-10-07 20:00",
            "created_at":"2026-10-07 20:00",
        }]
    return {
        "reservation":reservation,
        "items":[{
            "room_type_name":"Deluxe",
            "rate_plan_name":"Standard",
            "quantity":1,
            "total_price_minor":2500000,
        }],
        "transactions":transactions,
        "refunds":[],
        "audit":[],
        "assigned_rooms":[],
        "room_readiness":{"tracked":False,"ready":True,"items":[]},
    }


@pytest.mark.parametrize("role",["owner","manager","reservations","finance"])
def test_manual_payment_form_visible_for_authorized_front_desk_booking(role):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(role=role),
        )
    assert "Record hotel payment" in html
    assert "This does not charge a card." in html
    assert "NGN 25000.00 recordable balance" in html
    assert 'data-partner-payment' in html


@pytest.mark.parametrize(
    "source,role,paid,status",
    [
        ("direct_booking","reservations",0,"confirmed"),
        ("roya_marketplace","finance",0,"confirmed"),
        ("front_desk","staff",0,"confirmed"),
        ("front_desk","reservations",2500000,"confirmed"),
        ("front_desk","reservations",0,"cancelled"),
    ],
)
def test_manual_payment_form_hidden_outside_allowed_scope(source,role,paid,status):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(source=source,role=role,paid=paid,status=status),
        )
    assert "Record hotel payment" not in html
    assert 'data-partner-payment' not in html


def test_hotel_payment_history_shows_method():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(paid=1000000,with_tx=True),
        )
    assert "Hotel" in html
    assert "Cash" in html
    assert "NGN 10000.00" in html
