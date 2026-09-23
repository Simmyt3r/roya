import pytest
from pydantic import ValidationError
from roya.reservations.schemas import ReservationCreate

def sample(**overrides):
    data={"property_id":"11111111-1111-1111-1111-111111111111","room_type_id":"22222222-2222-2222-2222-222222222222","rate_plan_id":"33333333-3333-3333-3333-333333333333","check_in":"2026-10-01","check_out":"2026-10-03","quantity":1,"adults":2,"children":0,"guest_name":"Test Guest","guest_email":"guest@example.com","guest_phone":"+2348000000000","guarantee_type":"pay_at_property"}
    data.update(overrides); return data

def test_valid_reservation_schema():
    value=ReservationCreate.model_validate(sample()); assert (value.check_out-value.check_in).days==2

def test_rejects_reverse_dates():
    with pytest.raises(ValidationError): ReservationCreate.model_validate(sample(check_out="2026-09-30"))

def test_rejects_unknown_guarantee():
    with pytest.raises(ValidationError): ReservationCreate.model_validate(sample(guarantee_type="trust_me_bro"))
