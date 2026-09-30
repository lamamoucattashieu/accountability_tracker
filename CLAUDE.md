# CLAUDE.md

## Context
Individual Assignment 1, Software Development & DevOps (IE Madrid). Deadline **2026-10-04 23:59**.
A habit tracker for friend groups: members set goals, post photo check-ins, compete on a weekly
leaderboard, and the week's lowest scorer does a forfeit the group agreed on in advance.

This app gets Dockerized and deployed to Azure in Assignment 2 using a shared script we don't
control, so the deployment contract below is non-negotiable.

Full spec: @docs/assignment_spec.md

**Current status:** Phases 0-2 are done and merged (PRs #1-#5). **Phase 3** is implemented on
`feat/phase-3-rejection-votes`, awaiting my review.

---

## How we work
I'll be examined on this code on paper, closed-book, with no notes. Every line has to be
something I can explain and defend. Optimize for readable, boring, correct code over clever code.

- **One phase at a time.** Don't touch the next phase until I say "next phase".
- **Plan before code.** Every phase starts with a short plan (files, schema changes, interfaces,
  commit order). Then stop and wait for my approval.
- **Don't guess.** If something is ambiguous or a decision listed under "Decisions that are mine"
  is still open, stop and ask me. Don't pick a "sensible default".
- **Respect existing code.** If something from an earlier phase conflicts with this file, flag it
  and propose a fix. Don't silently rewrite it.
- **No scope creep.** No new abstractions, files, or packages I didn't ask for. If you think one
  is needed, make the case and let me decide.

## Course material to apply
The grading rewards visible design reasoning using the course's own vocabulary. When a choice is
driven by one of these, name it in one line (in the plan or the walkthrough, not code comments):
- **SOLID:** mainly single responsibility (route vs service vs repository) and dependency
  inversion (checkins depends on the points interface, not its internals).
- **Code smells:** avoid long functions, duplicated logic, magic numbers (thresholds, point values,
  and limits go in `config.py` or named constants), and business logic in route handlers.
- **Design patterns:** use one only when it solves a problem we actually have, and say what the
  problem is. "No pattern needed here" is a fine answer.
- **SDLC:** the phases are my iterations. The end-of-phase report is my evidence for the report's
  SDLC section, so be accurate about what was planned vs what actually happened.

---

## Hard constraints (from the spec, never violate)
- Single process: FastAPI + SQLite, with a plain HTML/CSS/JS frontend served by the same app
- Bind `0.0.0.0`, with the port from `PORT` (default 8000)
- All data under `DATA_DIR` (default `./data`): SQLite at `DATA_DIR/app.db`, uploads at
  `DATA_DIR/uploads/`
- One `requirements.txt` at the repo root, soft cap ~12 third-party packages. Don't add any
  package without asking me.
- No Dockerfile, docker-compose, `.github/workflows`, IaC, background job runners, cron, Redis,
  or anything else that assumes a second process
- No interactive setup: the schema is created automatically on startup
- Configured through env vars only. The app runs without a `.env` file.
- Starts with one documented command and is ready within a few seconds

---

## Architecture

### Domain 1: Goals & Check-ins (`app/checkins/`)
- Goals created inside a group
- Photo check-ins as proof of completing a goal
- Rejection votes: a check-in counts by default, and group members can vote to reject it; once
  the rule is met, it becomes rejected
- Owns tables: `goals`, `checkins`, `checkin_votes`

### Domain 2: Points & Forfeits (`app/points/`)
- Weekly scoring per group per week, and the leaderboard for the current week
- A forfeit agreed in advance per group. When a week ends, the lowest scorer is assigned it and
  must upload photo proof.
- **Lazy settlement (no cron):** the first request after a week ends settles it. A UNIQUE
  constraint on `(group_id, week_start)` makes double settlement impossible at the database
  level, not just in code.
- Owns tables: `point_events`, `forfeits`, `forfeit_assignments`

### Shared (not a domain)
- `app/auth/`: users, groups, invite codes, sessions
- `app/shared/uploads.py`: image saving and validation, used by both domains so neither imports
  the other for photos

### The seam (graded: keep it clean)
- Checkins talks to Points **only** through `app/points/service.py`:
  - `record_completion(...)` when a check-in is created
  - `revoke_completion(...)` when a check-in is rejected
- Points **never** reads or writes checkins tables, and checkins never touches points tables.
- Only IDs and timestamps cross the seam, never ORM objects or DB rows. This function boundary
  is exactly where a future HTTP or message call would go in the microservice split.
- Both functions must be **idempotent**: recording the same check-in twice, or revoking one that
  was never recorded or is already revoked, is a no-op, not an error or a double count.
- Once the signatures exist, changing them requires my approval.
- **Phase 3 check:** look at `app/points/service.py` first. If these functions don't exist yet,
  the Phase 3 plan must propose how checkins calls them before Points is implemented (for example
  a stub with final signatures and no logic, or an injected dependency). Give me the options with
  trade-offs, and I'll choose. Phase 4 fills in the real logic.

### Layering inside each domain
- `routes.py`: thin endpoints that parse input, call the service, and map results and errors to
  HTTP. No business logic.
- `service.py`: business logic. Rules (vote threshold, scoring, tie-breaking) are **pure
  functions** that take plain values and return decisions, so they're testable without a DB.
- `repository.py`: SQL only, with parameterized queries. No business decisions.
- Flow: request -> route -> service -> repository -> SQLite

### Database conventions
- Foreign keys enabled (`PRAGMA foreign_keys = ON`) on every connection
- Timestamps stored in UTC, ISO 8601
- Invariants enforced by constraints where possible (UNIQUE, CHECK, NOT NULL), not only in Python
- Any write that changes more than one row or table as a single logical action runs in **one
  transaction** (e.g. vote insert + status change; settlement + forfeit assignment)
- Schema changes go in the startup schema code (`CREATE TABLE IF NOT EXISTS`). If an existing
  table needs a new column, tell me, because local DBs from earlier phases won't pick it up
  automatically.

### Errors
Use meaningful status codes: 401 not logged in, 403 not allowed (e.g. not a group member), 404
not found, 409 conflicts with current state (duplicate vote, already settled), 422 invalid input.
Services raise domain errors, and routes translate them. No bare 400s or 500s for expected cases.

---

## Decisions that are mine
Never decide these. If one is blank when a phase needs it, stop and ask me.

| Decision | Needed by | My answer |
|---|---|---|
| Who can vote to reject a check-in (author excluded?) | Phase 3 | Any current group member, never the author (403) |
| Votes needed to reject (fixed number / majority of eligible voters) | Phase 3 | Strict majority of the other members: `eligible // 2 + 1`, recalculated from the current member count on every vote |
| Voting time window | Phase 3 | 48 hours from posting; open while `now < posted_at + 48h`, closed at exactly 48h (409) |
| Can a vote be changed or withdrawn? Can a rejection be undone? | Phase 3 | No and no: votes are final (duplicate = 409), and rejected is a terminal state (further votes = 409) |
| Small-group edge case (e.g. 2 members) | Phase 3 | The rule applies as-is: in a 2-person group the other member alone rejects; in a solo group nothing can be rejected |
| What a "week" is: start day, timezone, boundary time | Phase 4 | |
| What earns points: each valid check-in, or meeting a goal's weekly target | Phase 4 | |
| Point values, and whether streaks give bonuses | Phase 4 | |
| Tie-breaking for lowest score | Phase 5 | |
| How the forfeit is agreed and when it locks | Phase 5 | |
| What happens if the loser never posts proof | Phase 5 | |
| Whether members with zero check-ins can "lose" | Phase 5 | |

Anything that turns into a real trade-off is a candidate ADR entry. Point it out when it happens.

### Decisions already made in earlier phases
Recorded so later phases stay consistent with them. Each one was an open question that I answered.

**Phase 2a: Goals**
- A goal has a title (max 80), an optional description (max 500) and `times_per_week` (1-7,
  CHECK constraint). A weekly target, because scoring is weekly.
- Goals are never hard-deleted: archiving sets `archived_at`, because check-ins and point events
  reference goals. Archived goals can't be edited and are hidden from the goal list.
- No cap on active goals. Accepted risk: point farming, handled by social pressure.
- The owner can edit a goal any time; points use `times_per_week` as it was at each check-in.
- Checkins asks auth only through `auth.service.is_member` / `group_exists`, never auth tables
  (ADR-2). Cost: the goal list returns `user_id`, not `username`.
- A missing group is 404, then a non-member is 403. Accepted risk: group IDs can be enumerated,
  but joining still needs an invite code.
- Any change to an archived goal is 409, including archiving it twice. No special cases.
- PATCH follows JSON Merge Patch: an absent field is unchanged, `"description": null` clears it,
  and null `title`/`times_per_week` is 422. Text is trimmed, an empty description is stored as
  NULL, and length limits apply after trimming.
- All timestamps are ISO 8601 UTC from `utc_now_iso()`, and Phase 1 tables were migrated to it,
  because mixed formats sort wrongly as strings and mix naive/aware datetimes.
- pytest and pytest-cov are pinned in `requirements.txt`, because there is only one manifest and
  the coverage command must work on a clean clone. Cost: test tools ship in the production image.

**Phase 2b: Photo check-ins & uploads**
- Only JPEG/PNG, detected from file content. `MAX_UPLOAD_BYTES` = 5 MiB, enforced while reading
  in chunks. Too many pixels (decompression bomb) is 413. uuid4 filenames, and paths stored
  relative to `DATA_DIR` with `/` separators.
- `GoalError` was renamed `CheckinsError` (the domain-wide base). Routes catch
  `HANDLED_ERRORS = (CheckinsError, UploadError)`, so `shared/` never depends on a domain and
  each domain keeps its own HTTP error mapping.
- Starlette buffers uploads in the OS temp dir before our code runs. Accepted: the
  request-size limit belongs at the ingress/reverse proxy (Assignment 2), not in custom middleware.
- A row whose photo file is missing gives 404 `PhotoMissing` and a logged warning, not a 500.
- The feed keeps check-ins of archived goals, returns the 50 newest, and has no status filter.
- EXIF (including GPS) stays in stored photos. Accepted privacy risk: only members can fetch them.
- Commits stay in `get_db()`. A rare orphaned file after a failed commit is accepted (harmless),
  unlike a row pointing to a missing file.

**Phase 3: Rejection votes** (besides the table above)
- Before Points exists, checkins calls a **stub** `app/points/service.py` with the final
  signature and no logic (not an injected dependency). The seam is that module.
- The signature is fixed as `revoke_completion(conn, checkin_id)`. It takes `conn` so the
  rejection and the points change commit in one transaction. `record_completion`'s signature
  waits for the Phase 4 decision on what earns points.
- Guard checks run before the transaction starts. Accepted: two simultaneous votes can leave one
  extra vote row on a just-rejected check-in. Status and "revoke exactly once" stay correct,
  because `mark_rejected` (`UPDATE ... WHERE status = 'accepted'`) succeeds for only one transaction.

---

## Phases
0. **Scaffold** (done, committed directly on `main` as `3c8ec23`, before PRs were used): `config.py` (env vars `PORT`, `DATA_DIR`), `db.py`
   (connection with foreign keys on, schema created on startup), `main.py` (binds `0.0.0.0`),
   `/health` endpoint.
1. **Auth & groups** (done, PR #1): register/login with PBKDF2-SHA256 password hashing, session
   token in an httponly, samesite=lax cookie with a 7-day expiry, create a group, join with an
   8-character invite code.
2. **Goals & check-ins** (done, two increments):
   - 2a, PR #3: goals with membership rules, soft archive and JSON Merge Patch edits, plus
     `utc_now_iso()` for all timestamps.
   - 2b, PR #4: photo check-ins, newest-first feed, member-only photo access, and the shared
     `app/shared/uploads.py` facade.
   - ADR-2 and ADR-3 were written from these phases (PRs #3 and #5).
3. **Rejection votes:** voting endpoint, the rejection rule as a pure function, an atomic
   vote + status change, and `revoke_completion` called exactly once per rejection.
   *Done when:* the rule is unit-tested at the threshold boundary; duplicate votes, author votes,
   non-member votes, closed-window votes, and votes on rejected check-ins are all rejected
   correctly; tests prove `revoke_completion` fires once.
4. **Weekly scoring & leaderboard:** real `record_completion` / `revoke_completion`, weekly
   totals, and ranking computed in SQL.
   *Done when:* scoring is unit-tested across week boundaries and revocations; the leaderboard
   endpoint returns a correct ranking.
5. **Forfeits:** forfeit set in advance per group, lazy settlement, and the loser uploads proof.
   *Done when:* settlement is tested for ties, empty weeks, and concurrent first requests (the
   UNIQUE constraint holds); proof upload reuses `app/shared/uploads.py`.
6. **Frontend:** simple HTML/JS pages for everything above. If time is short, cut to the minimum
   usable pages rather than eat into Phase 7.
7. **Hardening & docs:** coverage to ≥70% on service logic, README (setup + coverage command),
   and a security pass (password hashing, session cookie flags, upload size/type/path-traversal
   checks, group membership checked on every group-scoped endpoint). Also generate the
   architecture diagram and database schema diagram from the **actual** code, so they match
   the repo.

**Stretch features are cut** unless I explicitly bring them back (image-hash duplicates, EXIF
stripping, per-group timezones).

---

## Testing
- pytest + pytest-cov. Tests live in `tests/checkins/` and `tests/points/`.
- Prioritize pure rule functions, then services against a temporary SQLite DB (point `DATA_DIR`
  at pytest's `tmp_path`). Never touch the real `./data`.
- Test behavior and edge cases, not framework glue or routing.
- Coverage command (goes in the README):
  `pytest --cov=app --cov-report=term-missing`
- At the end of each phase, report coverage for that phase's `service.py`.

---

## Process deliverables (I write these, you help)
- **ADR.md:** exactly 5 entries in the spec's format, spanning at least 3 distinct commit dates.
  When a phase involves an ADR-worthy decision, give me a draft and tell me which of the 5
  required entries it fits. I'll edit and commit it myself.
- **AI_USAGE.md:** one row per meaningful interaction. You may draft the factual columns, but
  **never write the "In my own words" column**. That column is mine.
- **Report:** the SDLC section draws on the phase reports, so keep them honest about deviations.

---

## End of every phase: stop and give me
1. **Walkthrough:** each new or changed file and key function in plain language, with the data
   flow (request -> route -> service -> repository -> SQLite)
2. **Why:** the design reasoning (naming any SOLID principle, smell, or pattern involved) and one
   alternative we didn't choose, with the reason
3. **3 closed-book questions** like the comprehension check would ask, using real function names
4. **Notes reminder**, and whether this phase needs an ADR entry (and which one)
5. **AI_USAGE.md reminder**
6. **Coverage** for this phase's services
7. **Git:** a conventional commit message (or several, if the work splits naturally) and the
   branch name

Then wait while I take notes and ask questions.

---

## Git
- One feature branch per phase (e.g. `feat/phase-3-rejection-votes`), with PRs into `main`
  merged using merge commits (no squash)
- Small, focused conventional commits that say what changed **and why**. Never "WIP", "update",
  or "fix".
- **Never push without asking me.**
- The spec requires 12+ commits across 6+ distinct days, with no day over 40% of commits,
  measured by **push timestamps**. At the end of each phase, run `git log` and tell me the commit
  count and distinct commit days so far. Never suggest backdating or rewriting history.