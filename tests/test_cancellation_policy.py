from datetime import date, datetime, time, timezone

from roya.reservations.policy import cancellation_policy_view


def test_refundable_rate_is_eligible_before_cutoff():
    view=cancellation_policy_view(
        refundable=True,
        policy={"free_cancellation_hours":24},
        check_in=date(2026,10,10),
        check_in_time=time(14,0),
        now=datetime(2026,10,8,12,0,tzinfo=timezone.utc),
    )
    assert view["refund_eligible"] is True
    assert view["free_cancellation_hours"]==24


def test_refundable_rate_closes_after_cutoff():
    view=cancellation_policy_view(
        refundable=True,
        policy={"free_cancellation_hours":24},
        check_in=date(2026,10,10),
        check_in_time=time(14,0),
        now=datetime(2026,10,9,14,0,tzinfo=timezone.utc),
    )
    assert view["refund_eligible"] is False


def test_non_refundable_rate_never_allows_automatic_refund():
    view=cancellation_policy_view(
        refundable=False,
        policy={"free_cancellation_hours":24},
        check_in=date(2026,10,10),
        check_in_time=time(14,0),
        now=datetime(2026,10,1,12,0,tzinfo=timezone.utc),
    )
    assert view["refund_eligible"] is False
    assert view["free_until"] is None
    assert view["summary"]=="Non-refundable rate."
