from datetime import datetime, timedelta, timezone

import pytest

from app.checkins import repository, service
from app.db import get_db
from app.points import service as points_service
from tests.factories import make_group, make_user
from tests.images import image_file

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


# --- pure rule functions ---

@pytest.mark.parametrize(
    "eligible_voters, needed",
    [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3)],
)
def test_votes_needed_is_a_strict_majority(eligible_voters, needed):
    assert service.votes_needed(eligible_voters) == needed


@pytest.mark.parametrize(
    "reject_votes, eligible_voters, rejected",
    [
        (2, 3, True),   # threshold met
        (1, 3, False),  # one short
        (3, 4, True),
        (2, 4, False),  # exactly half is not a majority
        (1, 1, True),   # 2-person group: the other member alone decides
        (0, 0, False),  # solo group: nobody can reject
    ],
)
def test_is_rejected_at_the_threshold(reject_votes, eligible_voters, rejected):
    assert service.is_rejected(reject_votes, eligible_voters) is rejected


def test_voting_is_open_just_before_the_window_ends():
    assert service.is_voting_open(NOW, NOW + timedelta(hours=48) - timedelta(seconds=1))


def test_voting_is_closed_at_exactly_48_hours():
    assert not service.is_voting_open(NOW, NOW + timedelta(hours=48))


# --- voting service ---

@pytest.fixture
def carol(conn):
    return make_user(conn, "carol")


@pytest.fixture
def dave(conn):
    return make_user(conn, "dave")


@pytest.fixture
def four_person_group(conn, alice, bob, carol, dave):
    """alice posts; bob, carol and dave are the 3 eligible voters, so 2 votes reject."""
    return make_group(conn, alice, bob, carol, dave)


@pytest.fixture
def checkin(conn, alice, four_person_group):
    goal = service.create_goal(conn, alice, four_person_group, "Gym", None, 3)
    return service.create_checkin(conn, alice, goal["id"], image_file(), None)


@pytest.fixture
def revoke_calls(monkeypatch):
    """Replace the Points stub with a recorder, so tests can count the calls."""
    calls = []
    monkeypatch.setattr(
        points_service, "revoke_completion", lambda conn, checkin_id: calls.append(checkin_id)
    )
    return calls


def status_of(conn, checkin_id):
    return repository.get_checkin(conn, checkin_id)["status"]


def test_one_vote_short_keeps_checkin_accepted(conn, bob, checkin, revoke_calls):
    result = service.cast_rejection_vote(conn, bob, checkin["id"])
    assert result == {
        "checkin_id": checkin["id"],
        "status": "accepted",
        "reject_votes": 1,
        "votes_needed": 2,
    }
    assert status_of(conn, checkin["id"]) == "accepted"
    assert revoke_calls == []


def test_reaching_the_threshold_rejects_and_revokes_once(conn, bob, carol, checkin, revoke_calls):
    service.cast_rejection_vote(conn, bob, checkin["id"])
    result = service.cast_rejection_vote(conn, carol, checkin["id"])
    assert result["status"] == "rejected"
    assert status_of(conn, checkin["id"]) == "rejected"
    assert revoke_calls == [checkin["id"]]


def test_vote_after_rejection_is_conflict_and_does_not_revoke_again(
    conn, bob, carol, dave, checkin, revoke_calls
):
    service.cast_rejection_vote(conn, bob, checkin["id"])
    service.cast_rejection_vote(conn, carol, checkin["id"])
    with pytest.raises(service.CheckinAlreadyRejected):
        service.cast_rejection_vote(conn, dave, checkin["id"])
    assert revoke_calls == [checkin["id"]]


def test_mark_rejected_only_succeeds_once(conn, checkin):
    """The UPDATE ... WHERE status = 'accepted' is what makes revoke fire exactly once."""
    assert repository.mark_rejected(conn, checkin["id"]) is True
    assert repository.mark_rejected(conn, checkin["id"]) is False


def test_duplicate_vote_is_conflict(conn, bob, checkin, revoke_calls):
    service.cast_rejection_vote(conn, bob, checkin["id"])
    with pytest.raises(service.AlreadyVoted):
        service.cast_rejection_vote(conn, bob, checkin["id"])
    assert repository.count_votes(conn, checkin["id"]) == 1


def test_unique_constraint_backs_up_the_duplicate_check(conn, bob, checkin, monkeypatch):
    # Simulate the race where has_voted() ran before the other vote was inserted.
    repository.insert_vote(conn, checkin["id"], bob, "2026-09-30T12:00:00+00:00")
    monkeypatch.setattr(repository, "has_voted", lambda *args: False)
    with pytest.raises(service.AlreadyVoted):
        service.cast_rejection_vote(conn, bob, checkin["id"])


def test_author_cannot_vote(conn, alice, checkin):
    with pytest.raises(service.CannotVoteOwnCheckin):
        service.cast_rejection_vote(conn, alice, checkin["id"])


def test_non_member_cannot_vote(conn, outsider, checkin):
    with pytest.raises(service.NotGroupMember):
        service.cast_rejection_vote(conn, outsider, checkin["id"])


def test_vote_on_missing_checkin_is_not_found(conn, bob):
    with pytest.raises(service.CheckinNotFound):
        service.cast_rejection_vote(conn, bob, 999)


def test_vote_after_window_is_closed(conn, bob, checkin):
    posted = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(timespec="seconds")
    conn.execute("UPDATE checkins SET created_at = ? WHERE id = ?", (posted, checkin["id"]))
    with pytest.raises(service.VotingClosed):
        service.cast_rejection_vote(conn, bob, checkin["id"])
    assert repository.count_votes(conn, checkin["id"]) == 0


def test_two_person_group_one_vote_rejects(conn, alice, bob, group_id, goal, revoke_calls):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), None)
    result = service.cast_rejection_vote(conn, bob, checkin["id"])
    assert result["status"] == "rejected"
    assert revoke_calls == [checkin["id"]]


def test_failed_revoke_rolls_back_vote_and_status(conn, bob, carol, checkin, monkeypatch):
    """Vote, status change and revoke are one transaction: an error undoes all of them."""
    service.cast_rejection_vote(conn, bob, checkin["id"])
    conn.commit()  # keep the setup and bob's vote; carol's vote gets its own transaction

    def failing_revoke(conn, checkin_id):
        raise RuntimeError("points unavailable")

    monkeypatch.setattr(points_service, "revoke_completion", failing_revoke)
    with pytest.raises(RuntimeError):
        with get_db() as request_conn:  # the same get_db() a real request uses
            service.cast_rejection_vote(request_conn, carol, checkin["id"])

    assert repository.count_votes(conn, checkin["id"]) == 1  # carol's vote was rolled back
    assert status_of(conn, checkin["id"]) == "accepted"


def test_rejection_by_vote_removes_the_points_from_the_leaderboard(
    conn, alice, bob, carol, four_person_group, checkin
):
    """End to end through the real seam: no recorder replaces revoke_completion here."""
    def alice_points():
        week_day = datetime.fromisoformat(checkin["created_at"]).date()
        board = points_service.get_leaderboard(conn, bob, four_person_group, week_day)
        return next(e["points"] for e in board["entries"] if e["user_id"] == alice)

    assert alice_points() == 1
    service.cast_rejection_vote(conn, bob, checkin["id"])
    service.cast_rejection_vote(conn, carol, checkin["id"])
    assert alice_points() == 0
