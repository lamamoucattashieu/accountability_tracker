"""The port Points uses to learn a group's members from Checkins (ports & adapters).

fetch_group returns a plain dict, or None if the group doesn't exist:
    {"id": int, "created_at": iso, "members": [{"id": int, "joined_at": iso}],
     "pending_points_sync": bool}
and raises CheckinsUnavailable when the answer can't be had right now.
Production plugs in an adapter with set_directory(); tests plug in a fake.
"""

from typing import Optional, Protocol

import httpx

from app.shared.internal_api import INTERNAL_KEY_HEADER


class CheckinsUnavailable(Exception):
    """Checkins is down, too slow, or answered with an error."""


class GroupDirectory(Protocol):
    def fetch_group(self, group_id: int) -> Optional[dict]: ...


class UnconfiguredGroupDirectory:
    """Used until main.py plugs in the real adapter: Checkins counts as unreachable."""

    def fetch_group(self, group_id: int) -> Optional[dict]:
        raise CheckinsUnavailable("no Checkins directory configured")


class HttpGroupDirectory:
    """Adapter: Checkins' GET /internal/groups/{id} over HTTP, with a timeout.

    404 means the group doesn't exist; anything else that isn't a 200 (a timeout,
    a refused connection, a 5xx, a refused key) means Checkins can't answer now.
    """

    def __init__(self, base_url: str, timeout_s: float, internal_key: str, transport=None):
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout_s, transport=transport,
            headers={INTERNAL_KEY_HEADER: internal_key},
        )

    def fetch_group(self, group_id: int) -> Optional[dict]:
        try:
            response = self._http.get(f"/internal/groups/{group_id}")
        except httpx.HTTPError as exc:  # timeouts and connection errors
            raise CheckinsUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise CheckinsUnavailable(f"checkins answered {response.status_code}")
        return response.json()


_directory: GroupDirectory = UnconfiguredGroupDirectory()


def set_directory(directory: GroupDirectory) -> None:
    global _directory
    _directory = directory


def get_directory() -> GroupDirectory:
    return _directory
