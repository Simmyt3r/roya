import hashlib
import hmac
import requests
from flask import current_app

from roya.common.errors import RoyaError
from .provider import PaymentProvider


class PaystackProvider(PaymentProvider):
    def __init__(self):
        self.secret=current_app.config.get("PAYSTACK_SECRET_KEY","")
        self.base_url=current_app.config.get("PAYSTACK_BASE_URL","https://api.paystack.co").rstrip("/")

    def _headers(self):
        if not self.secret:
            raise RoyaError("PAYMENT_PROVIDER_NOT_CONFIGURED","Paystack is not configured.",503)
        return {"Authorization":f"Bearer {self.secret}","Content-Type":"application/json"}

    def initialize_payment(self,*,amount_minor,email,reference,callback_url,metadata):
        response=requests.post(f"{self.base_url}/transaction/initialize",headers=self._headers(),json={"amount":amount_minor,"email":email,"reference":reference,"callback_url":callback_url,"metadata":metadata},timeout=12)
        if not response.ok:
            raise RoyaError("PAYMENT_FAILED","Payment initialization failed.",502)
        payload=response.json()
        if not payload.get("status"):
            raise RoyaError("PAYMENT_FAILED",payload.get("message","Payment initialization failed."),502)
        return payload["data"]

    def verify_payment(self,reference):
        response=requests.get(f"{self.base_url}/transaction/verify/{reference}",headers=self._headers(),timeout=12)
        if not response.ok:
            raise RoyaError("PAYMENT_VERIFICATION_FAILED","Payment verification failed.",502)
        return response.json().get("data",{})

    def refund_payment(self,reference,amount_minor=None):
        body={"transaction":reference}
        if amount_minor is not None: body["amount"]=amount_minor
        response=requests.post(f"{self.base_url}/refund",headers=self._headers(),json=body,timeout=12)
        if not response.ok:
            raise RoyaError("REFUND_FAILED","Refund request failed.",502)
        return response.json().get("data",{})

    def verify_webhook(self,raw_body,signature):
        if not self.secret or not signature: return False
        digest=hmac.new(self.secret.encode(),raw_body,hashlib.sha512).hexdigest()
        return hmac.compare_digest(digest,signature)
