from contextlib import contextmanager

from roya import create_app
from roya.marketing import service as marketing_service


class _RowResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, row=None):
        self.row = row
        self.committed = False

    def execute(self, *_args, **_kwargs):
        return _RowResult(self.row)

    def commit(self):
        self.committed = True


@contextmanager
def _connection(row=None):
    yield _Connection(row)


def test_unsubscribe_token_round_trip(monkeypatch):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "APP_URL": "https://iroya.example",
    })
    monkeypatch.setattr(
        marketing_service,
        "db_connection",
        lambda: _connection({
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "person@example.com",
            "unsubscribed_at": "2026-09-30T10:00:00+00:00",
        }),
    )

    with app.test_request_context("/"):
        token = marketing_service.create_unsubscribe_token("Person@Example.com")
        preview = marketing_service.preview_unsubscribe(token)
        result = marketing_service.unsubscribe_by_token(token)

    assert preview["masked_email"].endswith("@example.com")
    assert result["unsubscribed"] is True
    assert result["subscriber_found"] is True


def test_unsubscribe_page_rejects_tampered_token():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "WTF_CSRF_ENABLED": False,
    })
    client = app.test_client()
    response = client.get("/email/unsubscribe/not-a-valid-token")
    assert response.status_code == 400
    assert b"Link unavailable" in response.data
