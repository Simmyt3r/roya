import json
from pathlib import Path

from roya import create_app


def _app():
    return create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
        "SUPABASE_URL":"",
        "SUPABASE_PUBLISHABLE_KEY":"",
        "SUPABASE_SERVICE_ROLE_KEY":"",
        "PAYSTACK_SECRET_KEY":"",
        "SMTP_HOST":"",
        "SMTP_FROM":"",
    })


def test_all_jinja_templates_compile():
    app=_app()
    templates_root=Path(app.root_path).parent/"templates"
    template_names=[
        str(path.relative_to(templates_root)).replace("\\","/")
        for path in templates_root.rglob("*.html")
    ]
    assert template_names

    with app.app_context():
        for name in template_names:
            app.jinja_env.get_template(name)


def test_auth_safe_pages_render_without_external_services():
    client=_app().test_client()
    for path in ("/","/login","/register","/register?account_type=hotel"):
        response=client.get(path)
        assert response.status_code==200, path
        assert b"iRoya" in response.data


def test_static_pwa_assets_are_served_with_expected_content():
    client=_app().test_client()

    manifest_response=client.get("/static/manifest.json")
    assert manifest_response.status_code==200
    manifest=json.loads(manifest_response.get_data(as_text=True))
    assert manifest["name"]=="iRoya"
    assert manifest["start_url"]=="/?source=pwa"
    assert manifest["scope"]=="/"
    assert manifest["display"]=="standalone"
    assert manifest["icons"]
    assert all(icon["src"].startswith("/static/") for icon in manifest["icons"])

    sw=client.get("/static/js/sw.js")
    assert sw.status_code==200
    sw_text=sw.get_data(as_text=True)
    assert "iroya-shell-v14" in sw_text
    assert "url.pathname.startsWith('/api/')" in sw_text
    assert "url.pathname.startsWith('/partner')" in sw_text

    css=client.get("/static/css/app.css")
    js=client.get("/static/js/app.js")
    logo=client.get("/static/brand/iroya-logo.svg")
    assert css.status_code==200
    assert js.status_code==200
    assert logo.status_code==200
    assert "image/svg+xml" in (logo.content_type or "")


def test_public_pages_emit_basic_security_headers():
    response=_app().test_client().get("/")
    assert response.headers["X-Content-Type-Options"]=="nosniff"
    assert response.headers["Referrer-Policy"]=="strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"]=="camera=(), microphone=(), geolocation=(self)"
    assert response.headers.get("X-Request-ID")
