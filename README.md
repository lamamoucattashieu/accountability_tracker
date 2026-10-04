# lockin.

**No ghosting your goals.** A habit tracker for friend groups: everyone sets weekly goals, posts
photo proof, and the crew keeps each other honest. Friends can call cap on a suspicious check-in,
reply to it, or nudge someone who's slacking. Points add up on a weekly leaderboard, and the week's
lowest scorer does the forfeit that last week's winner picked.

Individual Assignment 1, Software Development & DevOps (IE Madrid): a single-process monolith
built to be Dockerized and deployed to Azure in Assignment 2.

## Features

| Domain | What it does |
|---|---|
| **Auth & groups** (shared) | Register/login with hashed passwords and a session cookie, crews with invite codes |
| **Goals & Check-ins** | Weekly goals, photo check-ins, rejection votes, comments on proof, nudges |
| **Points & Forfeits** | Weekly scoring with a per-goal cap and streak bonus, leaderboard, forfeits, lazy week settlement, proof upload |

The two feature domains only talk through each other's service functions, never each other's
tables (see [ADR-2](ADR.md)).

## Requirements

- Python 3.13 (3.11+ should work)
- Nothing else: SQLite ships with Python, and the frontend is plain HTML/CSS/JS served by the app.

## Setup and run

```bash
git clone https://github.com/lamamoucattashieu/accountability_tracker.git
cd accountability_tracker
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

Open **http://localhost:8000/**. The database schema is created automatically on startup; there is
no setup step and no `.env` file is needed. The interactive API docs are at **http://localhost:8000/docs**.

## Configuration

Everything is configured through environment variables, all optional:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port to listen on (the app always binds `0.0.0.0`) |
| `DATA_DIR` | `./data` | Where all data lives: the SQLite file and uploaded photos |
| `COOKIE_SECURE` | `false` | Set to `true` behind https so the session cookie is only sent over https |

Data locations:

- SQLite database: `DATA_DIR/app.db`
- Uploaded photos: `DATA_DIR/uploads/`

Example: `PORT=9000 DATA_DIR=/tmp/lockin python main.py` (on Windows PowerShell:
`$env:PORT=9000; $env:DATA_DIR="C:\tmp\lockin"; python main.py`).

## Tests and coverage

```bash
pytest --cov=app --cov-report=term-missing
```

Result: **303 tests pass, 99% coverage of core logic** (787 statements, 2 not covered).

Coverage is measured on the core business logic: services, pure rule functions, repositories,
config and the shared modules. The `routes.py` files are excluded in [`.coveragerc`](.coveragerc)
because they are thin HTTP glue (parse input, call a service, map its errors to status codes); they
were checked with end-to-end runs against a real server instead. Every test uses a temporary
`DATA_DIR`, never the real database. See [ADR-4](ADR.md) for the testing approach.

## Project structure

```
main.py                  starts the app: binds 0.0.0.0, PORT, schema on startup, serves the UI
requirements.txt         the one dependency manifest
app/
  config.py              environment settings and shared business constants
  db.py                  SQLite connection (foreign keys on) and schema creation
  auth/                  users, sessions, groups, invite codes (shared by both domains)
  checkins/              Goals & Check-ins domain: goals, check-ins, votes, comments, nudges
  points/                Points & Forfeits domain: scoring, leaderboard, forfeits, settlement
  shared/                image uploads and the week/time definitions used by both domains
  static/                the frontend: index.html, styles.css, api.js, app.js
tests/                   pytest suites per domain, with a temporary DATA_DIR per test
```

Each domain is layered the same way: `routes.py` (HTTP only) → `service.py` (business rules) →
`repository.py` (parameterised SQL only) → SQLite.

## Deployment contract (Assignment 2)

| Requirement | How it's met |
|---|---|
| Single process, one command | `python main.py` |
| Binds `0.0.0.0` | `uvicorn.run(app, host="0.0.0.0", ...)` in `main.py` |
| Port from one variable | `PORT`, default 8000 |
| No interactive setup | Schema created with `CREATE TABLE IF NOT EXISTS` on startup |
| SQLite at one documented path | `DATA_DIR/app.db` |
| No external runtime dependency | SQLite file and uploads both live in `DATA_DIR` |
| One dependency manifest | `requirements.txt` |
| No Dockerfile or CI needed | None in the repo |
| Configurable through env vars only | `PORT`, `DATA_DIR`, `COOKIE_SECURE`; no `.env` required |
| Ready in seconds | Starts in under a second on a laptop |

## Documentation

- [ADR.md](ADR.md): the five architecture decision records
- [AI_USAGE.md](AI_USAGE.md): the log of how AI was used, phase by phase
- [CLAUDE.md](CLAUDE.md): the working agreement and decision log used throughout the project
