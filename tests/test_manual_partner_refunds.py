from contextlib import contextmanager
from datetime import date,timedelta
from types import SimpleNamespace

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


class _RefundConnection:
    def __init__(self,row=None,error=None):
        self.row=row or {
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "refund_reference":"hotel_ref_rya-front123_abc123",
            "amount_minor":1000000,
            "total_refunded_minor":1000000,
            "net_paid_minor":1500000,
            "payment_status":"partially_refunded",
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
        if "private.record_partner_refund" in sql:
            return _Result(self.row)
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def test_manual_partner_refund_calls_private_atomic_function(monkeypatch):
    connection=_RefundConnection()
    monkeypatch.setattr(payment_service,"db_connection",lambda:_db(connection)())

    result=PaymentService().record_partner_refund(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        1000000,
        "bank_transfer",
        "Guest cancelled one night",
        "hotel-refund-request-1",
    )

    assert result["net_paid_minor"]==1500000
    sql,params=connection.calls[0]
    assert "private.record_partner_refund" in sql
    assert params==(
        "60000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        1000000,
        "bank_transfer",
        "Guest cancelled one night",
        "hotel-refund-request-1",
    )


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","FORBIDDEN",403),
        ("OFFLINE_REFUND_SOURCE_UNSUPPORTED","OFFLINE_REFUND_SOURCE_UNSUPPORTED",409),
        ("RESERVATION_NOT_REFUNDABLE","RESERVATION_NOT_REFUNDABLE",409),
        ("NO_HOTEL_PAYMENT","NO_HOTEL_PAYMENT",409),
        ("OVERREFUND","OVERREFUND",422),
        ("REFUND_ALLOCATION_FAILED","REFUND_ALLOCATION_FAILED",409),
    ],
)
def test_manual_partner_refund_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_RefundConnection(error=db_error)
    monkeypatch.setattr(payment_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        PaymentService().record_partner_refund(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            1000000,
            "cash",
            "Returned at reception",
            "hotel-refund-request-2",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_manual_partner_refund_route_forwards_idempotency(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="finance@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(payment_routes,"current_identity",lambda required=False:identity)

    def _record(reservation_id,user_id,amount_minor,method,reason,key):
        captured.update({
            "reservation_id":reservation_id,
            "user_id":user_id,
            "amount_minor":amount_minor,
            "method":method,
            "reason":reason,
            "key":key,
        })
        return {
            "reservation_id":reservation_id,
            "refund_reference":"hotel_ref_123",
            "payment_status":"partially_refunded",
        }

    monkeypatch.setattr(payment_routes.service,"record_partner_refund",_record)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/partner/reservations/50000000-0000-4000-8000-000000000001/refunds",
        headers={"Idempotency-Key":"hotel-refund-api-1"},
        json={
            "amount_minor":1000000,
            "method":"cash",
            "reason":"Returned at reception",
        },
    )

    assert response.status_code==201
    assert captured["user_id"]==identity.user_id
    assert captured["amount_minor"]==1000000
    assert captured["method"]=="cash"
    assert captured["key"]=="hotel-refund-api-1"


def _workspace(role="owner",source="front_desk",paid=2500000,refunded=0,status="confirmed"):
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
        "payment_status":"partially_refunded" if refunded else "paid",
        "currency":"NGN",
        "total_price_minor":2500000,
        "amount_paid_minor":paid,
        "amount_refunded_minor":refunded,
        "source_channel":source,
        "member_role":role,
    }
    refunds=[]
    if refunded:
        refunds=[{
            "amount_minor":refunded,
            "currency":"NGN",
            "status":"successful",
            "reason":"Returned at reception",
            "method":"cash",
            "provider_reference":"hotel_ref_123_1",
            "created_at":"2026-10-07 20:00",
            "updated_at":"2026-10-07 20:00",
        }]
    return {
        "reservation":reservation,
        "items":[{
            "room_type_name":"Deluxe",
            "rate_plan_name":"Standard",
            "quantity":1,
            "total_price_minor":2500000,
        }],
        "transactions":[{
            "provider":"hotel",
            "provider_reference":"hotel_rya-front123_abc",
            "amount_minor":paid,
            "currency":"NGN",
            "status":"partially_refunded" if refunded else "successful",
            "method":"cash",
            "paid_at":"2026-10-07 19:00",
            "created_at":"2026-10-07 19:00",
        }],
        "refunds":refunds,
        "audit":[],
        "assigned_rooms":[],
        "room_readiness":{"tracked":False,"ready":True,"items":[]},
    }


@pytest.mark.parametrize("role",["owner","manager","finance"])
def test_manual_refund_form_visible_to_financial_roles(role):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=_workspace(role=role))
    assert "Record returned money" in html
    assert "iRoya records the refund; it does not move funds." in html
    assert 'data-partner-refund' in html


@pytest.mark.parametrize("role",["reservations","staff"])
def test_manual_refund_form_hidden_from_non_financial_roles(role):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=_workspace(role=role))
    assert "Record returned money" not in html
    assert 'data-partner-refund' not in html


def test_refund_updates_net_collected_and_reopens_recordable_balance():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(role="owner",refunded=1000000),
        )

    assert "Gross collected" in html
    assert "NGN 25000.00" in html
    assert "NGN 10000.00" in html
    assert "NGN 15000.00" in html
    assert "NGN 10000.00 recordable balance" in html
    assert "Successful · Cash" in html


def test_manual_refund_form_hidden_for_non_front_desk_source():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "partner/reservation.html",
            workspace=_workspace(source="direct_booking"),
        )
    assert "Record returned money" not in html
