import pytest
from pydantic import ValidationError

from roya import create_app
from roya.auth.schemas import RegisterInput
from roya.reservations.schemas import PartnerReservationStatusChange
from roya.organizations.routes import OrganizationMemberUpdate


def test_registration_defaults_to_guest_account():
    payload=RegisterInput(name="Test Guest",email="guest@example.com",password="password123")
    assert payload.account_type=="guest"


def test_registration_accepts_hotel_account():
    payload=RegisterInput(
        name="Hotel Owner",
        email="hotel@example.com",
        password="password123",
        account_type="hotel",
    )
    assert payload.account_type=="hotel"


def test_registration_rejects_unknown_account_type():
    with pytest.raises(ValidationError):
        RegisterInput(
            name="Nope",
            email="nope@example.com",
            password="password123",
            account_type="admin",
        )


@pytest.mark.parametrize("status",["checked_in","checked_out","no_show"])
def test_partner_reservation_status_schema_accepts_supported_states(status):
    assert PartnerReservationStatusChange(status=status).status==status


def test_partner_reservation_status_schema_rejects_arbitrary_state():
    with pytest.raises(ValidationError):
        PartnerReservationStatusChange(status="confirmed")


def test_hotel_registration_entry_preselects_hotel_without_database():
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
        "SUPABASE_URL":"",
        "SUPABASE_PUBLISHABLE_KEY":"",
    })
    response=app.test_client().get("/register?account_type=hotel")
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert 'value="hotel" checked' in html
    assert "Manage a hotel" in html


def test_payment_callback_does_not_expose_reservation_to_signed_out_user():
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
        "SUPABASE_URL":"",
        "SUPABASE_PUBLISHABLE_KEY":"",
    })
    response=app.test_client().get("/payment/callback?reference=example-ref")
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "Sign in to check this payment." in html
    assert "example-ref" in html


def test_hotel_team_update_accepts_operational_role_and_status():
    update=OrganizationMemberUpdate(role="reservations",status="suspended")
    assert update.role=="reservations"
    assert update.status=="suspended"


def test_hotel_team_update_rejects_owner_role():
    with pytest.raises(ValidationError):
        OrganizationMemberUpdate(role="owner",status="active")
