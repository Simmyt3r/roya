import hashlib,hmac
from roya import create_app
from roya.payments.paystack import PaystackProvider

def test_paystack_signature_validation():
    secret="test-secret"
    app=create_app({"TESTING":True,"PAYSTACK_SECRET_KEY":secret,"WTF_CSRF_ENABLED":False})
    body=b'{"event":"charge.success"}'
    signature=hmac.new(secret.encode(),body,hashlib.sha512).hexdigest()
    with app.app_context():
        provider=PaystackProvider()
        assert provider.verify_webhook(body,signature)
        assert not provider.verify_webhook(body,"wrong")
