from roya import create_app

def test_health_endpoint():
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    response=app.test_client().get("/health")
    assert response.status_code==200
    payload=response.get_json()
    assert payload["success"] is True
    assert payload["data"]["service"]=="roya"
