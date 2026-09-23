import os
import pytest

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"),reason="requires disposable Supabase/Postgres test database")
def test_atomic_booking_requires_supabase_fixture():
    required=["ROYA_TEST_USER_ID","ROYA_TEST_PROPERTY_ID","ROYA_TEST_ROOM_TYPE_ID","ROYA_TEST_RATE_PLAN_ID"]
    missing=[key for key in required if not os.getenv(key)]
    if missing: pytest.skip("missing integration fixture IDs: "+", ".join(missing))
    from scripts.concurrency_check import run_concurrency_check
    result=run_concurrency_check()
    assert result["successes"]==1
    assert result["conflicts"]==1
