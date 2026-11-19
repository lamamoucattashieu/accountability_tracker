"""The port Points uses to learn a group's members from Checkins (ports & adapters).

fetch_group returns a plain dict, or None if the group doesn't exist:
    {"id": int, "created_at": iso, "members": [{"id": int, "joined_at": iso}],
     "pending_points_sync": bool}
and raises CheckinsUnavailable when the answer can't be had right now.
Production plugs in an adapter with set_directory(); tests plug in a fake.
"""

from typing import Optional, Protocol


class CheckinsUnavailable(Exception):
    """Checkins is down, too slow, or answered with an error."""


class GroupDirectory(Protocol):
    def fetch_group(self, group_id: int) -> Optional[dict]: ...


class UnconfiguredGroupDirectory:
    """Used until main.py plugs in the real adapter: Checkins counts as unreachable."""

    def fetch_group(self, group_id: int) -> Optional[dict]:
        raise CheckinsUnavailable("no Checkins directory configured")


_directory: GroupDirectory = UnconfiguredGroupDirectory()


def set_directory(directory: GroupDirectory) -> None:
    global _directory
    _directory = directory


def get_directory() -> GroupDirectory:
    return _directory
