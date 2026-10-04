from contextlib import contextmanager
from datetime import date,timedelta
from uuid import uuid4

import pytest

from roya import create_app
from roya.common.errors import RoyaError
from roya.payments import service as payment_service
from roya.payments.service import PaymentService
from roya.reservations import service as reservation_service
from roya.reservations.service import ReservationService


class _Txn:
    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False


class _TransitionConnection:
    def __init__(self,status="confirmed",check_in=None,role="owner"):
        self.status=status
        self.check_in=check_in or date.today()
        self.role=role
        self.result=None
        self.audit_actions=[]

    def transaction(self):
        return _Txn()

    def execute(self,sql,params=None):
        if "select r.id,r.organization_id" in sql:
            self.result={
                "id":"reservation-1",
                "organization_id":"org-1",
                "property_id":"property-1",
                "reference":"RYA-TEST",
                "status":self.status,
                "check_in":self.check_in,
                "check_out":self.check_in+timedelta(days=2),
                "role":self.role,
                "today":date.today(),
            }
        elif "set status='checked_in'" in sql:
            self.status="checked_in"
            self.result={"id":"reservation-1","status":"checked_in"}
        elif "set status='checked_out'" in sql:
            self.status="checked_out"
            self.result={"id":"reservation-1","status":"checked_out"}
        elif "set status='no_show'" in sql:
            self.status="no_show"
            self.result={"id":"reservation-1","status":"no_show"}
        elif "insert into audit_logs" in sql:
            self.audit_actions.append(params[3])
            self.result=None
        return self

    def fetchone(self):
        return self.result


def _connection_context(connection):
    @contextmanager
    def context():
        yield connection
    return context


class _GuestNotifier:
    calls=[]

    def notify_guest_status(self,reservation_id,status):
        self.__class__.calls.append((reservation_id,status))
        return {"created":1}


def test_confirmed_stay_can_check_in_then_check_out(monkeypatch):
    connection=_TransitionConnection(status="confirmed",check_in=date.today())
    monkeypatch.setattr(
        reservation_service,
        "db_connection",
        lambda:_connection_context(connection)(),
    )
    _GuestNotifier.calls=[]
    monkeypatch.setattr(reservation_service,"NotificationService",_GuestNotifier)

    service=ReservationService()
    checked_in=service.partner_transition("reservation-1","hotel-user","checked_in")
    assert checked_in["status"]=="checked_in"
    assert connection.audit_actions[-1]=="reservation.checked_in"

    checked_out=service.partner_transition("reservation-1","hotel-user","checked_out")
    assert checked_out["status"]=="checked_out"
    assert connection.audit_actions[-1]=="reservation.checked_out"
    assert _GuestNotifier.calls==[
        ("reservation-1","checked_in"),
        ("reservation-1","checked_out"),
    ]


def test_stay_cannot_check_in_before_arrival(monkeypatch):
    connection=_TransitionConnection(
        status="confirmed",
        check_in=date.today()+timedelta(days=1),
    )
    monkeypatch.setattr(
        reservation_service,
        "db_connection",
        lambda:_connection_context(connection)(),
    )
    monkeypatch.setattr(reservation_service,"NotificationService",_GuestNotifier)

    with pytest.raises(RoyaError) as raised:
        ReservationService().partner_transition(
            "reservation-1","hotel-user","checked_in"
        )
    assert raised.value.code=="STAY_NOT_STARTED"
    assert raised.value.status_code==409


class _WebhookResult:
    def __init__(self,row=None):
        self.row=row

    def fetchone(self):
        return self.row


class _WebhookConnection:
    def __init__(self,state):
        self.state=state

    def transaction(self):
        return _Txn()

    def execute(self,sql,params=None):
        if "insert into payment_webhook_events" in sql:
            fingerprint=params[0]
            if fingerprint in self.state["events"]:
                return _WebhookResult(None)
            self.state["events"].add(fingerprint)
            return _WebhookResult({"id":str(uuid4())})
        if "update payment_webhook_events" in sql:
            return _WebhookResult(None)
        raise AssertionError("Unexpected webhook SQL: "+sql)


def _webhook_db(state):
    @contextmanager
    def context():
        yield _WebhookConnection(state)
    return context


class _WebhookProvider:
    def verify_webhook(self,_raw_body,_signature):
        return True


class _PaymentNotifier:
    calls=[]

    def notify_payment_success(self,reservation_id):
        self.__class__.calls.append(reservation_id)
        return {"created":1}


def test_paystack_webhook_exact_replay_is_idempotent(monkeypatch):
    state={"events":set(),"settlements":0}
    reservation_id=str(uuid4())

    monkeypatch.setattr(
        payment_service,
        "db_connection",
        lambda:_webhook_db(state)(),
    )
    monkeypatch.setattr(payment_service,"PaystackProvider",_WebhookProvider)
    monkeypatch.setattr(payment_service,"NotificationService",_PaymentNotifier)

    def fake_settlement(_conn,reference,data):
        state["settlements"]+=1
        assert reference=="paystack-cert-ref"
        assert data["amount"]==5000000
        return {
            "reservation_id":reservation_id,
            "reservation_status":"confirmed",
            "payment_status":"paid",
        }

    monkeypatch.setattr(
        PaymentService,
        "_record_successful_payment",
        staticmethod(fake_settlement),
    )
    _PaymentNotifier.calls=[]

    raw=b'{"event":"charge.success","data":{"reference":"paystack-cert-ref","amount":5000000}}'
    service=PaymentService()

    first=service.process_paystack_webhook(raw,"signature")
    second=service.process_paystack_webhook(raw,"signature")

    assert first["processed"] is True
    assert second=={"duplicate":True}
    assert state["settlements"]==1
    assert _PaymentNotifier.calls==[reservation_id]


def test_booking_health_endpoint_has_release_gate_shape(monkeypatch):
    from roya.properties import routes as property_routes

    monkeypatch.setattr(property_routes,"booking_readiness_snapshot",lambda:{
        "database_configured":True,
        "database_reachable":True,
        "core_ready":True,
        "release_ready":True,
        "booking_ready":True,
        "core_blockers":[],
        "release_blockers":[],
        "blockers":[],
        "deferred":[],
        "schema":{
            "create_reservation":True,
            "record_successful_payment":True,
            "cancel_reservation":True,
            "expire_reservation_holds":True,
            "partner_decide_reservation":True,
        },
        "integrations":{
            "payments_configured":True,
            "notifications_configured":True,
            "storage_admin_configured":True,
        },
        "operations":{
            "inventory_anomalies":0,
            "operations_scan_active":True,
        },
        "activity":{},
    })
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False})
    response=app.test_client().get("/health")
    assert response.status_code==200
    data=response.get_json()["data"]
    assert data["core_ready"] is True
    assert data["release_ready"] is True
    assert data["booking_ready"] is True
    assert data["deferred"]==[]
    assert data["checks"]=={
        "booking_schema_ready":True,
        "inventory_consistent":True,
        "operations_scan_active":True,
    }
