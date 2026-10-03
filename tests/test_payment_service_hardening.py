from contextlib import contextmanager

from flask import Flask
import pytest

from roya.common.errors import RoyaError
from roya.payments import service as payment_service
from roya.payments.service import PaymentService


class _BrokenSettlementConnection:
    def __init__(self,message):
        self.message=message

    def execute(self,*_args,**_kwargs):
        raise Exception(self.message)


@pytest.mark.parametrize(
    ("database_error","expected_code"),
    [
        ("BOOKING_CONFLICT","PAYMENT_INVENTORY_CONFLICT"),
        ("PAYMENT_AMOUNT_MISMATCH","PAYMENT_AMOUNT_MISMATCH"),
        ("RESERVATION_NOT_PAYABLE","RESERVATION_NOT_PAYABLE"),
        ("PAYMENT_REFERENCE_NOT_FOUND","PAYMENT_NOT_FOUND"),
    ],
)
def test_payment_settlement_maps_database_invariants(database_error,expected_code):
    with pytest.raises(RoyaError) as exc:
        PaymentService._record_successful_payment(
            _BrokenSettlementConnection(database_error),
            "roya-example",
            {"amount":10000},
        )
    assert exc.value.code==expected_code


class _RowsResult:
    def __init__(self,rows):
        self.rows=rows

    def fetchall(self):
        return self.rows


class _ReconcileConnection:
    def execute(self,*_args,**_kwargs):
        return _RowsResult([
            {"provider_reference":"bad-reference"},
            {"provider_reference":"still-pending"},
        ])


@contextmanager
def _reconcile_connection():
    yield _ReconcileConnection()


class _Provider:
    def verify_payment(self,reference):
        if reference=="bad-reference":
            raise RoyaError("PAYMENT_PROVIDER_UNAVAILABLE","temporary provider failure",502)
        return {"status":"pending"}


def test_reconciliation_continues_after_one_provider_failure(monkeypatch):
    monkeypatch.setattr(payment_service,"db_connection",lambda:_reconcile_connection())
    monkeypatch.setattr(payment_service,"PaystackProvider",lambda:_Provider())

    app=Flask(__name__)
    with app.app_context():
        result=PaymentService().reconcile_pending()

    assert result=={
        "checked":2,
        "reconciled":0,
        "pending":1,
        "errors":1,
    }
