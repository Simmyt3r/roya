from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PILOT_PROPERTY_TIMEZONE = ZoneInfo("Africa/Lagos")
DEFAULT_FREE_CANCELLATION_HOURS = 24
MAX_FREE_CANCELLATION_HOURS = 720


def _hours(policy):
    raw=(policy or {}).get("free_cancellation_hours",DEFAULT_FREE_CANCELLATION_HOURS)
    try:
        value=int(raw)
    except (TypeError,ValueError):
        value=DEFAULT_FREE_CANCELLATION_HOURS
    return max(0,min(value,MAX_FREE_CANCELLATION_HOURS))


def cancellation_policy_view(*,refundable,policy,check_in,check_in_time=None,now=None):
    policy=policy or {}
    if not refundable:
        return {
            "refundable":False,
            "refund_eligible":False,
            "free_cancellation_hours":None,
            "free_until":None,
            "summary":"Non-refundable rate.",
            "timezone":"Africa/Lagos",
        }

    hours=_hours(policy)
    clock=check_in_time or time(14,0)
    check_in_local=datetime.combine(check_in,clock).replace(tzinfo=PILOT_PROPERTY_TIMEZONE)
    cutoff_local=check_in_local-timedelta(hours=hours)

    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current=current.replace(tzinfo=timezone.utc)

    eligible=current.astimezone(timezone.utc)<=cutoff_local.astimezone(timezone.utc)
    if hours==0:
        summary="Free cancellation until check-in time."
    elif hours==1:
        summary="Free cancellation until 1 hour before check-in."
    else:
        summary=f"Free cancellation until {hours} hours before check-in."

    return {
        "refundable":True,
        "refund_eligible":eligible,
        "free_cancellation_hours":hours,
        "free_until":cutoff_local.isoformat(),
        "summary":summary,
        "timezone":"Africa/Lagos",
    }
