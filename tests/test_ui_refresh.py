"""Focused regression checks for the guest/hotel UX refresh."""
from pathlib import Path

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
