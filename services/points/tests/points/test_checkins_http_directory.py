"""The HTTP adapter behind the GroupDirectory port, against a stub Checkins (httpx.MockTransport)."""

import httpx
import pytest

from app.points.group_directory import CheckinsUnavailable, HttpGroupDirectory

GROUP = {"id": 1, "created_at": "2026-09-20T09:00:00+00:00",
         "members": [{"id": 2, "joined_at": "2026-09-20T09:00:00+00:00"}], "pending_points_sync": False}


def directory_answering(handler):
    return HttpGroupDirectory("http://checkins.test", 2.0, "the-key", transport=httpx.MockTransport(handler))


def test_fetch_group_asks_checkins_with_the_internal_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=GROUP)

    assert directory_answering(handler).fetch_group(1) == GROUP
    assert seen[0].url.path == "/internal/groups/1"
    assert seen[0].headers["X-Internal-Key"] == "the-key"


def test_unknown_group_is_none():
    assert directory_answering(lambda request: httpx.Response(404)).fetch_group(1) is None


@pytest.mark.parametrize("answer", [
    lambda request: httpx.Response(500),
    lambda request: httpx.Response(401),
    lambda request: httpx.Response(503),
])
def test_error_answers_mean_checkins_is_unavailable(answer):
    with pytest.raises(CheckinsUnavailable):
        directory_answering(answer).fetch_group(1)


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("timed out")])
def test_down_or_slow_checkins_is_unavailable(error):
    def handler(request):
        raise error

    with pytest.raises(CheckinsUnavailable):
        directory_answering(handler).fetch_group(1)
