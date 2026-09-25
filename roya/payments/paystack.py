import hashlib
import hmac
from urllib.parse import quote

import requests
from flask import current_app

from roya.common.errors import RoyaError
from roya.common.integrations import paystack_settings
from .provider import PaymentProvider


class PaystackProvider(PaymentProvider):
    def __init__(self):
        self.secret=paystack_settings()["secret_key"]
        self.base_url=current_app.config.get("PAYSTACK_BASE_URL","https://api.paystack.co").rstrip("/")

    def _headers(self):
        if not self.secret:
            raise RoyaError("PAYMENT_PROVIDER_NOT_CONFIGURED","Paystack is not configured.",503)
        return {
            "Authorization":f"Bearer {self.secret}",
            "Content-Type":"application/json",
        }

    @staticmethod
    def _json_payload(response,*,error_code,error_message):
        try:
            payload=response.json()
        except (ValueError,TypeError) as exc:
            raise RoyaError(error_code,error_message,502) from exc
        if not isinstance(payload,dict):
            raise RoyaError(error_code,error_message,502)
        return payload

    def _request(self,method,path,*,json_body=None,error_code,error_message):
        try:
            response=requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=json_body,
                timeout=12,
            )
        except requests.RequestException as exc:
            raise RoyaError(
                "PAYMENT_PROVIDER_UNAVAILABLE",
                "Paystack is temporarily unreachable.",
                502,
            ) from exc

        payload=self._json_payload(
            response,
            error_code=error_code,
            error_message=error_message,
        )

        if not response.ok or payload.get("status") is not True:
            raise RoyaError(
                error_code,
                str(payload.get("message") or error_message)[:300],
                502,
            )

        data=payload.get("data")
        if not isinstance(data,dict):
            raise RoyaError(error_code,error_message,502)
        return data

    def initialize_payment(self,*,amount_minor,email,reference,callback_url,metadata):
        if int(amount_minor)<=0:
            raise RoyaError("PAYMENT_FAILED","Payment amount must be greater than zero.",422)
        data=self._request(
            "POST",
            "/transaction/initialize",
            json_body={
                "amount":int(amount_minor),
                "email":email,
                "reference":reference,
                "callback_url":callback_url,
                "metadata":metadata,
            },
            error_code="PAYMENT_FAILED",
            error_message="Payment initialization failed.",
        )
        if not data.get("authorization_url") or not data.get("access_code"):
            raise RoyaError(
                "PAYMENT_FAILED",
                "Paystack did not return a usable checkout session.",
                502,
            )
        return data

    def verify_payment(self,reference):
        if not reference:
            raise RoyaError("PAYMENT_REFERENCE_REQUIRED","Payment reference is required.",400)
        return self._request(
            "GET",
            f"/transaction/verify/{quote(str(reference),safe='')}",
            error_code="PAYMENT_VERIFICATION_FAILED",
            error_message="Payment verification failed.",
        )

    def refund_payment(self,reference,amount_minor=None):
        if not reference:
            raise RoyaError("PAYMENT_REFERENCE_REQUIRED","Payment reference is required.",400)
        body={"transaction":reference}
        if amount_minor is not None:
            if int(amount_minor)<=0:
                raise RoyaError("REFUND_FAILED","Refund amount must be greater than zero.",422)
            body["amount"]=int(amount_minor)
        return self._request(
            "POST",
            "/refund",
            json_body=body,
            error_code="REFUND_FAILED",
            error_message="Refund request failed.",
        )

    def verify_webhook(self,raw_body,signature):
        if not self.secret or not signature:
            return False
        digest=hmac.new(self.secret.encode(),raw_body,hashlib.sha512).hexdigest()
        return hmac.compare_digest(digest,signature)

    def test_connection(self):
        try:
            response=requests.get(
                f"{self.base_url}/integration/payment_session_timeout",
                headers=self._headers(),timeout=12,
            )
            payload=response.json()
        except (requests.RequestException,ValueError,TypeError) as exc:
            raise RoyaError("PAYSTACK_CONNECTION_FAILED","Paystack could not be reached.",502) from exc
        if not response.ok or not isinstance(payload,dict) or payload.get("status") is not True:
            raise RoyaError(
                "PAYSTACK_CONNECTION_FAILED",
                "Paystack rejected this key. Check the key and its mode.",502,
            )
        return True
