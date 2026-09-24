from flask import Blueprint, render_template, request
from roya.auth.service import current_identity, login_required
from roya.common.errors import RoyaError
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


@bp.get("/api/v1/payments/verify")
@login_required
def verify_payment():
    identity=current_identity(required=True)
    return ok(service.verify_and_reconcile(request.args.get("reference",""),identity.user_id))


@bp.post("/api/webhooks/paystack")
def paystack_webhook():
    return ok(service.process_paystack_webhook(request.get_data(cache=True),request.headers.get("x-paystack-signature","")))


@bp.get("/payment/callback")
def payment_callback():
    identity=current_identity(required=False)
    reference=(request.args.get("reference") or request.args.get("trxref") or "").strip()
    if not identity:
        return render_template("guest/payment_callback.html",state="login_required",reference=reference,result=None,error=None)
    if not reference:
        return render_template("guest/payment_callback.html",state="error",reference=None,result=None,error="Paystack did not return a payment reference.")
    try:
        result=service.verify_and_reconcile(reference,identity.user_id)
        return render_template("guest/payment_callback.html",state="confirmed" if result.get("verified") else "pending",reference=reference,result=result,error=None)
    except RoyaError as exc:
        return render_template("guest/payment_callback.html",state="error",reference=reference,result=None,error=exc.message),exc.status_code
