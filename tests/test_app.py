from roya import create_app


def test_health_endpoint():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/health")
    assert response.status_code==200
    payload=response.get_json()
    assert payload["success"] is True
    assert payload["data"]["service"]=="iroya"
    assert payload["data"]["database_configured"] is False
    assert payload["data"]["database_reachable"] is False
    assert payload["data"]["integrations"]["payments_configured"] is False
    assert payload["data"]["integrations"]["storage_admin_configured"] is False
    assert payload["data"]["integrations"]["notifications_configured"] is False


def test_internal_cron_routes_require_secret():
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
        "CRON_SECRET":"test-cron-secret",
    })
    client=app.test_client()

    for path in (
        "/api/internal/cron/expire-holds",
        "/api/internal/cron/payment-reconcile",
        "/api/internal/cron/send-reminders",
    ):
        response=client.get(path)
        assert response.status_code==403
        payload=response.get_json()
        assert payload["success"] is False
        assert payload["error"]["code"]=="FORBIDDEN"


def test_auth_mutations_require_json():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False})
    response=app.test_client().post(
        "/api/v1/auth/login",
        data={"email":"test@example.com","password":"password123"},
    )
    assert response.status_code==415
    payload=response.get_json()
    assert payload["error"]["code"]=="UNSUPPORTED_MEDIA_TYPE"


def test_cookie_mutations_require_same_origin(monkeypatch):
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "SERVER_NAME":"localhost",
    })
    client=app.test_client()
    monkeypatch.setattr("roya.auth.routes.revoke_server_session",lambda _sid: None)

    with client.session_transaction() as sess:
        sess["sid"]="test-session-id"

    blocked=client.post("/api/v1/auth/logout",json={})
    assert blocked.status_code==403
    assert blocked.get_json()["error"]["code"]=="FORBIDDEN"

    allowed=client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Origin":"http://localhost"},
    )
    assert allowed.status_code==200
    assert allowed.get_json()["success"] is True


def test_landing_page_renders_without_database():
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "DATABASE_URL":"",
        "SUPABASE_URL":"",
        "SUPABASE_PUBLISHABLE_KEY":"",
        "SUPABASE_SERVICE_ROLE_KEY":"",
    })
    response=app.test_client().get("/")
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "A warmer way to find your" in html
    assert "data-home-search" in html
    assert 'href="/register?account_type=hotel"' in html
    assert "Pending reservation approvals" not in html
