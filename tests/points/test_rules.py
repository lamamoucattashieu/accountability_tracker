from datetime import date, datetime, timedelta, timezone

import pytest

from app.points import rules

UTC = timezone.utc
WEEK = date(2026, 9, 28)                                   # Monday
SETTLES = datetime(2026, 10, 7, 0, 0, tzinfo=UTC)          # the next Wednesday 00:00 UTC
SECOND = timedelta(seconds=1)


def at(text):
    return datetime.fromisoformat(text)


# --- settlement time ---

def test_week_settles_at_week_end_plus_48_hours():
    assert rules.settles_at(WEEK) == SETTLES


@pytest.mark.parametrize(
    "now, provisional",
    [(SETTLES - SECOND, True), (SETTLES, False), (SETTLES + SECOND, False)],
)
def test_week_is_provisional_until_it_can_settle(now, provisional):
    assert rules.is_provisional(WEEK, now) is provisional


def test_no_week_is_settleable_just_before_week_end_plus_48h():
    created = at("2026-09-21T10:00:00+00:00")  # in the week before WEEK
    assert rules.settleable_weeks(created, SETTLES - SECOND) == [date(2026, 9, 21)]


def test_week_becomes_settleable_exactly_at_week_end_plus_48h():
    created = at("2026-09-21T10:00:00+00:00")
    assert rules.settleable_weeks(created, SETTLES) == [date(2026, 9, 21), WEEK]


def test_backlog_lists_every_week_since_creation_oldest_first():
    created = at("2026-09-02T10:00:00+00:00")  # a Wednesday
    assert rules.settleable_weeks(created, SETTLES + SECOND) == [
        date(2026, 8, 31), date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21), WEEK,
    ]


def test_weeks_before_the_group_existed_are_never_settleable():
    created = at("2026-10-01T10:00:00+00:00")  # during WEEK
    assert rules.settleable_weeks(created, SETTLES) == [WEEK]
    assert rules.settleable_weeks(created, SETTLES - SECOND) == []


# --- eligibility ---

def test_only_members_who_joined_before_the_week_are_eligible():
    members = [
        {"id": 1, "joined_at": "2026-09-27T23:59:59+00:00"},  # Sunday before: eligible
        {"id": 2, "joined_at": "2026-09-28T00:00:00+00:00"},  # exactly Monday 00:00: not before
        {"id": 3, "joined_at": "2026-10-01T12:00:00+00:00"},  # mid-week
    ]
    assert rules.eligible_member_ids(members, WEEK) == [1]


# --- losers ---

def test_single_lowest_scorer_loses():
    assert rules.losers({1: 3, 2: 1, 3: 2}) == [2]


def test_everyone_tied_at_the_lowest_score_shares_the_forfeit():
    assert rules.losers({1: 3, 2: 0, 3: 0}) == [2, 3]


def test_zero_score_member_can_lose():
    assert rules.losers({1: 2, 2: 0}) == [2]


@pytest.mark.parametrize(
    "scores",
    [{1: 2, 2: 2, 3: 2}, {1: 0, 2: 0}, {1: 5}, {}],
    ids=["everyone tied", "all zero", "single member", "nobody eligible"],
)
def test_nobody_loses_when_all_scores_are_equal(scores):
    assert rules.losers(scores) == []


# --- forfeit of a week ---

def forfeit(id, created_at):
    return {"id": id, "text": f"forfeit {id}", "created_at": created_at}


def test_weeks_forfeit_is_the_latest_set_before_monday():
    forfeits = [
        forfeit(1, "2026-09-20T10:00:00+00:00"),
        forfeit(2, "2026-09-25T10:00:00+00:00"),
    ]
    assert rules.forfeit_for_week(forfeits, WEEK)["id"] == 2


def test_forfeit_changed_mid_week_applies_from_next_week():
    forfeits = [
        forfeit(1, "2026-09-25T10:00:00+00:00"),
        forfeit(2, "2026-09-30T10:00:00+00:00"),  # Wednesday of WEEK
    ]
    assert rules.forfeit_for_week(forfeits, WEEK)["id"] == 1
    assert rules.forfeit_for_week(forfeits, date(2026, 10, 5))["id"] == 2


def test_forfeit_set_exactly_at_monday_midnight_is_too_late_for_that_week():
    forfeits = [forfeit(1, "2026-09-28T00:00:00+00:00")]
    assert rules.forfeit_for_week(forfeits, WEEK) is None


def test_same_second_forfeits_are_ordered_by_id():
    forfeits = [forfeit(2, "2026-09-25T10:00:00+00:00"), forfeit(1, "2026-09-25T10:00:00+00:00")]
    assert rules.forfeit_for_week(forfeits, WEEK)["id"] == 2


def test_no_forfeit_set():
    assert rules.forfeit_for_week([], WEEK) is None


# --- proof deadline and status ---

SETTLED = at("2026-10-07T09:00:00+00:00")
DUE = at("2026-10-14T09:00:00+00:00")


def test_proof_is_due_seven_days_after_settlement():
    assert rules.due_at(SETTLED) == DUE


@pytest.mark.parametrize(
    "proof_at, now, status",
    [
        (None, DUE - SECOND, "pending"),
        (None, DUE, "pending"),            # due means "by then", so not overdue yet
        (None, DUE + SECOND, "overdue"),
        (DUE - SECOND, DUE + timedelta(days=3), "submitted"),
        (DUE, DUE, "submitted"),
        (DUE + SECOND, DUE + SECOND, "late"),
    ],
)
def test_proof_status(proof_at, now, status):
    assert rules.proof_status(DUE, proof_at, now) == status
