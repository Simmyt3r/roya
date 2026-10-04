import os
import pytest


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="requires disposable Supabase/Postgres test database",
)
def test_final_room_concurrency_allows_exactly_one_booking():
    from scripts.concurrency_check import run_concurrency_check

    result=run_concurrency_check()
    assert result["passed"] is True
    assert result["successes"]==1
    assert result["conflicts"]==1
    assert result["fixture_cleaned"] is True
