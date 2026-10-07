from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

from roya import create_app
from roya.auth import service as auth_service
from roya.organizations import routes as organization_routes
from roya.reservations import routes as reservation_routes


class _Result:
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


def test_booking_page_shows_exact_stay_total_and_deposit_due(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="ada@example.com")
    room_id=str(uuid4())
    rate_id=str(uuid4())
    property_id=str(uuid4())
    captured=[]

    room_rate={
        "id":room_id,
        "name":"Deluxe King",
        "capacity_adults":2,
        "capacity_children":1,
        "property_name":"Example Hotel",
        "property_id":property_id,
        "property_slug":"example-hotel",
        "rate_id":rate_id,
        "rate_name":"Flexible",
        "base_price_minor":2500000,
        "currency":"NGN",
        "guarantee_type":"deposit",
        "refundable":True,
        "cancellation_policy":{"free_cancellation_hours":24},
        "deposit_percent":50,
        "rate_min_stay":1,
    }

    class _Connection:
        def execute(self,sql,params):
            captured.append((sql,params))
            if "from room_types rt" in sql:
                return _Result(row=room_rate)
            if "from profiles" in sql:
                return _Result(row={"name":"Ada Guest","phone":"08012345678"})
            if "from inventory_days i" in sql:
                return _Result(row={
                    "total_nights":2,
                    "sellable_nights":2,
                    "total_price_minor":6000000,
                })
            raise AssertionError(sql)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(reservation_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr("roya.common.db.db_connection",lambda:_connection())
    monkeypatch.setattr(
        reservation_routes.service,
        "source_channel_for_request",
        lambda property_id,host:"roya_marketplace",
    )

    check_in=date.today()+timedelta(days=7)
    check_out=check_in+timedelta(days=2)
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get(
        f"/book?room_type_id={room_id}&rate_plan_id={rate_id}"
        f"&check_in={check_in.isoformat()}&check_out={check_out.isoformat()}"
    )

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "NGN 60000.00" in html
    assert "NGN 30000.00 due now" in html
    assert "Pay a 50% deposit now." in html
    assert "Continue to payment" in html
    assert f"/hotels/example-hotel?check_in={check_in.isoformat()}&amp;check_out={check_out.isoformat()}" in html

    availability_sql=next(sql for sql,_ in captured if "from inventory_days i" in sql)
    assert "left join daily_rates dr" in availability_sql
    assert "coalesce(dr.price_minor,i.price_override_minor,%s)" in availability_sql


def test_booking_page_plain_language_for_pay_at_property(monkeypatch):
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/book"):
        from flask import render_template
        html=render_template(
            "guest/booking.html",
            property={"id":"property-1","name":"Example Hotel","slug":"example-hotel"},
            room={"id":"room-1","name":"Standard Room","capacity_adults":2,"capacity_children":0},
            rate={
                "id":"rate-1",
                "name":"Standard",
                "currency":"NGN",
                "total_price_minor":5000000,
                "amount_due_minor":0,
                "guarantee_type":"pay_at_property",
                "refundable":True,
                "cancellation_policy":{"free_cancellation_hours":24},
                "deposit_percent":0,
            },
            check_in=date.today()+timedelta(days=7),
            check_out=date.today()+timedelta(days=9),
            nights=2,
            guest={"name":"","email":"","phone":""},
        )

    assert "No online payment is required now. Pay at the hotel." in html
    assert "Confirm reservation" in html
    assert "stored daily rates" not in html
    assert "guarantee type" not in html.lower()


def test_partner_settings_route_loads_team_and_properties(monkeypatch):
    identity=SimpleNamespace(user_id=str(uuid4()),email="owner@example.com")
    organization_id=str(uuid4())
    property_id=str(uuid4())
    teammate_id=str(uuid4())

    class _Connection:
        def execute(self,sql,params):
            if "select o.id,o.name,o.slug,om.role" in sql:
                return _Result(rows=[{
                    "id":organization_id,
                    "name":"Example Hotels",
                    "slug":"example-hotels",
                    "role":"owner",
                }])
            if "select p.id,p.name,p.city,o.name organization_name" in sql:
                return _Result(rows=[{
                    "id":property_id,
                    "name":"Example Hotel",
                    "city":"Makurdi",
                    "organization_name":"Example Hotels",
                }])
            if "join auth.users u" in sql and "organization_invites" not in sql:
                return _Result(rows=[{
                    "organization_id":organization_id,
                    "organization_name":"Example Hotels",
                    "user_id":teammate_id,
                    "role":"reservations",
                    "status":"active",
                    "name":"Desk User",
                    "email":"desk@example.com",
                    "actor_role":"owner",
                }])
            if "from organization_invites oi" in sql:
                return _Result(rows=[])
            raise AssertionError(sql)

    @contextmanager
    def _connection():
        yield _Connection()

    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(organization_routes,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(organization_routes,"account_type_for_user",lambda user_id:"hotel")
    monkeypatch.setattr(organization_routes,"db_connection",lambda:_connection())

    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/partner/settings")

    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "Hotel team" in html
    assert "Desk User" in html
    assert "What each role can do" in html
    assert f'/partner/properties/{property_id}' in html
    assert "Add or invite teammate" in html


def test_hotel_navigation_uses_settings_workspace():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner"):
        from flask import render_template, session
        session["sid"]="session-1"
        session["account_type"]="hotel"
        html=render_template("base.html")

    assert 'href="/partner/settings">Settings</a>' in html
    assert 'href="/partner#team">Settings</a>' not in html
