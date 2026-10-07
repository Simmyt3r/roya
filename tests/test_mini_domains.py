from contextlib import contextmanager

import pytest

from roya import create_app
from roya.common.domains import (
    mini_domain_url, normalize_mini_domain, property_subdomain_from_host,
)
from roya.common.errors import RoyaError
from roya.properties import routes as property_routes
from roya.reservations import service as reservation_service
from roya.reservations.service import ReservationService


def test_normalize_mini_domain_makes_dns_safe_label():
    app=create_app({"TESTING":True,"HOTEL_DOMAIN_BASE":"iroya.ng","DATABASE_URL":""})
    with app.app_context():
        assert normalize_mini_domain("Royal Palm Hotel Ikeja")=="royal-palm-hotel-ikeja"
        assert mini_domain_url("royal-palm-hotel-ikeja")=="https://royal-palm-hotel-ikeja.iroya.ng"


def test_reserved_mini_domains_are_rejected():
    app=create_app({"TESTING":True,"HOTEL_DOMAIN_BASE":"iroya.ng","DATABASE_URL":""})
    with app.app_context():
        with pytest.raises(RoyaError) as raised:
            normalize_mini_domain("admin")
        assert raised.value.code=="MINI_DOMAIN_RESERVED"


def test_property_subdomain_only_accepts_one_hotel_label():
    app=create_app({"TESTING":True,"HOTEL_DOMAIN_BASE":"iroya.ng","DATABASE_URL":""})
    with app.app_context():
        assert property_subdomain_from_host("royal-palm.iroya.ng")=="royal-palm"
        assert property_subdomain_from_host("royal-palm.iroya.ng:443")=="royal-palm"
        assert property_subdomain_from_host("iroya.ng") is None
        assert property_subdomain_from_host("www.iroya.ng") is None
        assert property_subdomain_from_host("admin.iroya.ng") is None
        assert property_subdomain_from_host("a.b.iroya.ng") is None
        assert property_subdomain_from_host("royal-palm.example.com") is None


class _Lookup:
    def __init__(self,slug=None):
        self.slug=slug

    def execute(self,*_args,**_kwargs):
        return self

    def fetchone(self):
        return {"slug":self.slug} if self.slug else None


@contextmanager
def _domain_lookup(slug=None):
    yield _Lookup(slug)


def test_verified_hotel_subdomain_dispatches_to_property_page(monkeypatch):
    monkeypatch.setattr(
        property_routes,
        "db_connection",
        lambda:_domain_lookup("royal-palm-hotel-abc123"),
    )
    monkeypatch.setattr(
        property_routes,
        "property_page",
        lambda slug:f"HOTEL:{slug}",
    )
    app=create_app({
        "TESTING":True,
        "HOTEL_DOMAIN_BASE":"iroya.ng",
        "DATABASE_URL":"",
    })
    response=app.test_client().get("/",base_url="https://royal-palm.iroya.ng")
    assert response.status_code==200
    assert response.get_data(as_text=True)=="HOTEL:royal-palm-hotel-abc123"


def test_unknown_hotel_subdomain_returns_not_found(monkeypatch):
    monkeypatch.setattr(
        property_routes,
        "db_connection",
        lambda:_domain_lookup(None),
    )
    app=create_app({
        "TESTING":True,
        "HOTEL_DOMAIN_BASE":"iroya.ng",
        "DATABASE_URL":"",
    })
    response=app.test_client().get("/",base_url="https://missing-hotel.iroya.ng")
    assert response.status_code==404
    assert response.get_json()["error"]["code"]=="PROPERTY_NOT_FOUND"


class _SourceLookup:
    def __init__(self,matched):
        self.matched=matched

    def execute(self,*_args,**_kwargs):
        return self

    def fetchone(self):
        return {"ok":1} if self.matched else None


@contextmanager
def _source_lookup(matched):
    yield _SourceLookup(matched)


def test_main_iroya_host_is_marketplace_booking_source():
    app=create_app({"TESTING":True,"HOTEL_DOMAIN_BASE":"iroya.ng","DATABASE_URL":""})
    with app.app_context():
        assert ReservationService().source_channel_for_request(
            "20000000-0000-4000-8000-000000000001",
            "iroya.ng",
        )=="roya_marketplace"


def test_matching_hotel_subdomain_is_direct_booking_source(monkeypatch):
    monkeypatch.setattr(
        reservation_service,
        "db_connection",
        lambda:_source_lookup(True),
    )
    app=create_app({"TESTING":True,"HOTEL_DOMAIN_BASE":"iroya.ng","DATABASE_URL":""})
    with app.app_context():
        assert ReservationService().source_channel_for_request(
            "20000000-0000-4000-8000-000000000001",
            "royal-palm.iroya.ng",
        )=="direct_booking"


def test_hotel_subdomain_cannot_book_another_property(monkeypatch):
    monkeypatch.setattr(
        reservation_service,
        "db_connection",
        lambda:_source_lookup(False),
    )
    app=create_app({"TESTING":True,"HOTEL_DOMAIN_BASE":"iroya.ng","DATABASE_URL":""})
    with app.app_context():
        with pytest.raises(RoyaError) as raised:
            ReservationService().source_channel_for_request(
                "20000000-0000-4000-8000-000000000001",
                "wrong-hotel.iroya.ng",
            )
        assert raised.value.code=="PROPERTY_HOST_MISMATCH"
        assert raised.value.status_code==409
