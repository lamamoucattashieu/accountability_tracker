from datetime import date, datetime, timedelta, timezone

import pytest

from app.points import rules

UTC = timezone.utc
MADRID_SUMMER = timezone(timedelta(hours=2))


@pytest.mark.parametrize(
    "day, monday",
    [
        (date(2026, 9, 28), date(2026, 9, 28)),  # Monday is its own week start
        (date(2026, 10, 1), date(2026, 9, 28)),  # Thursday
        (date(2026, 10, 4), date(2026, 9, 28)),  # Sunday is the last day of the week
        (date(2026, 10, 5), date(2026, 10, 5)),  # next Monday starts a new week
        (date(2027, 1, 1), date(2026, 12, 28)),  # weeks cross year boundaries
    ],
)
def test_monday_of(day, monday):
    assert rules.monday_of(day) == monday


def test_last_second_of_sunday_belongs_to_the_old_week():
    moment = datetime(2026, 10, 4, 23, 59, 59, tzinfo=UTC)
    assert rules.week_start_for(moment) == date(2026, 9, 28)


def test_monday_midnight_utc_starts_the_new_week():
    moment = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)
    assert rules.week_start_for(moment) == date(2026, 10, 5)


def test_week_boundary_is_utc_not_local_time():
    # 01:30 on Monday in Madrid is still 23:30 on Sunday in UTC.
    moment = datetime(2026, 10, 5, 1, 30, tzinfo=MADRID_SUMMER)
    assert rules.week_start_for(moment) == date(2026, 9, 28)
