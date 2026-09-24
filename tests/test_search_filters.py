from flask import Flask
import pytest

from roya.common.errors import RoyaError
from roya.properties.routes import SearchQuery,_search_query


def test_search_query_supports_booking_filters():
    query=SearchQuery(
        city="Lagos",
        guests=2,
        min_price_ngn=10000,
        max_price_ngn=50000,
        refundable=True,
        meal_plan="breakfast",
        guarantee_type="pay_at_property",
        sort="price_asc",
        lat=6.5244,
        lng=3.3792,
        radius_km=10,
    )
    assert query.guests==2
    assert query.refundable is True
    assert query.radius_km==10


def test_search_query_rejects_inverted_price_range():
    app=Flask(__name__)
    with app.test_request_context("/search?min_price_ngn=50000&max_price_ngn=10000"):
        with pytest.raises(RoyaError):
            _search_query()


def test_search_query_requires_coordinate_pair():
    app=Flask(__name__)
    with app.test_request_context("/search?lat=6.5"):
        with pytest.raises(RoyaError):
            _search_query()
