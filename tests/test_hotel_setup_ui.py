from uuid import uuid4

from flask import render_template

from roya import create_app


def _property():
    return {
        "id":str(uuid4()),
        "organization_name":"Example Hotels",
        "name":"Example Hotel",
        "city":"Makurdi",
        "state":"Benue",
        "country":"Nigeria",
        "address":"1 Example Road",
        "phone":"",
        "email":"",
        "description":"",
        "check_in_time":"14:00",
        "check_out_time":"12:00",
        "member_role":"owner",
        "verification_status":"pending",
        "status":"draft",
        "mini_domain":"example-hotel",
    }


def _room():
    return {
        "id":str(uuid4()),
        "name":"Deluxe King",
        "description":"",
        "capacity_adults":2,
        "capacity_children":0,
        "base_occupancy":1,
        "total_inventory":4,
        "bed_configuration":"1 King Bed",
        "status":"active",
        "rates":[],
        "inventory_summary":None,
        "calendar":[],
        "images":[],
    }


def test_new_hotel_setup_shows_essential_first_step():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context("/partner/properties/new"):
        html=render_template(
            "partner/property_new.html",
            organizations=[{"id":str(uuid4()),"name":"Example Hotels","role":"owner"}],
        )

    assert "Step 1 of 5" in html
    assert "Hotel details" in html
    assert "Rooms" in html
    assert "Rates" in html
    assert "Photos" in html
    assert "Publish" in html
    assert "Create hotel & continue" in html
    assert "Optional details" in html
    assert 'name="name"' in html
    assert 'name="address"' in html
    assert 'name="check_in_time"' in html


def test_property_setup_guides_owner_to_first_room():
    prop=_property()
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context(f"/partner/properties/{prop['id']}"):
        html=render_template(
            "partner/property_manage.html",
            property=prop,
            rooms=[],
            images=[],
            amenities=[],
            readiness={"ready":False,"has_room":False,"has_rate":False,"has_inventory":False},
            mini_domain_url="https://example-hotel.iroya.ng",
            can_edit_property=True,
            can_manage=True,
        )

    assert "Add your first room" in html
    assert "Add room & continue" in html
    assert "Direct hotel address" in html
    assert "Optional" in html
    assert 'id="add-room"' in html
    assert 'name="capacity_children"' in html


def test_property_setup_hides_rate_complexity_under_advanced_settings():
    prop=_property()
    room=_room()
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context(f"/partner/properties/{prop['id']}"):
        html=render_template(
            "partner/property_manage.html",
            property=prop,
            rooms=[room],
            images=[],
            amenities=[],
            readiness={"ready":False,"has_room":True,"has_rate":False,"has_inventory":False},
            mini_domain_url="https://example-hotel.iroya.ng",
            can_edit_property=True,
            can_manage=True,
        )

    assert "Add a nightly rate" in html
    assert "How should guests confirm?" in html
    assert "Advanced rate settings" in html
    assert 'name="meal_plan"' in html
    assert 'name="min_stay"' in html
    assert 'name="deposit_percent"' in html
    assert "Add rate & continue" in html


def test_property_setup_keeps_simple_availability_and_advanced_controls():
    prop=_property()
    room=_room()
    room["rates"]=[{
        "id":str(uuid4()),
        "name":"Standard",
        "guarantee_type":"pay_at_property",
        "meal_plan":"room_only",
        "currency":"NGN",
        "base_price_minor":2500000,
        "min_stay":1,
        "deposit_percent":100,
        "cancellation_policy":{"free_cancellation_hours":24},
        "refundable":True,
        "status":"active",
    }]
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    with app.test_request_context(f"/partner/properties/{prop['id']}"):
        html=render_template(
            "partner/property_manage.html",
            property=prop,
            rooms=[room],
            images=[],
            amenities=[],
            readiness={"ready":False,"has_room":True,"has_rate":True,"has_inventory":False},
            mini_domain_url="https://example-hotel.iroya.ng",
            can_edit_property=True,
            can_manage=True,
        )

    assert "Load room availability" in html
    assert "Add availability" in html
    assert "Available from" in html
    assert "Rooms available" in html
    assert "Advanced availability" in html
    assert "Pause sales for this date range" in html
    assert "Save availability" in html
