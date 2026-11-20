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
- Docker, for a local SQL Server (each service has its own database on it)

## Setup and run (locally)

```bash
git clone https://github.com/lamamoucattashieu/accountability_tracker.git
cd accountability_tracker
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS / Linux: source .venv/bin/activate
pip install -r services/checkins/requirements.txt -r services/points/requirements.txt
```

**1. A local SQL Server** (until Phase 3's docker-compose does this), with a password you choose:

```bash
docker run -d --name lockin-sqlserver -e ACCEPT_EULA=Y -e "MSSQL_SA_PASSWORD=<your password>" \
  -p 1433:1433 mcr.microsoft.com/mssql/server:2022-latest
```

Running it accepts Microsoft's SQL Server licence (the free Developer edition). Then create the
two empty databases, `checkins` and `points` (for example with `sqlcmd` in the container:
`CREATE DATABASE checkins; CREATE DATABASE points;`). Each service creates its own tables on
startup from its migrations.

**2. The secrets.** They have no default, so a service refuses to start without them. Use the
same token secret and internal key in both services; each service gets its own database:

```bash
# macOS / Linux
export AUTH_TOKEN_SECRET=local-dev-secret INTERNAL_API_KEY=local-dev-key
# Windows PowerShell
$env:AUTH_TOKEN_SECRET="local-dev-secret"; $env:INTERNAL_API_KEY="local-dev-key"
```

**3. Run each service with its own `DATABASE_URL`** (special characters in the password must be
URL-encoded), and the UI:

```bash
cd services/checkins && DATABASE_URL="mssql+pymssql://sa:<password>@localhost:1433/checkins" python main.py   # :8000
cd services/points && DATABASE_URL="mssql+pymssql://sa:<password>@localhost:1433/points" python main.py       # :8001
python -m http.server 5500 -d ui            # from the repo root: the UI
```

Open **http://localhost:5500/**. API docs: http://localhost:8000/docs and http://localhost:8001/docs.

## Database and migrations

Each service owns one database and touches no other. Its schema exists only in versioned
migrations, `services/<service>/migrations/NNN_name.sql`, applied in order on startup:

- each migration runs once, in its own transaction, and is recorded in `schema_migrations`; a
  second start applies nothing (the log says `migrations: nothing to apply`);
- an applied migration is never edited: its SHA-256 is recorded, and a changed file stops the
  service from starting. Corrections go in a new migration;
- nothing drops or recreates tables on startup.

Connecting is retried while the database is paused or resuming (Azure SQL serverless), up to
about 2 minutes at startup and with short backoff for requests; a request that still can't reach
the database gets a clear 503.

## Demo data (optional)

With both services running on empty databases, seed the demo crew in two halves, each into its
own service's database:

```bash
cd services/checkins && python seed_demo.py   # people, goals, check-ins, votes, comments, nudges
cd services/points && python seed_demo.py     # forfeits, settled weeks, proof, next week's forfeit
```

(with the same environment variables as when running each service). Log in as **`maya`** with
password **`lockin-demo`** (`leo`, `zoe` and `sam` use the same password). Each half refuses to run
on a database that already has data.

## Configuration

Everything is configured through environment variables. Secrets have no default.

| Variable | Service | Default | Purpose |
|---|---|---|---|
| `PORT` | both | 8000 (checkins), 8001 (points) | Port to listen on (always binds `0.0.0.0`) |
| `DATABASE_URL` | both | none (secret) | `mssql+pymssql://user:password@host:1433/database`: the service's own database |
| `AUTH_TOKEN_SECRET` | both | none (secret) | Signs (checkins) and verifies (points) access tokens |
| `INTERNAL_API_KEY` | both | none (secret) | Proves an `/internal/...` call comes from the other service |
| `POINTS_URL` | checkins | `http://localhost:8001` | Where Points is |
| `POINTS_TIMEOUT_S` | checkins | `2` | Timeout of every call to Points |
| `CHECKINS_URL` | points | `http://localhost:8000` | Where Checkins is |
| `CHECKINS_TIMEOUT_S` | points | `2` | Timeout of every call to Checkins |
| `CORS_ORIGINS` | both | `http://localhost:5500` | The UI's origin(s), comma-separated |
| `GIT_SHA` | both | `dev` | The commit the code was built from, shown by `/health` |

The UI's service URLs are in `ui/config.js`. Photos are stored in each service's database; nothing
is written to disk. [`system.schema.json`](system.schema.json) (provided by the course) defines the
`system.yaml` that describes all of this.

## Health and logs

- `GET /health` on each service: `200 {"status": "ok", "db": "ok", "version": "<git sha>"}` when the
  service can read and write its own database, `503` otherwise. It never depends on the other
  service.
- One JSON line per request on stdout, for example
  `{"service": "points", "method": "GET", "path": "/groups/1/leaderboard", "status": 200, "duration_ms": 14.2}`.
  Only the path is logged: never the query string, headers or bodies.

## What happens when one service is down

- **Points down:** check-ins and votes still work. Their points wait in the outbox, marked "points
  pending" in the feed, and are delivered in order on a later check-in, vote or feed load.
- **Checkins down:** the scoreboard keeps answering from its last copy of the crew, with a notice
  that it may be out of date. Changes (setting a forfeit, uploading proof) and week settlement wait
  until Checkins is back, because they need the current crew.
- **Cold start on Azure:** the UI shows "Starting up…" and retries for about a minute.

## Tests and coverage

The tests run against a real SQL Server, never Azure SQL: set `TEST_DATABASE_ADMIN_URL` to the
local server's `master` database (for example `mssql+pymssql://sa:<password>@localhost:1433/master`,
or put that line in the repository's `.env`, which is gitignored). Each run creates its own scratch
databases and drops them at the end. Then, from each service's folder:

```bash
cd services/checkins && pytest --cov=app --cov-report=term-missing
cd services/points && pytest --cov=app --cov-report=term-missing
```

Result: **checkins 260 tests, 99% of core logic; points 210 tests, 97% of core logic.**

- Unit tests (most of them): pure rules, and services against a scratch database built by the real
  migrations, emptied before each test. Each service's tests replace the other service with a fake.
- Migration runner tests: order, once only, a second start applying nothing, a failing migration
  rolled back, an edited one refused, two copies at once, and a migration that changes a table
  that already holds data.
- Route and adapter tests: `/health`, the request log, the internal endpoints, the internal key,
  CORS, and the HTTP clients against a stub server (`httpx.MockTransport`).
- Integration tests across the seam (`services/checkins/tests/integration/`): both real services as
  separate processes on their own databases, including with one of them stopped.

The `routes.py` files are excluded from coverage (see [ADR-4](ADR.md)).

## Project structure

```
services/
  checkins/              auth + Goals & Check-ins: main.py, requirements.txt, app/, migrations/, tests/, seed_demo.py
    app/auth/            users, sessions, groups, invite codes, signed access tokens
    app/checkins/        goals, check-ins, votes, comments, nudges, the points outbox and its HTTP client
  points/                Points & Forfeits: main.py, requirements.txt, app/, migrations/, tests/, seed_demo.py
    app/points/          scoring, leaderboard, forfeits, settlement, the Checkins directory client
  */migrations/          the service's schema, as numbered SQL files
  */app/shared/          small modules copied into both services: database connections and the
                         migration runner, health and request log, time and week rules, photo
                         checks, internal key and CORS
ui/                      the static frontend: index.html, config.js, api.js, app.js, styles.css
system.schema.json       the course's schema for system.yaml
```

Each domain is layered the same way: `routes.py` (HTTP only) → `service.py` (business rules) →
`repository.py` (parameterised SQL only) → the service's own database, or a client module → the
other service.

## Documentation

- [ADR.md](ADR.md): the five architecture decision records
- [AI_USAGE.md](AI_USAGE.md): the log of how AI was used, phase by phase
- [CLAUDE.md](CLAUDE.md): the working agreement and decision log used throughout the project
