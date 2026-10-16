import os

from roya import create_app
from roya.config import Config


def test_release_security_headers_are_present():
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
    })
    response=app.test_client().get("/login")

    assert response.status_code==200
    assert response.headers["X-Frame-Options"]=="DENY"
    assert response.headers["X-Content-Type-Options"]=="nosniff"
    assert response.headers["Cross-Origin-Opener-Policy"]=="same-origin"
    csp=response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp


def test_production_validation_rejects_missing_runtime_settings(monkeypatch):
    names=(
        "FLASK_SECRET_KEY",
        "APP_URL",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "DATABASE_URL",
        "CRON_SECRET",
    )
    for name in names:
        monkeypatch.delenv(name,raising=False)

    missing=Config.validate_production()

    assert "FLASK_SECRET_KEY" in missing
    assert "APP_URL" in missing
    assert "SUPABASE_URL" in missing
    assert "SUPABASE_PUBLISHABLE_KEY" in missing
    assert "SUPABASE_SERVICE_ROLE_KEY" in missing
    assert "DATABASE_URL" in missing
    assert "CRON_SECRET" in missing


def test_production_validation_requires_https_and_strong_secret(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY","short")
    monkeypatch.setenv("APP_URL","http://iroya.example")
    monkeypatch.setenv("SUPABASE_URL","https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY","publishable")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY","service-role")
    monkeypatch.setenv("DATABASE_URL","postgresql://example")
    monkeypatch.setenv("CRON_SECRET","cron-secret")

    invalid=Config.validate_production()

    assert "APP_URL_HTTPS" in invalid
    assert "FLASK_SECRET_KEY_STRONG" in invalid
