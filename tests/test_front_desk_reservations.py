from contextlib import contextmanager
from datetime import date,timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import render_template

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.reservations import routes as reservation_routes
from roya.reservations import service as reservation_service
from roya.reservations.schemas import PartnerReservationCreate
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


class _OptionsConnection:
    def __init__(self,writer=True):
        self.writer=writer
        self.calls=[]

    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if "select p.id,p.name,p.city,p.state,p.organization_id,om.role" in sql:
            if not self.writer:
                return _Result(rows=[])
            return _Result(rows=[{
                "id":"10000000-0000-4000-8000-000000000001",
                "name":"Example Hotel",
                "city":"Makurdi",
                "state":"Benue",
                "organization_id":"20000000-0000-4000-8000-000000000001",
                "role":"reservations",
            }])
        if "min(i.total_inventory-i.held_inventory-i.sold_inventory)" in sql:
            return _Result(rows=[{
                "room_type_id":"30000000-0000-4000-8000-000000000001",
                "room_type_name":"Deluxe",
                "capacity_adults":2,
                "capacity_children":1,
                "rate_plan_id":"40000000-0000-4000-8000-000000000001",
                "rate_plan_name":"Standard",
                "currency":"NGN",
                "meal_plan":"room_only",
                "refundable":True,
                "guarantee_type":"pay_at_property",
                "loaded_nights":2,
                "available_rooms":3,
                "total_price_minor":5000000,
            }])
        raise AssertionError(sql)


def _db(connection):
    @contextmanager
    def _connection():
        yield connection
    return _connection


def test_front_desk_options_are_writer_scoped_and_price_from_inventory(monkeypatch):
    connection=_OptionsConnection(writer=True)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())
    check_in=date.today()+timedelta(days=2)
    check_out=check_in+timedelta(days=2)

    workspace=ReservationService().front_desk_booking_options(
        "hotel-user",
        property_id="10000000-0000-4000-8000-000000000001",
        check_in=check_in,
        check_out=check_out,
    )

    assert workspace["selected_property"]["name"]=="Example Hotel"
    assert workspace["nights"]==2
    assert workspace["options"][0]["available_rooms"]==3
    assert workspace["options"][0]["total_price_minor"]==5000000

    property_sql,_=connection.calls[0]
    assert "om.role in ('owner','manager','reservations')" in property_sql
    option_sql,option_params=connection.calls[1]
    assert "not i.stop_sell" in option_sql
    assert "i.closed_to_arrival" in option_sql
    assert "i.closed_to_departure" in option_sql
    assert option_params[2]=="10000000-0000-4000-8000-000000000001"


def test_read_only_hotel_role_cannot_open_front_desk_creator(monkeypatch):
    connection=_OptionsConnection(writer=False)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().front_desk_booking_options(
            "hotel-user",
            check_in=date.today()+timedelta(days=1),
            check_out=date.today()+timedelta(days=2),
        )
    assert raised.value.code=="FORBIDDEN"
    assert raised.value.status_code==403


