from decimal import Decimal

import pytest
from flask import render_template

from roya import create_app
from roya.properties.routes import SearchQuery


@pytest.fixture
def app():
    return create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "DATABASE_URL": "",
        "SUPABASE_URL": "",
        "SUPABASE_PUBLISHABLE_KEY": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "PAYSTACK_SECRET_KEY": "",
    })


@pytest.mark.parametrize("price,expected", [
    (1250050, "From ₦12,500.50"),
    (0, "From ₦0.00"),
    (None, "Choose dates to see rates"),
])
def test_search_prices_keep_precision_and_explain_units(app, price, expected):
    hotel = {
        "slug": "test-hotel", "name": "Test Hotel", "city": "Lagos",
        "state": "Lagos", "distance_km": None, "rating": None,
        "cover_image": None, "from_price_minor": price,
    }
    with app.test_request_context("/search"):
        html = render_template(
            "public/search.html", properties=[hotel], query=SearchQuery(),
            city=None, check_in=None, check_out=None, guests=1,
        )
    assert expected in html
    assert "No reviews yet" in html
    if price is not None:
        assert "per room / night" in html


def test_empty_search_keeps_sort_visible_and_offers_recovery(app):
    with app.test_request_context("/search"):
        html = render_template(
            "public/search.html", properties=[],
            query=SearchQuery(min_price_ngn=Decimal("5000")),
            city=None, check_in=None, check_out=None, guests=1,
        )
    assert html.index('data-search-sort') < html.index('<details')
    assert 'href="#hotel-search"' in html
    assert 'href="/search">Clear all filters' in html
    assert 'role="status" aria-live="polite"' in html


def test_nested_hotel_workspace_marks_one_current_section(app):
    with app.test_request_context("/partner/reservations/example"):
        from flask import session
        session.update(sid="test-session", account_type="hotel", platform_role="user")
        html = render_template("base.html")
    assert html.count('aria-current="page"') == 1
    assert 'href="/partner/reservations" aria-current="page"' in html
    assert 'href="#main-content"' in html
    assert '<main id="main-content" tabindex="-1">' in html
