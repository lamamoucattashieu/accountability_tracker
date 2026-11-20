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

- Docker (Docker Desktop on Windows or macOS). On a Mac with Apple Silicon, turn on "Use Rosetta
  for x86_64/amd64 emulation" in Docker Desktop's settings: SQL Server only ships for amd64.
- Python 3.13, only to run the tests, the demo seed or a single service outside Docker.

## Running everything with Docker Compose

```bash
git clone https://github.com/lamamoucattashieu/accountability_tracker.git
cd accountability_tracker
cp .env.example .env        # then replace every value (letters and digits, 16+ characters)
docker compose up --build
```

Open **http://localhost:5500/**. That starts:

| Container | What it is | Port |
|---|---|---|
| `sqlserver` | SQL Server 2022, data in the `sqlserver-data` volume | 1433 |
| `db-init` | runs [`db/init.sql`](db/init.sql) once and exits: the two databases and one login per service | |
| `checkins` | the Checkins service, built from `services/checkins/Dockerfile` | 8000 |
| `points` | the Points service, built from `services/points/Dockerfile` | 8001 |
| `ui` | nginx serving `ui/` | 5500 |

The very first start on an empty volume is slow (SQL Server creates its system databases; it took
about 10 minutes here); later starts take seconds. Each service creates its own tables from its
migrations when it starts. `docker compose down` keeps the data; only `docker compose down -v`
deletes it. Running the stack accepts Microsoft's SQL Server licence (Developer edition,
`ACCEPT_EULA` in `docker-compose.yml`).

Every password and secret comes from `.env`, which is gitignored; `docker-compose.yml` reads them
with `${NAME:?}` and refuses to start if one is missing. Each service connects with its own
database login (`checkins_app`, `points_app`), which can only reach its own database; `sa` is used
only by `db-init` and the tests.

To see a service fail on its own: `docker compose stop points` (check-ins still work and show
"points pending"; `docker compose start points` delivers them), or `docker compose stop checkins`
(the scoreboard keeps answering from its last copy of the crew).

## Running a single service outside Docker

Useful while developing one service. Start only SQL Server and the logins with compose, then run
the service from its folder with its own login (the passwords are the ones in your `.env`):

```bash
docker compose up -d db-init            # starts sqlserver, creates the databases and logins
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r services/checkins/requirements-dev.txt -c services/checkins/constraints.txt
cd services/checkins
export DATABASE_URL="mssql+pymssql://checkins_app:<CHECKINS_DB_PASSWORD>@localhost:1433/checkins"
export AUTH_TOKEN_SECRET=<from .env> INTERNAL_API_KEY=<from .env>
python main.py                          # http://localhost:8000; POINTS_URL defaults to localhost:8001
```

Points is the same from `services/points`, with `points_app`, the `points` database and port 8001.
Every setting is an environment variable (see Configuration).

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

On a fresh stack (`docker compose down -v`, then `docker compose up -d --build`), seed the demo
crew in two halves from your Python environment, each into its own service's database through the
published ports, with that service's own login:

```bash
cd services/checkins
DATABASE_URL="mssql+pymssql://checkins_app:<CHECKINS_DB_PASSWORD>@localhost:1433/checkins"   AUTH_TOKEN_SECRET=<from .env> INTERNAL_API_KEY=<from .env> python seed_demo.py
cd ../points
DATABASE_URL="mssql+pymssql://points_app:<POINTS_DB_PASSWORD>@localhost:1433/points"   AUTH_TOKEN_SECRET=<from .env> INTERNAL_API_KEY=<from .env> python seed_demo.py
```

The Checkins half (people, goals, check-ins, votes, comments, nudges) delivers its points to the
running Points container; the Points half (forfeits, settled weeks, proof, next week's forfeit)
finds the crew through Checkins' API. Log in as **`maya`** with password **`lockin-demo`** (`leo`,
`zoe` and `sam` use the same password). Each half refuses to run on a database that already has
data. The seed is a development tool: it isn't in the images.

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

The tests run against the compose SQL Server, never Azure SQL. Start it with
`docker compose up -d sqlserver`; the tests read `TEST_DATABASE_ADMIN_URL` (its `master` database
as `sa`, already in `.env.example`) and create their own scratch databases, which they drop at the
end. Install the test tools with `requirements-dev.txt`, then:

```bash
cd services/checkins && pytest --cov=app --cov-report=term-missing   # unit and integration tests
cd services/points && pytest --cov=app --cov-report=term-missing
docker compose up -d --build && pytest e2e                            # from the repo root: the smoke test
```

Result: **checkins 261 tests, 99% of core logic; points 211 tests, 97% of core logic; the smoke
test passes on the stack.**

- Unit tests (most of them): pure rules, and services against a scratch database built by the real
  migrations, emptied before each test. Each service's tests replace the other service with a fake.
- Migration runner tests: order, once only, a second start applying nothing, a failing migration
  rolled back, an edited one refused, two copies at once, and a migration that changes a table
  that already holds data.
- Route and adapter tests: `/health`, the request log, the internal endpoints, the internal key,
  CORS, and the HTTP clients against a stub server (`httpx.MockTransport`).
- Integration tests across the seam (`services/checkins/tests/integration/`): both real services as
  separate processes on their own databases, including with one of them stopped.
- One end-to-end smoke test ([`e2e/test_smoke.py`](e2e/test_smoke.py)) on the running compose
  stack: nginx, both services, both databases and the call across the seam, the way a user reaches
  them.

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
  */Dockerfile           each service's image: only main.py, app/ and migrations/, as a non-root user
ui/                      the static frontend: index.html, config.js, api.js, app.js, styles.css
db/init.sql              the databases and one login per service, for the compose stack
docker-compose.yml       the whole system locally: SQL Server, db-init, both services, nginx
e2e/                     the end-to-end smoke test
system.yaml              the system description (services, settings, calls, Azure names)
system.schema.json       the course's schema for system.yaml
```

Each domain is layered the same way: `routes.py` (HTTP only) → `service.py` (business rules) →
`repository.py` (parameterised SQL only) → the service's own database, or a client module → the
other service.

## Documentation

- [ADR.md](ADR.md): the five architecture decision records
- [AI_USAGE.md](AI_USAGE.md): the log of how AI was used, phase by phase
- [CLAUDE.md](CLAUDE.md): the working agreement and decision log used throughout the project
