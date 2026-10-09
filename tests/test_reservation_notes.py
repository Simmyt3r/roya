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


class _NoteConnection:
    def __init__(self,error=None):
        self.error=error
        self.calls=[]
    def transaction(self):
        return _Txn()
    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if self.error:
            raise Exception(self.error)
        if "private.add_partner_reservation_note" in sql:
            return _Result({
                "note_id":"70000000-0000-4000-8000-000000000001",
                "reservation_id":"50000000-0000-4000-8000-000000000001",
                "kind":"guest_request",
                "body":"Guest arriving after 10 PM",
                "status":"open",
                "created_at":"2026-10-07 20:00",
                "idempotent":False,
            })
        if "private.resolve_partner_reservation_note" in sql:
            return _Result({
                "note_id":"70000000-0000-4000-8000-000000000001",
                "reservation_id":"50000000-0000-4000-8000-000000000001",
                "kind":"guest_request",
                "body":"Guest arriving after 10 PM",
                "status":"resolved",
                "resolved_at":"2026-10-07 21:00",
                "idempotent":False,
            })
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


class _ResolvedRequestNotifier:
    calls=[]

    def notify_guest_request_resolved(self,note_id):
        self.__class__.calls.append(note_id)
        return {"created":1}


def test_add_partner_note_calls_private_atomic_function(monkeypatch):
    connection=_NoteConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    result=ReservationService().add_partner_note(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        "guest_request",
        "Guest arriving after 10 PM",
        "reservation-note-request-1",
    )

    assert result["status"]=="open"
    sql,params=connection.calls[0]
    assert "private.add_partner_reservation_note" in sql
    assert params==(
        "60000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        "guest_request",
        "Guest arriving after 10 PM",
        "reservation-note-request-1",
    )


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","FORBIDDEN",403),
        ("INVALID_KIND","VALIDATION_ERROR",422),
        ("VALIDATION_ERROR","VALIDATION_ERROR",422),
    ],
)
def test_add_partner_note_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_NoteConnection(error=db_error)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().add_partner_note(
            "50000000-0000-4000-8000-000000000001",
            "60000000-0000-4000-8000-000000000001",
            "guest_request",
            "Late arrival",
            "reservation-note-request-2",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_resolve_partner_note_calls_private_function(monkeypatch):
    connection=_NoteConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())
    monkeypatch.setattr(reservation_service,"NotificationService",_ResolvedRequestNotifier)
    _ResolvedRequestNotifier.calls=[]

    result=ReservationService().resolve_partner_note(
        "50000000-0000-4000-8000-000000000001",
        "70000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
    )

    assert result["status"]=="resolved"
    sql,params=connection.calls[0]
    assert "private.resolve_partner_reservation_note" in sql
    assert params==(
        "60000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        "70000000-0000-4000-8000-000000000001",
    )
    assert _ResolvedRequestNotifier.calls==["70000000-0000-4000-8000-000000000001"]


def test_note_routes_forward_member_identity(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="desk@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _add(reservation_id,user_id,kind,body,key):
        captured["add"]=(reservation_id,user_id,kind,body,key)
        return {"note_id":"70000000-0000-4000-8000-000000000001","status":"open"}

    def _resolve(reservation_id,note_id,user_id):
        captured["resolve"]=(reservation_id,note_id,user_id)
        return {"note_id":note_id,"status":"resolved"}

    monkeypatch.setattr(reservation_routes.service,"add_partner_note",_add)
    monkeypatch.setattr(reservation_routes.service,"resolve_partner_note",_resolve)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    client=app.test_client()

    created=client.post(
        "/api/v1/partner/reservations/50000000-0000-4000-8000-000000000001/notes",
        headers={"Idempotency-Key":"reservation-note-api-1"},
        json={"kind":"staff_note","body":"Prepare baby cot"},
    )
    resolved=client.post(
        "/api/v1/partner/reservations/50000000-0000-4000-8000-000000000001/notes/70000000-0000-4000-8000-000000000001/resolve"
    )

    assert created.status_code==201
    assert resolved.status_code==200
    assert captured["add"][1]==identity.user_id
    assert captured["add"][2]=="staff_note"
    assert captured["resolve"][2]==identity.user_id


def _workspace(role="reservations"):
    check_in=date.today()+timedelta(days=2)
    return {
        "reservation":{
            "id":"50000000-0000-4000-8000-000000000001",
            "reference":"RYA-NOTES123",
            "property_id":"10000000-0000-4000-8000-000000000001",
            "property_name":"Example Hotel",
            "property_address":"1 Example Road",
            "property_city":"Makurdi",
            "property_state":"Benue",
            "property_country":"Nigeria",
            "property_phone":"08030000000",
            "property_email":"stay@example.com",
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
            "status":"confirmed",
            "payment_status":"unpaid",
            "currency":"NGN",
            "total_price_minor":5000000,
            "amount_paid_minor":0,
            "amount_refunded_minor":0,
            "source_channel":"front_desk",
            "member_role":role,
        },
        "items":[{
            "id":"80000000-0000-4000-8000-000000000001",
            "room_type_id":"30000000-0000-4000-8000-000000000001",
            "rate_plan_id":"40000000-0000-4000-8000-000000000001",
            "quantity":1,
            "unit_price_minor":2500000,
            "total_price_minor":5000000,
            "room_type_name":"Deluxe",
            "rate_plan_name":"Standard",
            "guarantee_type":"pay_at_property",
        }],
        "notes":[
            {
                "id":"70000000-0000-4000-8000-000000000001",
                "kind":"guest_request",
                "body":"Guest arriving after 10 PM",
                "status":"open",
                "created_by_name":"Front Desk",
                "created_at":"2026-10-07 20:00",
                "resolved_by_name":None,
                "resolved_at":None,
            },
            {
                "id":"70000000-0000-4000-8000-000000000002",
                "kind":"staff_note",
                "body":"Do not print this internal note",
                "status":"open",
                "created_by_name":"Manager",
                "created_at":"2026-10-07 20:05",
                "resolved_by_name":None,
                "resolved_at":None,
            },
            {
                "id":"70000000-0000-4000-8000-000000000003",
                "kind":"guest_request",
                "body":"Resolved airport pickup",
                "status":"resolved",
                "created_by_name":"Front Desk",
                "created_at":"2026-10-07 19:00",
                "resolved_by_name":"Manager",
                "resolved_at":"2026-10-07 20:30",
            },
        ],
        "transactions":[],
        "refunds":[],
        "audit":[],
        "assigned_rooms":[],
        "room_readiness":{"tracked":False,"ready":True,"items":[]},
    }


@pytest.mark.parametrize("role",["owner","manager","reservations","staff"])
def test_operational_roles_can_add_and_resolve_notes(role):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=_workspace(role))

    assert "Guest arriving after 10 PM" in html
    assert "Do not print this internal note" in html
    assert 'data-reservation-note-form' in html
    assert 'data-reservation-note-resolve' in html


def test_finance_can_view_but_not_edit_notes():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=_workspace("finance"))

    assert "Guest arriving after 10 PM" in html
    assert "Do not print this internal note" in html
    assert 'data-reservation-note-form' not in html
    assert 'data-reservation-note-resolve' not in html


def test_confirmation_only_shares_open_guest_requests():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001/confirmation"):
        html=render_template("partner/reservation_confirmation.html",workspace=_workspace())

    assert "Guest arriving after 10 PM" in html
    assert "Do not print this internal note" not in html
    assert "Resolved airport pickup" not in html
    assert "Guest request: Guest arriving after 10 PM" in html
