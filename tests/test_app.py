from roya import create_app


def test_health_endpoint():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/health")
    assert response.status_code==200
    payload=response.get_json()
    assert payload["success"] is True
    assert payload["data"]["service"]=="roya"


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
