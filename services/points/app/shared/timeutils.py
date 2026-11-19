from datetime import date, datetime, time, timedelta, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- weeks and days: one definition used by both domains ---

def monday_of(day: date) -> date:
    """The Monday of the week a calendar day falls in. Weeks run Monday to Sunday."""
    return day - timedelta(days=day.weekday())


def week_start_for(moment: datetime) -> date:
    """The week a moment belongs to, with weeks starting Monday 00:00 UTC."""
    return monday_of(moment.astimezone(timezone.utc).date())


def week_begins_at(week_start: date) -> datetime:
    """Monday 00:00 UTC of a week, as a moment."""
    return datetime.combine(week_start, time.min, tzinfo=timezone.utc)


def day_begins_at(moment: datetime) -> datetime:
    """00:00 UTC of the day a moment falls in."""
    return datetime.combine(moment.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc)
