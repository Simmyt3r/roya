"""Focused regression checks for the guest/hotel UX refresh."""
from pathlib import Path

from flask import render_template, session

from roya import create_app


def _app():
    return create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "DATABASE_URL": "",
        "SUPABASE_URL": "",
        "SUPABASE_PUBLISHABLE_KEY": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "PAYSTACK_SECRET_KEY": "",
    })


def test_homepage_exposes_real_search_and_city_shortcuts_without_database():
    response = _app().test_client().get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'action="/search"' in html
    assert 'href="/search?city=Lagos"' in html
    assert 'href="/search?city=Abuja"' in html
    assert 'href="/search?city=Jos"' in html
    assert 'href="/static/css/ui-refresh.css"' in html


def test_hotel_dashboard_prioritizes_today_before_handover():
    template = (Path(__file__).resolve().parents[1] / "templates/partner/dashboard.html").read_text()
    assert template.index('id="operations-today"') < template.index('id="shift-handover"')
    assert 'href="/partner/reservations?tab=today"' in template
    assert 'href="/partner/housekeeping"' in template


def test_hotel_search_cards_explain_next_action_and_missing_photos():
    template = (Path(__file__).resolve().parents[1] / "templates/public/search.html").read_text()
    assert 'class="property-card-action"' in template
    assert "View hotel &amp; rooms" in template
    assert "Hotel photos coming soon" in template


def test_hotel_workspace_navigation_keeps_personal_booking_access():
    app = _app()
    with app.test_request_context("/partner/reservations/example"):
        session.update(sid="test-session", account_type="hotel", platform_role="user")
        html = render_template("base.html")
    assert 'class="hotel-workspace"' in html
    assert "Manage your hotel" in html
    assert "Personal" in html
    assert 'href="/search"' in html
    assert 'href="/account"' in html
    assert 'href="/partner/reservations" aria-current="page"' in html
    assert html.count('aria-current="page"') == 1


def test_property_page_handles_missing_reviews_and_images_honestly():
    app = _app()
    property_info = {
        "id": "hotel-1", "slug": "sample-hotel", "name": "Sample Hotel",
        "address": "1 Sample Road", "city": "Abuja", "state": "FCT",
        "description": "A convenient place to stay.",
        "check_in_time": "14:00", "check_out_time": "11:00",
    }
    with app.test_request_context("/hotels/sample-hotel"):
        html = render_template(
            "public/property.html", property=property_info, images=[],
            amenities=[], rooms=[], check_in=None, check_out=None,
            guests=1, reviews=[],
            review_summary={"average_rating": 0, "review_count": 0},
            booking_origin="https://iroya.example",
        )
    assert 'data-count="0"' in html
    assert "Hotel photos will appear here when available." in html
    assert "New on iRoya" in html
    assert "Not rated yet" in html
    assert 'data-stay-dates' in html
    assert 'id="check-availability"' in html


def test_property_gallery_has_one_primary_photo_and_accessible_alt_text():
    app = _app()
    property_info = {
        "id": "hotel-1", "slug": "sample-hotel", "name": "Sample Hotel",
        "address": "1 Sample Road", "city": "Abuja", "state": "FCT",
        "description": "A convenient place to stay.",
        "check_in_time": "14:00", "check_out_time": "11:00",
    }
    with app.test_request_context("/hotels/sample-hotel"):
        html = render_template(
            "public/property.html", property=property_info,
            images=[
                {"path": "/static/photo1.jpg", "alt_text": "Reception"},
                {"path": "/static/photo2.jpg", "alt_text": "Bedroom"},
            ],
            amenities=[], rooms=[], check_in=None, check_out=None,
            guests=1, reviews=[],
            review_summary={"average_rating": 0, "review_count": 0},
            booking_origin="https://iroya.example",
        )
    assert 'data-count="2"' in html
    assert html.count('class="property-gallery-item is-primary"') == 1
    assert 'alt="Reception"' in html
    assert 'alt="Bedroom"' in html


def test_booking_ui_exposes_step_semantics_and_typed_phone():
    from datetime import date
    app = _app()
    with app.test_request_context("/book"):
        html = render_template(
            "guest/booking.html",
            property={"id": "hotel-1", "slug": "sample-hotel", "name": "Sample Hotel"},
            room={"id": "room-1", "name": "Standard", "capacity_adults": 2, "capacity_children": 1},
            rate={
                "id": "rate-1", "name": "Flexible", "currency": "NGN",
                "total_price_minor": 2500000, "amount_due_minor": 2500000,
                "guarantee_type": "pay_now", "refundable": True,
                "cancellation_policy": {"free_cancellation_hours": 24},
            },
            check_in=date(2026, 11, 7), check_out=date(2026, 11, 9),
            nights=2, guest={"name": "Test Guest", "email": "test@example.com", "phone": ""},
        )
    assert 'aria-current="step"' in html
    assert 'type="tel" name="guest_phone"' in html
    assert "Booking summary" in html
    assert "Review payment and cancellation terms before confirming" in html
