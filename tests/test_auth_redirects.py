from urllib.parse import parse_qs,urlsplit

from roya import create_app
from roya.auth.routes import _safe_next_path


def _app():
    return create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
        "SUPABASE_URL":"",
        "SUPABASE_PUBLISHABLE_KEY":"",
    })


def test_signed_out_page_redirects_to_login_and_preserves_destination():
    client=_app().test_client()
    response=client.get("/partner?section=team&_vercel_share=internal-token")
    assert response.status_code==302

    location=response.headers["Location"]
    parsed=urlsplit(location)
    assert parsed.path=="/login"
    assert parse_qs(parsed.query)["next"]==["/partner?section=team"]


def test_signed_out_api_still_returns_json_401():
    response=_app().test_client().get("/api/v1/auth/me")
    assert response.status_code==401
    payload=response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"]=="AUTH_REQUIRED"


def test_safe_next_path_accepts_internal_routes_only():
    assert _safe_next_path("/book?room=1")=="/book?room=1"
    assert _safe_next_path("/partner#reservations")=="/partner#reservations"
    assert _safe_next_path("https://evil.example/phish") is None
    assert _safe_next_path("//evil.example/phish") is None
    assert _safe_next_path("partner") is None


def test_login_page_carries_only_safe_return_path():
    client=_app().test_client()

    safe=client.get("/login?next=%2Fbook%3Froom%3D1")
    html=safe.get_data(as_text=True)
    assert safe.status_code==200
    assert 'name="next_path" value="/book?room=1"' in html
    assert "/register?next=" in html

    unsafe=client.get("/login?next=https%3A%2F%2Fevil.example")
    unsafe_html=unsafe.get_data(as_text=True)
    assert unsafe.status_code==200
    assert 'name="next_path"' not in unsafe_html
    assert "evil.example" not in unsafe_html
