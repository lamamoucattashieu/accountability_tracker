# lockin.

**No ghosting your goals.** A habit tracker for friend groups: everyone sets weekly goals, posts
photo proof, and the crew keeps each other honest. Friends can call cap on a suspicious check-in,
reply to it, or nudge someone who's slacking. Points add up on a weekly leaderboard, and the week's
lowest scorer does the forfeit that last week's winner picked.

Software Development & DevOps (IE Madrid). Assignment 1 built it as a single-process monolith;
Assignment 2 splits it into two services, one per domain, talking over HTTP, each with its own
database, with a static UI that calls both.

## Features

| Service | What it does |
|---|---|
| **checkins** (`services/checkins/`) | Register/login (signed access tokens), crews with invite codes, weekly goals, photo check-ins, rejection votes, comments on proof, nudges |
| **points** (`services/points/`) | Weekly scoring with a per-goal cap and streak bonus, leaderboard, forfeits, lazy week settlement, proof upload |
| **UI** (`ui/`) | Static HTML/CSS/JS that calls both services from the browser |

The services never read each other's database. Checkins tells Points about completions through a
points outbox (delivered over HTTP, retried until Points takes them); Points asks Checkins who is
in a group, and keeps the last answer so it can keep serving when Checkins is down.

## Requirements

- Python 3.13 (3.11+ should work)
- SQLite ships with Python. (Phase 2 of A2 moves the databases to SQL Server.)

## Setup and run (locally, three terminals)

```bash
git clone https://github.com/lamamoucattashieu/accountability_tracker.git
cd accountability_tracker
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS / Linux: source .venv/bin/activate
pip install -r services/checkins/requirements.txt -r services/points/requirements.txt
```

Both services need the same two secrets. They have no default, so a service refuses to start
without them. Pick any values for a local run, and use the same ones in every terminal:

```bash
# macOS / Linux
export AUTH_TOKEN_SECRET=local-dev-secret INTERNAL_API_KEY=local-dev-key
# Windows PowerShell
$env:AUTH_TOKEN_SECRET="local-dev-secret"; $env:INTERNAL_API_KEY="local-dev-key"
```

Then:

```bash
cd services/checkins && python main.py      # terminal 1: http://localhost:8000
cd services/points && python main.py        # terminal 2: http://localhost:8001
python -m http.server 5500 -d ui            # terminal 3, from the repo root: the UI
```

Open **http://localhost:5500/**. Each service creates its schema on startup. API docs:
http://localhost:8000/docs and http://localhost:8001/docs.

## Demo data (optional)

With both services running on empty data folders, seed the demo crew in two halves, each into its
own service's database:

```bash
cd services/checkins && python seed_demo.py   # people, goals, check-ins, votes, comments, nudges
cd services/points && python seed_demo.py     # forfeits, settled weeks, proof, next week's forfeit
```

Log in as **`maya`** with password **`lockin-demo`** (`leo`, `zoe` and `sam` use the same
password). Each half refuses to run on a database that already has data.

## Configuration

Everything is configured through environment variables:

| Variable | Service | Default | Purpose |
|---|---|---|---|
| `PORT` | both | 8000 (checkins), 8001 (points) | Port to listen on (always binds `0.0.0.0`) |
| `DATA_DIR` | both | `./data` | The service's SQLite file (`checkins.db` / `points.db`) and uploaded photos |
| `POINTS_URL` | checkins | `http://localhost:8001` | Where Points is |
| `POINTS_TIMEOUT_S` | checkins | `2` | Timeout of every call to Points |
| `CHECKINS_URL` | points | `http://localhost:8000` | Where Checkins is |
| `CHECKINS_TIMEOUT_S` | points | `2` | Timeout of every call to Checkins |
| `CORS_ORIGINS` | both | `http://localhost:5500` | The UI's origin(s), comma-separated |
| `AUTH_TOKEN_SECRET` | both | none (secret) | Signs (checkins) and verifies (points) access tokens |
| `INTERNAL_API_KEY` | both | none (secret) | Proves an `/internal/...` call comes from the other service |

The UI's service URLs are in `ui/config.js`.

## What happens when one service is down

- **Points down:** check-ins and votes still work. Their points wait in the outbox, marked "points
  pending" in the feed, and are delivered in order on a later check-in, vote or feed load.
- **Checkins down:** the scoreboard keeps answering from its last copy of the crew, with a notice
  that it may be out of date. Changes (setting a forfeit, uploading proof) and week settlement wait
  until Checkins is back, because they need the current crew.
- **Cold start on Azure:** the UI shows "Starting up…" and retries for about a minute.

## Tests and coverage

Each service has its own tests, run from its folder:

```bash
cd services/checkins && pytest --cov=app --cov-report=term-missing
cd services/points && pytest --cov=app --cov-report=term-missing
```

Result: **checkins 222 tests, 99% of core logic; points 179 tests, 99% of core logic.**

- Unit tests (most of them): pure rules and services against a temporary SQLite. Each service's
  tests replace the other service with a fake behind its port.
- Route and adapter tests: the internal endpoints, the internal key, CORS, and the HTTP clients
  against a stub server (`httpx.MockTransport`).
- Integration tests across the seam (`services/checkins/tests/integration/`): both real services
  as separate processes, including with one of them stopped.

The `routes.py` files are excluded from coverage (see [ADR-4](ADR.md)).

## Project structure

```
services/
  checkins/              auth + Goals & Check-ins: main.py, requirements.txt, app/, tests/, seed_demo.py
    app/auth/            users, sessions, groups, invite codes, signed access tokens
    app/checkins/        goals, check-ins, votes, comments, nudges, the points outbox and its HTTP client
  points/                Points & Forfeits: main.py, requirements.txt, app/, tests/, seed_demo.py
    app/points/          scoring, leaderboard, forfeits, settlement, the Checkins directory client
  */app/shared/          small modules copied into both services (time and week rules, uploads,
                         internal key and CORS)
ui/                      the static frontend: index.html, config.js, api.js, app.js, styles.css
```

Each domain is layered the same way: `routes.py` (HTTP only) → `service.py` (business rules) →
`repository.py` (parameterised SQL only) → the service's own database, or a client module → the
other service.

## Documentation

- [ADR.md](ADR.md): the five architecture decision records
- [AI_USAGE.md](AI_USAGE.md): the log of how AI was used, phase by phase
- [CLAUDE.md](CLAUDE.md): the working agreement and decision log used throughout the project