class _CreateConnection:
    def __init__(self,row=None,error=None):
        self.row=row or {
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "reference":"RYA-FRONT123",
            "status":"confirmed",
            "payment_status":"unpaid",
            "total_price_minor":2500000,
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
        if "private.create_partner_reservation" in sql:
            return _Result(row=self.row)
        raise AssertionError(sql)


def _payload():
    check_in=date.today()+timedelta(days=2)
    return PartnerReservationCreate(
        property_id="10000000-0000-4000-8000-000000000001",
        room_type_id="30000000-0000-4000-8000-000000000001",
        rate_plan_id="40000000-0000-4000-8000-000000000001",
        check_in=check_in,
        check_out=check_in+timedelta(days=1),
        quantity=1,
        adults=2,
        children=0,
        guest_name="Ada Guest",
        guest_email=None,
        guest_phone="08012345678",
    )


def test_front_desk_create_uses_private_atomic_function(monkeypatch):
    connection=_CreateConnection()
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    result=ReservationService().create_for_partner(
        "60000000-0000-4000-8000-000000000001",
        _payload(),
        "frontdesk-request-1",
    )

    assert result["reference"]=="RYA-FRONT123"
    sql,params=connection.calls[0]
    assert "private.create_partner_reservation" in sql
    assert params[0]=="60000000-0000-4000-8000-000000000001"
    assert params[9]=="Ada Guest"
    assert params[10]==""
    assert params[12]=="frontdesk-request-1"


@pytest.mark.parametrize(
    "db_error,code,status",
    [
        ("FORBIDDEN","FORBIDDEN",403),
        ("BOOKING_CONFLICT","BOOKING_CONFLICT",409),
        ("CAPACITY_EXCEEDED","VALIDATION_ERROR",422),
        ("RATE_NOT_AVAILABLE","RATE_NOT_FOUND",409),
    ],
)
def test_front_desk_create_maps_database_failures(monkeypatch,db_error,code,status):
    connection=_CreateConnection(error=db_error)
    monkeypatch.setattr(reservation_service,"db_connection",lambda:_db(connection)())

    with pytest.raises(RoyaError) as raised:
        ReservationService().create_for_partner(
            "60000000-0000-4000-8000-000000000001",
            _payload(),
            "frontdesk-request-2",
        )

    assert raised.value.code==code
    assert raised.value.status_code==status


def test_front_desk_api_forwards_idempotency_key(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="desk@example.com",
    )
    captured={}

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)

    def _create(user_id,payload,key):
        captured.update({"user_id":user_id,"payload":payload,"key":key})
        return {
            "reservation_id":"50000000-0000-4000-8000-000000000001",
            "reference":"RYA-FRONT123",
            "status":"confirmed",
        }

    monkeypatch.setattr(reservation_routes.service,"create_for_partner",_create)

    check_in=date.today()+timedelta(days=2)
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().post(
        "/api/v1/partner/reservations",
        headers={"Idempotency-Key":"frontdesk-api-request-1"},
        json={
            "property_id":"10000000-0000-4000-8000-000000000001",
            "room_type_id":"30000000-0000-4000-8000-000000000001",
            "rate_plan_id":"40000000-0000-4000-8000-000000000001",
            "check_in":check_in.isoformat(),
            "check_out":(check_in+timedelta(days=1)).isoformat(),
            "quantity":1,
            "adults":1,
            "children":0,
            "guest_name":"Ada Guest",
            "guest_email":None,
            "guest_phone":"08012345678",
        },
    )

    assert response.status_code==201
    assert captured["user_id"]==identity.user_id
    assert captured["key"]=="frontdesk-api-request-1"
    assert response.get_json()["data"]["redirect_to"]=="/partner/reservations/50000000-0000-4000-8000-000000000001"


def test_new_reservation_page_renders_available_option(monkeypatch):
    identity=SimpleNamespace(
        user_id="60000000-0000-4000-8000-000000000001",
        email="desk@example.com",
    )
    check_in=date.today()+timedelta(days=1)
    workspace={
        "properties":[{
            "id":"10000000-0000-4000-8000-000000000001",
            "name":"Example Hotel",
            "role":"reservations",
        }],
        "selected_property":{
            "id":"10000000-0000-4000-8000-000000000001",
            "name":"Example Hotel",
        },
        "selected_property_id":"10000000-0000-4000-8000-000000000001",
        "check_in":check_in,
        "check_out":check_in+timedelta(days=1),
        "nights":1,
        "options":[{
            "room_type_id":"30000000-0000-4000-8000-000000000001",
            "room_type_name":"Deluxe",
            "capacity_adults":2,
            "capacity_children":1,
            "rate_plan_id":"40000000-0000-4000-8000-000000000001",
            "rate_plan_name":"Standard",
            "currency":"NGN",
            "meal_plan":"room_only",
            "refundable":True,
            "guarantee_type":"pay_at_property",
            "available_rooms":2,
            "total_price_minor":2500000,
        }],
    }
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(
        reservation_routes.service,
        "front_desk_booking_options",
        lambda *_args,**_kwargs:workspace,
    )

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        "/partner/reservations/new?property_id=10000000-0000-4000-8000-000000000001"
    )

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "For phone, WhatsApp and walk-in bookings." in html
    assert "Deluxe" in html
    assert "Confirmed immediately" in html
    assert "data-front-desk-reservation-form" in html


def test_front_desk_source_label_and_missing_email_render_cleanly():
    property_id="10000000-0000-4000-8000-000000000001"
    reservation={
        "id":"50000000-0000-4000-8000-000000000001",
        "reference":"RYA-FRONT123",
        "property_id":property_id,
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
        "status":"confirmed",
        "payment_status":"unpaid",
        "currency":"NGN",
        "total_price_minor":2500000,
        "amount_paid_minor":0,
        "source_channel":"front_desk",
        "member_role":"reservations",
    }
    workspace={
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

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/reservations/50000000-0000-4000-8000-000000000001"):
        html=render_template("partner/reservation.html",workspace=workspace)

    assert "Front desk" in html
    assert "Not provided" in html
    assert 'href="mailto:"' not in html
