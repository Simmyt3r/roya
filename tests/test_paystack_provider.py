import hashlib
import hmac

import pytest
import requests

from roya import create_app
from roya.common.errors import RoyaError
from roya.payments.paystack import PaystackProvider


class FakeResponse:
    def __init__(self,*,ok=True,payload=None,json_error=None):
        self.ok=ok
        self._payload=payload
        self._json_error=json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


@pytest.fixture()
def paystack_app():
    return create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "PAYSTACK_SECRET_KEY":"sk_test_example",
        "PAYSTACK_BASE_URL":"https://api.paystack.example",
    })


def test_paystack_webhook_signature_accepts_exact_hmac(paystack_app):
    raw=b'{"event":"charge.success"}'
    signature=hmac.new(b"sk_test_example",raw,hashlib.sha512).hexdigest()
    with paystack_app.app_context():
        assert PaystackProvider().verify_webhook(raw,signature) is True
        tampered=("0" if signature[0]!="0" else "1")+signature[1:]\n        assert PaystackProvider().verify_webhook(raw,tampered) is False


def test_paystack_initialize_requires_checkout_fields(paystack_app,monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *args,**kwargs: FakeResponse(
            ok=True,
            payload={"status":True,"data":{"reference":"ref-1"}},
        ),
    )
    with paystack_app.app_context(),pytest.raises(RoyaError) as exc:
        PaystackProvider().initialize_payment(
            amount_minor=10000,
            email="guest@example.com",
            reference="ref-1",
            callback_url="https://iroya.example/payment/callback",
            metadata={},
        )
    assert exc.value.code=="PAYMENT_FAILED"
    assert exc.value.status_code==502


def test_paystack_malformed_json_becomes_provider_error(paystack_app,monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *args,**kwargs: FakeResponse(
            ok=True,
            json_error=ValueError("bad json"),
        ),
    )
    with paystack_app.app_context(),pytest.raises(RoyaError) as exc:
        PaystackProvider().verify_payment("ref-1")
    assert exc.value.code=="PAYMENT_VERIFICATION_FAILED"
    assert exc.value.status_code==502


def test_paystack_network_failure_is_normalized(paystack_app,monkeypatch):
    def fail(*args,**kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests,"request",fail)

    with paystack_app.app_context(),pytest.raises(RoyaError) as exc:
        PaystackProvider().verify_payment("ref-1")
    assert exc.value.code=="PAYMENT_PROVIDER_UNAVAILABLE"
    assert exc.value.status_code==502


def test_paystack_false_provider_status_uses_provider_error(paystack_app,monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *args,**kwargs: FakeResponse(
            ok=True,
            payload={"status":False,"message":"Provider declined request","data":{}},
        ),
    )
    with paystack_app.app_context(),pytest.raises(RoyaError) as exc:
        PaystackProvider().refund_payment("ref-1",10000)
    assert exc.value.code=="REFUND_FAILED"
    assert "declined" in exc.value.message.lower()
