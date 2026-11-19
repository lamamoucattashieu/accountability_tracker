"""The HTTP adapter behind the PointsClient port, against a stub Points (httpx.MockTransport)."""

import json

import httpx
import pytest

from app.checkins.points_client import HttpPointsClient, PointsRejected, PointsUnavailable

COMPLETION = {"checkin_id": 7, "group_id": 1, "user_id": 2, "goal_id": 3,
              "times_per_week": 3, "completed_at": "2026-11-19T10:00:00+00:00"}


def client_answering(handler):
    return HttpPointsClient("http://points.test", 2.0, "the-key", transport=httpx.MockTransport(handler))


def test_record_posts_the_completion_with_the_internal_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    client_answering(handler).record(COMPLETION)
    [request] = seen
    assert (request.method, request.url.path) == ("POST", "/internal/completions")
    assert request.headers["X-Internal-Key"] == "the-key"
    assert json.loads(request.content) == COMPLETION


def test_revoke_posts_the_rejection_time():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    client_answering(handler).revoke(7, "2026-11-19T11:00:00+00:00")
    assert seen[0].url.path == "/internal/completions/7/revocation"
    assert json.loads(seen[0].content) == {"revoked_at": "2026-11-19T11:00:00+00:00"}


@pytest.mark.parametrize("error", [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("timed out"),
    httpx.ConnectTimeout("timed out"),
])
def test_down_or_slow_points_is_unavailable(error):
    def handler(request):
        raise error

    with pytest.raises(PointsUnavailable):
        client_answering(handler).record(COMPLETION)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_unavailable_so_the_change_is_retried(status):
    with pytest.raises(PointsUnavailable):
        client_answering(lambda request: httpx.Response(status)).record(COMPLETION)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_is_unavailable_not_rejected(status, caplog):
    """A wrong key is a configuration problem: keep the change queued until it's fixed."""
    with pytest.raises(PointsUnavailable):
        client_answering(lambda request: httpx.Response(status)).record(COMPLETION)
    assert "INTERNAL_API_KEY" in caplog.text


@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_client_errors_are_rejected(status):
    with pytest.raises(PointsRejected):
        client_answering(lambda request: httpx.Response(status, text="bad completion")).record(COMPLETION)
