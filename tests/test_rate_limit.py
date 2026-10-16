from contextlib import contextmanager

import pytest
from flask import Flask

from roya.common.errors import RoyaError
from roya.common import rate_limit


class _Result:
    def __init__(self,row):
        self.row=row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self,count):
        self.count=count
        self.committed=False

    def execute(self,sql,params=None):
        if "insert into private.request_rate_limits" in sql:
            return _Result({"request_count":self.count})
        return _Result(None)

    def commit(self):
        self.committed=True


def _db(connection):
    @contextmanager
    def factory():
        yield connection
    return factory


def test_rate_limit_allows_request_at_limit(monkeypatch):
    app=Flask(__name__)
    app.config.update(
        TESTING=False,
        DATABASE_URL="postgresql://example",
        SECRET_KEY="test-secret-that-is-long-enough-for-hmac",
    )
    connection=_Connection(20)
    monkeypatch.setattr(rate_limit,"db_connection",_db(connection))
    monkeypatch.setattr(rate_limit.time,"time",lambda:1000)

    with app.test_request_context(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For":"203.0.113.10"},
    ):
        count=rate_limit.enforce_rate_limit(
            "auth.login",
            limit=20,
            window_seconds=900,
        )

    assert count==20
    assert connection.committed is True


def test_rate_limit_rejects_request_over_limit(monkeypatch):
    app=Flask(__name__)
    app.config.update(
        TESTING=False,
        DATABASE_URL="postgresql://example",
        SECRET_KEY="test-secret-that-is-long-enough-for-hmac",
    )
    connection=_Connection(21)
    monkeypatch.setattr(rate_limit,"db_connection",_db(connection))
    monkeypatch.setattr(rate_limit.time,"time",lambda:1000)

    with app.test_request_context(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For":"203.0.113.10"},
    ):
        with pytest.raises(RoyaError) as exc:
            rate_limit.enforce_rate_limit(
                "auth.login",
                limit=20,
                window_seconds=900,
            )

    assert exc.value.code=="RATE_LIMITED"
    assert exc.value.status_code==429
    assert exc.value.details["retry_after_seconds"]>0


def test_rate_limit_skips_database_in_testing(monkeypatch):
    app=Flask(__name__)
    app.config.update(TESTING=True,DATABASE_URL="postgresql://example")

    def unexpected_db():
        raise AssertionError("database should not be opened while TESTING")

    monkeypatch.setattr(rate_limit,"db_connection",unexpected_db)

    with app.test_request_context("/"):
        assert rate_limit.enforce_rate_limit("test",limit=1,window_seconds=60)==0
