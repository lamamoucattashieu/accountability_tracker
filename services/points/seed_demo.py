"""Points half of the demo: forfeits, settled weeks, proof and next week's forfeit.

Run it after the Checkins half (services/checkins/seed_demo.py), with both
services running and this service's DATA_DIR holding only what the Checkins
half delivered:
    python seed_demo.py

It finds the demo crew through Checkins' public API (logging in as maya), so it
never touches the other service's database: seed data moves with its table.
Then it adds the forfeits the crew agreed on (backdated), settles every finished
week, uploads sam's proof for his oldest loss, and lets maya, last week's
winner, set next week's forfeit, all through the real service functions.
It refuses to run twice: a database that already has forfeits isn't seeded.
"""

import io
import sys
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.db import get_connection, init_db
from app.points import group_directory, repository, service
from app.shared.timeutils import week_begins_at, week_start_for

PASSWORD = "lockin-demo"  # the Checkins half gives every demo member this password
CREW_NAME = "gym gremlins"
WEEK = timedelta(weeks=1)


def photo(label: str) -> io.BytesIO:
    """A generated 'proof' photo: a yellow card with a big label."""
    image = Image.new("RGB", (800, 600), (243, 198, 74))
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, 30, 770, 570], outline=(20, 20, 20), width=8)
    draw.text((70, 220), label, fill=(20, 20, 20), font=ImageFont.load_default(size=72))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return buffer


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def find_crew(checkins_url: str) -> tuple[int, dict]:
    """The demo group's id and {username: user_id}, from Checkins' public API."""
    login = httpx.post(f"{checkins_url}/auth/login", json={"username": "maya", "password": PASSWORD})
    if login.status_code != 200:
        raise SystemExit("Can't log in as maya. Run the Checkins half first, with Checkins running.")
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    group = next(g for g in httpx.get(f"{checkins_url}/groups", headers=headers).json() if g["name"] == CREW_NAME)
    members = httpx.get(f"{checkins_url}/groups/{group['id']}/members", headers=headers).json()
    return group["id"], {member["username"]: member["id"] for member in members}


def seed(now: datetime, group_id: int, ids: dict) -> dict:
    init_db()
    conn = get_connection()
    if conn.execute("SELECT COUNT(*) AS n FROM forfeits").fetchone()["n"]:
        raise SystemExit("This DATA_DIR already has forfeits. Point DATA_DIR at a fresh folder to seed the demo.")

    this_week = week_begins_at(week_start_for(now))
    last_week, two_ago, three_ago = this_week - WEEK, this_week - 2 * WEEK, this_week - 3 * WEEK
    day, hour = timedelta(days=1), timedelta(hours=1)

    # --- forfeits, each set before the week it applies to -------------------------
    for text, set_at in [
        ("loser buys the whole crew coffee", three_ago - 6 * hour),
        ("10 push-ups on video in the group chat", two_ago - day),
        ("a 30-second dance video, no filters", last_week - day),
    ]:
        repository.insert_forfeit(conn, group_id, text, ids["maya"], iso(set_at))
    conn.commit()

    # --- settle finished weeks, then proof for sam's oldest loss -------------------
    service.ensure_settled(conn, group_id, now)
    sam_loss = conn.execute(
        """SELECT TOP 1 forfeit_assignments.id FROM forfeit_assignments
           JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
           WHERE settlements.group_id = %s AND forfeit_assignments.user_id = %s
           ORDER BY settlements.week_start""",
        (group_id, ids["sam"]),
    ).fetchone()
    if sam_loss:
        service.submit_proof(conn, ids["sam"], sam_loss["id"], photo("10 PUSH-UPS"), now)
        conn.commit()

    # --- next week's forfeit, set by last week's winner (the real rule) ------------
    service.set_forfeit(conn, ids["maya"], group_id, "last place renames the group chat for a week", now)
    conn.commit()

    summary = {
        "settled_weeks": conn.execute("SELECT COUNT(*) AS n FROM settlements").fetchone()["n"],
        "forfeit_losers": conn.execute("SELECT COUNT(*) AS n FROM forfeit_assignments").fetchone()["n"],
        "proofs": conn.execute("SELECT COUNT(*) AS n FROM forfeit_assignments WHERE proof_at IS NOT NULL").fetchone()["n"],
    }
    conn.close()
    return summary


def main():
    settings.check_secrets()
    group_directory.set_directory(group_directory.HttpGroupDirectory(
        settings.checkins_url, settings.checkins_timeout_s, settings.internal_api_key,
    ))
    group_id, ids = find_crew(settings.checkins_url)
    summary = seed(datetime.now(timezone.utc), group_id, ids)
    print("Points half seeded:", ", ".join(f"{k} {v}" for k, v in summary.items()))
    print(f"Open the UI and log in as maya / {PASSWORD}")


if __name__ == "__main__":
    sys.exit(main())
