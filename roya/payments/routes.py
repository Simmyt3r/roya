from flask import Blueprint, render_template, request
from roya.auth.service import current_identity, login_required
from roya.common.response import ok
from .service import PaymentService

bp=Blueprint("payments",__name__)
service=PaymentService()


@bp.post("/api/v1/payments/initiate")
@login_required
def initiate_payment():
    body=request.get_json(silent=True) or {}
    identity=current_identity(required=True)
    return ok(service.initialize(body.get("reservation_id",""),identity.user_id,request.headers.get("Idempotency-Key","")),201)


@bp.post("/api/webhooks/paystack")
def paystack_webhook():
    return ok(service.process_paystack_webhook(request.get_data(cache=True),request.headers.get("x-paystack-signature","")))


@bp.get("/payment/callback")
def payment_callback():
    return render_template("guest/payment_callback.html")
