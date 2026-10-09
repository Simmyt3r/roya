from contextlib import contextmanager
from datetime import date,time,timedelta
from types import SimpleNamespace

from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.organizations.operations_service import build_daily_actions
from roya.reservations import routes as reservation_routes
from roya.reservations import service as reservation_service
from roya.reservations.schemas import GuestPrearrivalUpdate, PartnerPrearrivalUpdate
from roya.reservations.service import ReservationService


class _Txn:
    def __enter__(self): return self
    def __exit__(self,*_args): return False


class _Result:
    def __init__(self,row=None): self.row=row
    def fetchone(self): return self.row


class _PrearrivalConnection:
    def __init__(self):
        self.calls=[]

    def transaction(self): return _Txn()

    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if "private.upsert_guest_prearrival" in sql:
            return _Result({
                "reservation_id":"50000000-0000-4000-8000-000000000001",
                "eta_time":time(21,30),
                "arrival_details":"Bus arrives late",
                "guest_updated_at":"2026-10-09 05:00",
                "idempotent":False,
            })
        if "private.update_partner_prearrival" in sql:
            return _Result({
                "reservation_id":"50000000-0000-4000-8000-000000000001",
                "eta_time":time(21,30),
                "arrival_details":"Bus arrives late",
                "guest_details_checked":True,
                "payment_checked":True,
                "requests_reviewed":True,
                "arrival_prepared":True,
                "staff_note":"Key ready",
                "checklist_updated_at":"2026-10-09 05:05",
            })
        raise AssertionError(sql)


@contextmanager
def _db(connection):
    yield connection


class _Notifier:
    calls=[]
    def notify_prearrival_updated(self,reservation_id):
        self.__class__.calls.append(reservation_id)
        return {"created":1}


def test_guest_prearrival_uses_private_owned_function(monkeypatch):
    connection=_PrearrivalConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection))
    monkeypatch.setattr(reservation_service,"NotificationService",_Notifier)
    _Notifier.calls=[]

    payload=GuestPrearrivalUpdate(
        eta_time=time(21,30),
        arrival_details="Bus arrives late",
    )
    result=ReservationService().update_guest_prearrival(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000001",
        payload,
        "guest-prearrival-1",
    )

    assert result["eta_time"]==time(21,30)
    sql,params=connection.calls[0]
    assert "private.upsert_guest_prearrival" in sql
    assert params[0]=="60000000-0000-4000-8000-000000000001"
    assert params[1]=="50000000-0000-4000-8000-000000000001"
    assert params[2]==time(21,30)
    assert _Notifier.calls==["50000000-0000-4000-8000-000000000001"]


def test_partner_prearrival_updates_checklist(monkeypatch):
    connection=_PrearrivalConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection))

    payload=PartnerPrearrivalUpdate(
        eta_time=time(21,30),
        arrival_details="Bus arrives late",
        guest_details_checked=True,
        payment_checked=True,
        requests_reviewed=True,
        arrival_prepared=True,
        staff_note="Key ready",
    )
    result=ReservationService().update_partner_prearrival(
        "50000000-0000-4000-8000-000000000001",
        "60000000-0000-4000-8000-000000000002",
        payload,
    )

    assert result["arrival_prepared"] is True
    sql,params=connection.calls[0]
    assert "private.update_partner_prearrival" in sql
    assert params[4:8]==(True,True,True,True)


def test_prearrival_routes_forward_authenticated_identity(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="guest@example.com",
    )
    captured={}
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _guest(reservation_id,user_id,payload,key):
        captured["guest"]=(reservation_id,user_id,payload.eta_time,key)
        return {"reservation_id":reservation_id}

    def _partner(reservation_id,user_id,payload):
        captured["partner"]=(reservation_id,user_id,payload.arrival_prepared)
        return {"reservation_id":reservation_id}

    monkeypatch.setattr(reservation_routes.service,"update_guest_prearrival",_guest)
    monkeypatch.setattr(reservation_routes.service,"update_partner_prearrival",_partner)

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    client=app.test_client()
    reservation_id="50000000-0000-4000-8000-000000000001"

    guest=client.put(
        f"/api/v1/reservations/{reservation_id}/prearrival",
        headers={"Idempotency-Key":"guest-prearrival-api-1"},
        json={"eta_time":"21:30:00","arrival_details":"Late bus"},
    )
    partner=client.put(
        f"/api/v1/partner/reservations/{reservation_id}/prearrival",
        json={
            "eta_time":"21:30:00",
            "arrival_details":"Late bus",
            "guest_details_checked":True,
            "payment_checked":True,
            "requests_reviewed":True,
            "arrival_prepared":True,
            "staff_note":"Ready",
        },
    )

    assert guest.status_code==200
    assert partner.status_code==200
    assert captured["guest"][1]==identity.user_id
    assert captured["partner"][1]==identity.user_id


def _guest_reservation():
    check_in=date.today()+timedelta(days=1)
    return {
        "id":"50000000-0000-4000-8000-000000000001",
        "reference":"RYA-ETA123",
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
        "status":"confirmed",
        "payment_status":"unpaid",
        "currency":"NGN",
        "total_price_minor":5000000,
        "amount_due_minor":0,
        "amount_paid_minor":0,
        "refund_status":None,
        "refund_amount_minor":None,
        "room_readiness_tracked":True,
        "rooms_ready":False,
        "prearrival":{
            "eta_time":time(21,30),
            "arrival_details":"Bus arrives late",
            "guest_updated_at":"2026-10-09 05:00",
        },
        "guest_requests":[],
        "cancellation_policy_view":{
            "summary":"Free cancellation",
            "free_until":None,
            "refund_eligible":True,
        },
    }


def test_guest_reservation_renders_arrival_plan_and_room_signal():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/reservation/50000000-0000-4000-8000-000000000001"):
        html=render_template(
            "guest/reservation.html",
            reservation=_guest_reservation(),
            review=None,
        )

    assert "Arrival plan" in html
    assert "21:30" in html
    assert "Bus arrives late" in html
    assert "Room being prepared" in html
    assert 'data-guest-prearrival-form' in html


def test_daily_actions_surface_incomplete_arrival_preparation():
    tasks=build_daily_actions(
        {
            "pending_approvals":0,
            "overdue_arrivals":0,
            "overdue_departures":0,
            "arrivals_today":2,
            "departures_today":0,
            "refund_attention":0,
            "open_guest_requests":0,
            "prearrival_attention":2,
        },
        [],
        [],
    )
    assert any(
        task["href"]=="/partner#operations-arrivals"
        and "still need preparation" in task["title"]
        for task in tasks
    )
