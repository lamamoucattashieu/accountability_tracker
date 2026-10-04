"""Fill an empty DATA_DIR with a demo crew, so every feature has something to show.

    python seed_demo.py      # then: python main.py, and log in as maya / lockin-demo

Everything goes through the real service functions, so every rule holds (vote
thresholds, the weekly cap, streaks, settlement, who may set the forfeit); only
timestamps are moved back afterwards to create past weeks. It refuses to run on a
database that already has users, so demo data never mixes with real data.
"""

import io
import sys
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

from app.auth import repository as auth_repository
from app.auth import service as auth_service
from app.checkins import service as checkins_service
from app.db import get_connection, init_db
from app.points import repository as points_repository
from app.points import service as points_service
from app.shared.timeutils import week_begins_at, week_start_for

PASSWORD = "lockin-demo"
CREW = ["maya", "leo", "zoe", "sam"]  # maya is the account to log in with
WEEK = timedelta(weeks=1)
COLORS = {"purple": (138, 123, 255), "lime": (187, 255, 92), "coral": (255, 122, 87),
          "yellow": (243, 198, 74)}


def photo(label: str, color: str) -> io.BytesIO:
    """A generated 'proof' photo: a coloured card with a big label."""
    image = Image.new("RGB", (800, 600), COLORS[color])
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, 30, 770, 570], outline=(20, 20, 20), width=8)
    draw.text((70, 220), label, fill=(20, 20, 20), font=ImageFont.load_default(size=72))
    draw.text((70, 500), "lockin. demo proof", fill=(20, 20, 20), font=ImageFont.load_default(size=28))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return buffer


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def seed(now: datetime) -> dict:
    """Create the demo crew relative to `now`; returns a short summary."""
    init_db()
    conn = get_connection()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        raise SystemExit("This DATA_DIR already has users. Point DATA_DIR at an empty folder to seed the demo.")

    this_week = week_begins_at(week_start_for(now))
    last_week, two_ago, three_ago = this_week - WEEK, this_week - 2 * WEEK, this_week - 3 * WEEK
    created = three_ago - timedelta(hours=12)  # the crew exists a few weeks before "now"

    # --- people and the crew ------------------------------------------------------
    ids = {}
    for name in CREW:
        auth_service.register(conn, name, PASSWORD)
        ids[name] = auth_repository.get_user_by_username(conn, name)["id"]
    group = auth_service.create_group(conn, ids["maya"], "gym gremlins")
    for name in CREW[1:]:
        auth_service.join_group(conn, ids[name], group["invite_code"])
    conn.execute("UPDATE groups SET created_at = ? WHERE id = ?", (iso(created), group["id"]))
    conn.execute("UPDATE group_members SET joined_at = ? WHERE group_id = ?", (iso(created), group["id"]))

    def goal(owner, title, description, times_per_week):
        row = checkins_service.create_goal(conn, ids[owner], group["id"], title, description, times_per_week)
        conn.execute("UPDATE goals SET created_at = ? WHERE id = ?", (iso(created), row["id"]))
        return row["id"]

    goals = {
        "maya_gym": goal("maya", "Gym before class", "Leg day counts. No mysterious calendar conflicts.", 3),
        "maya_read": goal("maya", "Read 20 pages", "Yes, the book on the nightstand.", 2),
        "leo_run": goal("leo", "Run 5K", "Outside, not on a treadmill.", 2),
        "zoe_gym": goal("zoe", "Gym", "At least 45 minutes.", 3),
        "sam_spanish": goal("sam", "Spanish practice", "20 minutes on the app or with a tutor.", 3),
    }

    def post(owner, goal_key, at, label, color, caption=None):
        """A check-in through the real service, then moved back in time (with its points)."""
        checkin = checkins_service.create_checkin(conn, ids[owner], goals[goal_key], photo(label, color), caption)
        move_checkin(checkin["id"], at)
        return checkin["id"]

    def move_checkin(checkin_id, at):
        conn.execute("UPDATE checkins SET created_at = ? WHERE id = ?", (iso(at), checkin_id))
        conn.execute(
            "UPDATE point_events SET completed_at = ?, week_start = ? WHERE checkin_id = ?",
            (iso(at), week_start_for(at).isoformat(), checkin_id),
        )

    day = timedelta(days=1)
    hour = timedelta(hours=1)

    # --- forfeits, each set before the week it applies to -------------------------
    for text, set_at in [
        ("loser buys the whole crew coffee", three_ago - 6 * hour),
        ("10 push-ups on video in the group chat", two_ago - day),
        ("a 30-second dance video, no filters", last_week - day),
    ]:
        points_repository.insert_forfeit(conn, group["id"], text, ids["maya"], iso(set_at))

    # --- two weeks ago: sam scores nothing and loses ------------------------------
    for offset in (0, 2, 4):
        post("maya", "maya_gym", two_ago + offset * day + 8 * hour, "LEG DAY", "purple")
    for offset in (1, 3):
        post("leo", "leo_run", two_ago + offset * day + 7 * hour, "5K DONE", "lime")
    for offset in (1, 4):
        post("zoe", "zoe_gym", two_ago + offset * day + 18 * hour, "GYM", "coral")

    # --- last week: maya wins with a streak bonus, leo and sam tie for last --------
    for offset in (0, 2, 4):
        post("maya", "maya_gym", last_week + offset * day + 8 * hour, "SQUATS", "purple")
    post("maya", "maya_read", last_week + 5 * day + 21 * hour, "20 PAGES", "yellow")
    for offset in (1, 3, 5):
        post("zoe", "zoe_gym", last_week + offset * day + 18 * hour, "GYM", "coral")
    post("leo", "leo_run", last_week + 2 * day + 7 * hour, "5K DONE", "lime")
    post("sam", "sam_spanish", last_week + 3 * day + 20 * hour, "HOLA", "yellow")

    # --- this week (only moments before `now`) ------------------------------------
    elapsed = now - this_week
    def this_week_at(fraction):
        return this_week + elapsed * fraction

    zoe_posts = [post("zoe", "zoe_gym", this_week_at(f), "GYM", "coral", caption)
                 for f, caption in ((0.2, "sunrise session"), (0.6, None))]
    leo_post = post("leo", "leo_run", this_week_at(0.4), "5K DONE", "lime", "5.2K before my brain could negotiate")
    # maya's post is from before today if possible, so she is nudgeable today (unless it's Monday)
    maya_at = max(this_week + hour, now - 1.5 * day) if elapsed > day else None
    maya_post = post("maya", "maya_gym", maya_at, "LEG DAY", "purple", "leg day, as promised") if maya_at else None

    # A suspicious check-in the crew votes down: created now (votes need an open
    # window), rejected by a majority of the other three, then moved back.
    suspicious = checkins_service.create_checkin(
        conn, ids["leo"], goals["leo_run"], photo("TOTALLY RAN", "lime"), "trust me, I ran")
    checkins_service.cast_rejection_vote(conn, ids["maya"], suspicious["id"])
    checkins_service.cast_rejection_vote(conn, ids["zoe"], suspicious["id"])
    move_checkin(suspicious["id"], this_week_at(0.5))

    # --- comments on proof ---------------------------------------------------------
    checkins_service.add_comment(conn, ids["sam"], suspicious["id"], "that's a screenshot from 2019")
    checkins_service.add_comment(conn, ids["leo"], suspicious["id"], "ok fine, it was the treadmill")
    checkins_service.add_comment(conn, ids["maya"], leo_post, "the brain negotiation is real")
    checkins_service.add_comment(conn, ids["zoe"], zoe_posts[0], "who is awake at this hour??")
    if maya_post:
        checkins_service.add_comment(conn, ids["leo"], maya_post, "ok that's actually impressive")
        checkins_service.add_comment(conn, ids["maya"], maya_post, "receipts attached")
    conn.commit()

    # --- settle finished weeks, then proof for the oldest loss ---------------------
    points_service.ensure_settled(conn, group["id"], now)
    sam_loss = conn.execute(
        """SELECT forfeit_assignments.id FROM forfeit_assignments
           JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
           WHERE settlements.group_id = ? AND forfeit_assignments.user_id = ?
           ORDER BY settlements.week_start LIMIT 1""",
        (group["id"], ids["sam"]),
    ).fetchone()
    if sam_loss:
        points_service.submit_proof(conn, ids["sam"], sam_loss["id"], photo("10 PUSH-UPS", "yellow"), now)
        conn.commit()

    # --- next week's forfeit, set by last week's winner (the real rule) ------------
    points_service.set_forfeit(conn, ids["maya"], group["id"], "last place renames the group chat for a week", now)
    conn.commit()

    # --- nudges: maya receives one, sam receives one -------------------------------
    nudges = 0
    for sender, target, message in [("zoe", "maya", "the gym misses you, it told me"), ("leo", "sam", None)]:
        try:
            checkins_service.send_nudge(conn, ids[sender], group["id"], ids[target], message, now)
            nudges += 1
        except checkins_service.NotNudgeable:
            pass  # e.g. on a Monday maya may already have posted today; nothing to nudge
    conn.commit()

    summary = {
        "users": len(CREW),
        "checkins": conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0],
        "rejected": conn.execute("SELECT COUNT(*) FROM checkins WHERE status = 'rejected'").fetchone()[0],
        "comments": conn.execute("SELECT COUNT(*) FROM checkin_comments").fetchone()[0],
        "settled_weeks": conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0],
        "forfeit_losers": conn.execute("SELECT COUNT(*) FROM forfeit_assignments").fetchone()[0],
        "nudges": nudges,
    }
    conn.close()
    return summary


def main():
    summary = seed(datetime.now(timezone.utc))
    print("Demo crew 'gym gremlins' created:", ", ".join(f"{k} {v}" for k, v in summary.items()))
    print(f"Now run: python main.py   and log in as maya / {PASSWORD}")
    print(f"(leo, zoe and sam use the same password; open a private window to see another view)")


if __name__ == "__main__":
    sys.exit(main())
