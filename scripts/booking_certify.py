"""Run the rollback-only PostgreSQL booking lifecycle certification.

Usage:
    DATABASE_URL=... python scripts/booking_certify.py

The SQL fixture creates a synthetic auth user, hotel, rates, inventory,
reservations and payment records inside an explicit transaction and always
ROLLBACKs. Any broken invariant raises an exception and exits non-zero.
"""

import os
from pathlib import Path

import psycopg


def run(database_url=None):
    url=database_url or os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Set TEST_DATABASE_URL or DATABASE_URL.")

    sql_path=Path(__file__).with_name("booking_lifecycle_certification.sql")
    sql=sql_path.read_text(encoding="utf-8")

    with psycopg.connect(url,autocommit=True,prepare_threshold=None) as conn:
        conn.execute(sql)

    return {
        "passed":True,
        "rollback_only":True,
        "checks":[
            "pay_now_hold_and_settlement",
            "payment_replay_idempotency",
            "deposit_partial_payment",
            "pay_at_property_confirmation",
            "cancellation_inventory_release",
            "hotel_approval_confirmation",
            "hotel_rejection_inventory_release",
        ],
    }


if __name__=="__main__":
    result=run()
    print("iRoya booking lifecycle certification: PASS")
    print("Rollback-only fixture: yes")
    for check in result["checks"]:
        print(f" - {check}")
