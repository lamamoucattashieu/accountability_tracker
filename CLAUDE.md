# CLAUDE.md

## Context
Software Development & DevOps (IE Madrid). A habit tracker for friend groups: members set goals,
post photo check-ins, compete on a weekly leaderboard, and the week's lowest scorer does a forfeit
the group agreed on in advance.

**Assignment 1: submitted and done** (deadline 2026-10-04 23:59). All phases (0-7) and the
redesign are merged (PRs #1-#13). A1 spec: @docs/assignment_spec.md

**Assignment 2: in progress.** Deadline **2026-11-29 23:59** (moved from 11-22); my target is
to tag `submission` by **2026-11-25 23:59**. Spec: @docs/assignment2_spec.md
Nothing is provided: I write the Dockerfiles, compose file, pipeline and deployment myself.

A2 roadmap (from class):
1. Split the monolith into two services, one per domain (Goals & Check-ins, Points & Forfeits),
   talking over HTTP, each with its own database.
2. One Dockerfile per service.
3. Docker Compose runs the whole system locally with one command.
4. CI/CD pipelines that take the same images from localhost to the Azure cloud environment.

The Hard constraints, Architecture, A2 decisions and A2 phases sections describe A2. "Decisions
that are mine" and "A1 phases (done)" are the A1 record and stay as they are.

---

## How we work
I'll be examined on this code on paper, closed-book, with no notes. Every line has to be
something I can explain and defend. Optimize for readable, boring, correct code over clever code.

**This protocol applies to ALL work from now on, not only phases:** fixes, refactors, docs,
infrastructure and Azure setup. Any time a choice is needed, ask me as a question with options,
trade-offs and your recommendation, and wait for my answer.

1. **PLAN:** read the spec sections that apply (@docs/assignment2_spec.md), then give me a short
   plan: files, interfaces, schema changes, tests, commit order. Name the course concept behind
   each choice in one line.
2. **QUESTIONS:** list every decision the work needs as numbered questions. For each: 2-3
   options, the trade-off of each, and your recommendation with the reason. Include anything
   ambiguous in the spec or in conflict with this file. Never pick a default yourself. Then STOP.
3. **CONFIRM:** after I answer, restate my decisions as a short numbered list and wait for me to
   say "go". If my answers raise new questions, ask them first. Once I say "go", record each
   decision in "A2 decisions (mine)".
4. **BUILD:** on a branch, in small conventional commits. Never push without asking me.
5. **CLOSE:** the end-of-phase checklist below, including the AI_USAGE.md update.

Standing rules:
- **One phase at a time.** Don't touch the next phase until I say "next phase".
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

## Hard constraints (A2 spec, never violate)
- **Exactly two service containers**, one per domain, each from its own Dockerfile in
  `services/<name>/` with its own dependency manifest (soft cap ~12 third-party packages per
  service). Don't add any package without asking me. No third container (gateway, frontend, etc.).
- **Static UI** in `ui/` (plain HTML/CSS/JS, no build step), deployed to the Azure Storage static
  website `<prefix>ui`. Service base URLs come from a `config.js` generated at deploy time, never
  hardcoded. Locally, compose serves `ui/` with stock `nginx:alpine` (folder mounted, no Dockerfile).
- **Database per service:** SQL Server. Locally, one `mcr.microsoft.com/mssql/server:2022-latest`
  container with one database per service, created by an idempotent `db/init.sql` run by a one-off
  compose service. On Azure, one serverless Azure SQL database per service (free offer) on one
  server `<prefix>-sql`. Each service has its own login with access to its own database only, and
  reads its connection string from `DATABASE_URL`. No service ever touches the other's database.
- **HTTP between services only**, each locating the other through an env var. Every outbound
  call has a timeout. No hardcoded hostnames or ports.
- **CORS:** each service accepts cross-origin requests only from the UI's origin.
- **Versioned migrations** in `services/<name>/migrations/`, applied in order on startup, each
  exactly once (recorded in a `schema_migrations` table). Applied migrations are never edited.
  Never drop or recreate tables on boot. At least one migration changes a table that already
  holds data.
- **`GET /health`** on every service: 200 `{"status", "db", "version": <git sha>}` when it can
  read and write its own database, 503 otherwise. Reflects its own state, not the other service's.
- **One log line per request** to stdout: method, path, status, duration.
- **Dockerfiles:** no `COPY . .`, no secrets or `.env` in the image, pinned dependencies,
  non-root user.
- **`docker compose up --build`** from a clean clone brings up the whole system.
- **CI on every push/PR:** lint, test, coverage ≥70% per service, validate `system.yaml` and both
  `openapi.yaml`, build every image. CI never connects to Azure SQL.
- **CD on push to `main` only:** SHA-tagged images to GHCR, deploy to Container Apps (Consumption,
  min 0 / max 1 replicas), upload the UI to `$web`, then fail the run if `/health` isn't 200 in
  time. Sign-in through the `<prefix>-github` managed identity over OIDC.
- **Cold starts:** connect to the database with retries and backoff (paused DB, error 40613). The
  UI shows a designed "starting up, try again" state for a 503, never a blank page or hang.
- **No secrets in the repo** (source, workflows, compose file or history). Secrets live in GitHub
  Actions secrets and reach Container Apps as secrets, never as plain env vars.
- **Azure allowance:** 2 Container Apps (one environment), 2 serverless SQL databases, 1 storage
  account, the managed identity. Nothing else, everything in `rg-<prefix>`, all named with my
  prefix. Nothing changed by hand in the portal after the initial setup.
- Same stack as A1 (Python + FastAPI). Configured through env vars only.

---

## Architecture (A2: two services)

### Service 1: Goals & Check-ins (`services/checkins/`)
- Goals, photo check-ins, rejection votes, comments, nudges (as in A1)
- **Also owns auth** (decided for A2): users, groups, invite codes, sessions and membership,
  moved in from the A1 shared `app/auth/`. Chosen because Checkins checks membership on almost
  every request; putting auth in Points would make most Checkins requests cross the seam.
- Owns tables: `users`, `sessions`, `groups`, `group_members`, `goals`, `checkins`,
  `checkin_votes`, `checkin_comments`, `nudges`, and `points_outbox` (points changes not yet
  delivered to Points)
- Check-in photos are stored in this service's database (see Photos below)

### Service 2: Points & Forfeits (`services/points/`)
- Weekly scoring, leaderboard, forfeits, lazy settlement, forfeit proof (as in A1). The
  `UNIQUE (group_id, week_start)` settlement guarantee carries over to SQL Server.
- Owns tables: `point_events`, `forfeits`, `settlements`, `forfeit_assignments`, and
  `group_snapshots` (its last copy of each group from Checkins)
- Forfeit proof photos are stored in this service's database
- Gets members, `joined_at` and `group_created_at` from Checkins over HTTP, since it no longer
  shares a process with auth

### The seam (HTTP now)
- **Server-side cross-seam flow: Checkins calls Points** (decided for A2, keeps ADR-2's direction).
  `record_completion` / `revoke_completion` become HTTP calls from Checkins to Points, located
  by an env var (e.g. `POINTS_URL`), with a timeout.
- The A1 rules still hold: only IDs, timestamps and `times_per_week` cross the seam, and both
  calls stay **idempotent** on `checkin_id`, so a repeated call is a no-op.
- **A2 change:** the A1 "one transaction" guarantee (rejection + points change commit together)
  can't survive the split, because they're now in two databases. That integrity loss goes in ADR-7.
- **When Points is down** (my decision, see A2 decisions): the check-in or rejection is
  still saved in Checkins, flagged as not yet synced to Points, and the user is told points will
  update later. Checkins retries unsynced calls lazily on later requests, the same pattern as lazy
  settlement, so no background job is needed. Retrying is safe because the calls are idempotent.
- **When Checkins is down:** Points keeps serving the leaderboard and forfeits from its own data
  if possible. Anything that needs membership fails with a clear 503 message.
- Every endpoint one service calls on the other must appear in the other's `openapi.yaml` with
  the same shapes.

### Photos
- Stored as image bytes (`VARBINARY`) in the database of the service that owns them (decided for
  A2), because containers that scale to zero have no persistent disk and the Azure allowance has
  no room for blob storage. The 5 MiB `MAX_UPLOAD_BYTES` cap keeps rows bounded. A1's
  content/size/pixel checks still apply. The `DATA_DIR/uploads/` files of A1 go away.

### Layering inside each service
- `routes.py`: thin endpoints that parse input, call the service, and map results and errors to
  HTTP. No business logic.
- `service.py`: business logic. Rules (vote threshold, scoring, tie-breaking) are **pure
  functions** that take plain values and return decisions, so they're testable without a DB.
- `repository.py`: SQL only, with parameterized queries. No business decisions.
- A client module per outbound dependency (e.g. a points client in Checkins) holds the URL,
  timeout and error mapping, so services never build HTTP requests themselves.
- Flow: request -> route -> service -> repository -> SQL Server (or -> client -> other service)

### Database conventions
- Timestamps stored in UTC, ISO 8601
- Invariants enforced by constraints where possible (UNIQUE, CHECK, NOT NULL, foreign keys
  *within* a service), not only in Python. IDs from the other service are plain columns, with
  integrity enforced in code or deliberately not enforced.
- Any write that changes more than one row or table in one service as a single logical action
  runs in **one transaction**
- Schema changes only through a new numbered migration, never by editing an applied one

### Errors
Use meaningful status codes: 401 not logged in, 403 not allowed (e.g. not a group member), 404
not found, 409 conflicts with current state (duplicate vote, already settled), 422 invalid input,
503 when the other service or the database is unavailable. Services raise domain errors, and
routes translate them. No bare 400s or 500s for expected cases.

### Still open (ask me before building)
- Nothing. Infrastructure definition was decided in Phase 5 (Azure CLI, see A2 decisions).

---

## A2 decisions (mine)
Recorded only after I confirm them (step 3 of How we work), one line each, with the phase they
came from. Never record a decision I didn't make.

| Decision | From | My answer |
|---|---|---|
| Where tests live | Before Phase 1 | Per service, in `services/<name>/tests/` |
| End-to-end testing | Before Phase 1 | One end-to-end smoke test on the compose stack, on top of unit and integration tests |
| Where auth lives | Before Phase 1 | Inside Goals & Check-ins (users, groups, invite codes, sessions, membership) |
| Direction of the server-side cross-seam flow | Before Phase 1 | Checkins calls Points (`record_completion` / `revoke_completion` over HTTP), keeping ADR-2's direction |
| Behaviour when Points is down | Before Phase 1 | Save the check-in or rejection, flag it as not synced, retry lazily on later Checkins requests (safe because the calls are idempotent) |
| Where photos are stored | Before Phase 1 | As `VARBINARY` in the database of the service that owns them |
| How Points knows who is calling | Phase 1 | A token signed with HMAC-SHA256 (`AUTH_TOKEN_SECRET`, standard library) holding user id, session id and expiry, issued by Checkins at login/register and verified locally by both; Checkins also checks the session row, so logout is immediate there and only at expiry in Points |
| Where the browser keeps the token | Phase 1 | `localStorage`, 7 days (the A1 login lifetime), sent as `Authorization: Bearer`; photos fetched as blobs. XSS defence is the `textContent`-only rule; no CSRF, the browser never adds the header |
| Protecting `/internal/...` endpoints | Phase 1 | A separate shared secret `INTERNAL_API_KEY` in an `X-Internal-Key` header, compared in constant time |
| Membership in Points | Phase 1 | One `GET /internal/groups/{id}` per request, cached in `group_snapshots`. Checkins down: reads served from the snapshot marked `membership_stale`, changes 503, no snapshot at all 503 |
| Settlement and incomplete data | Phase 1 | Never settle from a stale snapshot, nor while Checkins reports `pending_points_sync` for the group |
| "Not yet synced" store | Phase 1 | A `points_outbox` table written in the same local transaction, with the payload as it was at write time |
| When the outbox retries | Phase 1 | After each check-in or vote and on feed load, at most `OUTBOX_BATCH` (20) rows, oldest first, stopping at the first failure |
| Outbox row Points rejects (4xx) | Phase 1 | Marked failed, logged, skipped. Timeouts, 5xx and a refused key stay pending |
| HTTP client between services | Phase 1 | `httpx==0.28.1` in both services (also gives `TestClient` and `MockTransport`, so ADR-4 changes) |
| Timeouts | Phase 1 | 2 s both ways, named constants overridable by `POINTS_TIMEOUT_S` / `CHECKINS_TIMEOUT_S` |
| Code both services need | Phase 1 | Copied into each service (`timeutils`, `uploads`, `tokens`, `internal_api`, the 48h window), kept identical; Phase 4 CI checks the copies match |
| Databases in Phase 1 | Phase 1 | One SQLite file per service in its own `DATA_DIR` (`checkins.db`, `points.db`) until SQL Server in Phase 2 |
| Photos in Phase 1 | Phase 1 | Files under each service's `DATA_DIR/uploads` until Phase 2 |
| Package layout | Phase 1 | `services/checkins/app/` and `services/points/app/`, moved with `git mv` |
| Ports and env vars | Phase 1 | checkins 8000, points 8001, UI 5500; `POINTS_URL`, `CHECKINS_URL`, `POINTS_TIMEOUT_S`, `CHECKINS_TIMEOUT_S`, `CORS_ORIGINS`, `AUTH_TOKEN_SECRET`, `INTERNAL_API_KEY`, `DATA_DIR`. Secrets have no default: a service refuses to start without them (replaces A1's "runs without a `.env`") |
| Demo seed | Phase 1 | Two halves, one per service, run in order with both running; backdated times travel in the outbox; the Points half finds the crew through Checkins' public API |
| `/health` in Phase 1 | Phase 1 | Minimal `{"status": "ok", "service": ...}`; the full one in Phase 2 |
| Azure cold-start 503 in the UI | Phase 1 | "Starting up…" banner and automatic retries with backoff for about 60 s, then "try again" |
| Integration test across the seam | Phase 1 | Both real services as subprocesses, including stopping one; client unit tests use an HTTP stub |
| Upload tests | Phase 1 | Run in both services, so each copy is covered |
| ADR statuses | Phase 1 | ADR-2 → Superseded by 6 now, ADR-3 → by 7 in Phase 2, ADR-4 → by 9 in Phase 4 |
| Usernames across the seam | Phase 1 | Points returns user ids only; the UI shows names from Checkins' `/groups/{id}/members`, like the feed |
| Internal API contract | Phase 1 | `POST /internal/completions`, `POST /internal/completions/{checkin_id}/revocation` (with `revoked_at` from Checkins), `GET /internal/groups/{id}`, all as built |
| SQL Server driver | Phase 2 | `pymssql==2.4.6` (bundles FreeTDS, no system driver); `DATABASE_URL` = `mssql+pymssql://user:password@host:1433/database`, parsed with `urllib`, a secret with no default |
| Timestamps in SQL Server | Phase 2 | ISO 8601 UTC strings in `NVARCHAR(32)`, as in A1; `week_start` CHECK is a Monday via `DATEDIFF` from 1900-01-01, independent of `DATEFIRST` |
| Usernames | Phase 2 | `NVARCHAR(50)` with `USERNAME_MAX_LENGTH = 50` (422 above); usernames and invite codes stay case-sensitive (`Latin1_General_100_CS_AS`) |
| Idempotent inserts | Phase 2 | Plain INSERT; a duplicate key on the named constraint means "already done"; CHECK violations still raise |
| Settlement race | Phase 2 | `sp_getapplock` per group in the transaction; lock timeout → `SettlementBusy`; `UQ_settlements_group_week` stays the backstop |
| Open-transaction guard | Phase 2 | The connection wrapper records unsaved writes (`in_transaction`) |
| Placeholders | Phase 2 | `%s` / `%(name)s` written out in every query |
| Migrations | Phase 2 | Numbered SQL files with our own runner: each in its own transaction with its `schema_migrations` row; SHA-256 checksum (line endings normalised) refuses an edited applied file; `sp_getapplock` stops two copies |
| Connection retry | Phase 2 | Only connecting is retried, never a query. Retryable: 40613, 40197, 40501, 4060, 20002, 20003, 20009. Requests wait 0.5/1/2/4/8 s then 503; startup up to 120 s then exits; 5 s per attempt |
| Lock timeout | Phase 2 | 5 s on every connection |
| `/health` | Phase 2 | Reads `schema_migrations`, updates and commits the one `service_health` row; one 3 s attempt, no retry; version from `GIT_SHA` (default `dev`) |
| Request log | Phase 2 | One JSON line per request (service, method, path, status, duration_ms) via `print`; no query string, headers or bodies; uvicorn's access log off |
| Photos | Phase 2 | `VARBINARY(MAX)` + type column in the owning row, never selected by list queries. Replaces the Phase 1 "files until Phase 2" entry; A1's `PhotoMissing`, orphan-file cleanup and `DATA_DIR` are gone. Limits in the SQL file are literals, compared with the config constants by a test |
| Test database | Phase 2 | Local SQL Server container; one migrated scratch database per run per service, tables wiped and ids reset before each test; `TEST_DATABASE_ADMIN_URL` (or the gitignored `.env`); database tests fail, never skip |
| Demo seed | Phase 2 | Same two halves on SQL Server, ported together with each service |
| Databases before Phase 3 | Phase 2 | Created by hand on the local container and used as `sa`, until `db/init.sql` and per-service logins in Phase 3 |
| A1 data | Phase 2 | Not imported: fresh databases plus the seed |
| Shared database code | Phase 2 | `database.py`, `migrations.py` and `observability.py` copied identically into both services |
| `system.schema.json` | Phase 2 | Copied unchanged to the repo root now; the first `system.yaml` comes in Phase 3 with `docker-compose.yml` (its service names must match), validated by CI in Phase 4. It is a contract: every env var listed (defaults for all but secrets), service names = compose names, each cross-service call with its `METHOD /path`, `timeout_s` and `on_failure` |
| Other service's URL default | Phase 2 | Stays `localhost` in the code; compose sets `POINTS_URL` / `CHECKINS_URL` |
| Azure prefix | Phase 2 | IE username `lhvmoucattas.ieu2024`, prefix `lhvmoucattas-ieu2024` (container apps `lhvmoucattas-ieu2024-checkins` / `-points`, storage `lhvmoucattasieu2024ui`, all within the length limits) |
| Base image | Phase 3 | `python:3.13.5-slim-bookworm` (exact tag, the version the code is tested on) |
| Dependencies in the image | Phase 3 | Runtime `requirements.txt` only; test tools in `requirements-dev.txt`; every package pinned in `constraints.txt` (`pip freeze` inside the base image). Supersedes A1's single manifest with pytest |
| Container start | Phase 3 | `CMD ["python", "main.py"]`, one process, non-root uid 10001 |
| `GIT_SHA` | Phase 3 | Build argument baked into the image (`dev` locally, the commit in CD) |
| Healthchecks | Phase 3 | sqlserver `sqlcmd SELECT 1` (up to ~10 min on a first start); both services `/health`; ui none; the smoke test waits up to 120 s |
| Ports and passwords | Phase 3 | 8000, 8001, 5500→80, 1433; every password letters and digits only, 16+ characters |
| db-init | Phase 3 | `sqlcmd` from the same pinned SQL Server image; passwords as env vars (sqlcmd variables), `sa` as `SQLCMDPASSWORD` |
| Database logins | Phase 3 | Contained users `checkins_app` / `points_app` with exactly `db_ddladmin`, `db_datareader`, `db_datawriter` on their own database; password set again from `.env` on every run. Replaces "Databases before Phase 3" (by hand, as `sa`) |
| Volume and restarts | Phase 3 | Named volume `sqlserver-data`; `unless-stopped` for everything but db-init (`no`) |
| Pinned stock images | Phase 3 | SQL Server `2022-CU28-ubuntu-22.04`, nginx `1.29.8-alpine` |
| SQL Server licence | Phase 3 | `ACCEPT_EULA=Y` committed in `docker-compose.yml`; the README says running it accepts Microsoft's licence (Developer edition) |
| Test database | Phase 3 | `TEST_DATABASE_ADMIN_URL` points at the compose SQL Server; the Phase 2 container was removed |
| Smoke test | Phase 3 | `e2e/test_smoke.py` at the repo root, run with `pytest e2e` on the running stack |
| `system.yaml` values before Azure | Phase 3 | `public_url` `https://lhvmoucattasieu2024ui.z6.web.core.windows.net` (zone confirmed in Phase 5); registry `ghcr.io/lamamoucattashieu`; validated once with `check-jsonschema` in a throwaway environment (CI in Phase 4) |
| OpenAPI files | Phase 3 | `services/<name>/openapi.json` (FastAPI writes JSON; spec 8a allows .json) |
| Demo seed with compose | Phase 3 | Not in the images; run from the host against the published ports with each service's own login |
| Apple Silicon | Phase 3 | README note: Rosetta in Docker Desktop; no `platform:` in compose |
| Deadline and schedule | Phase 4 | Deadline moved to 2026-11-29; I submit by 2026-11-25: Phase 4 on 22, Phase 5 on 23, Phase 6 evidence on 24, docs and the `submission` tag on 25, 26-29 buffer |
| Linter | Phase 4 | `ruff==0.17.6` in each `requirements-dev.txt`, no config file or formatter; real errors only (`--select E4,E7,E9,F`, since ruff 0.17's defaults include style rules) |
| OpenAPI documents | Phase 4 | Generated from `app.openapi()` by one documented command and committed; CI regenerates them and fails on a difference; validated with `openapi-spec-validator`; CI checks every `calls:` endpoint in `system.yaml` exists in the called service's document |
| CI-only tools | Phase 4 | `check-jsonschema==0.39.0`, `openapi-spec-validator==0.9.0`, `pyyaml==6.0.4`, pinned inline in the workflow, in no requirements file |
| SQL Server in CI | Phase 4 | GitHub Actions service container on the compose image `2022-CU28-ubuntu-22.04`; `sa` password from the GitHub secret `CI_MSSQL_SA_PASSWORD` |
| CI job layout | Phase 4 | A matrix job per service (lint, tests, coverage, OpenAPI drift, image build, not pushed) plus one validation job; the checkins job also starts `../points` for the seam test, which relies on identical requirements |
| Coverage gate | Phase 4 | `fail_under = 70` in each `.coveragerc`, the same verdict locally and in CI |
| Copies check | Phase 4 | A `diff` step naming `app/shared/*.py` and `app/auth/tokens.py`, plus the `VOTING_WINDOW` line of each `config.py` |
| Action versions | Phase 4 | Major tags (`@v4`, `@v5`); commit SHAs named in ADR-9 as the stricter alternative |
| Smoke test in CI | Phase 4 | Not in CI: stays a local `pytest e2e` on the compose stack (ADR-9) |
| CI triggers | Phase 4 | `push` on every branch plus `pull_request` |
| Branch protection | Phase 4 | `main` requires CI to pass before merging (set by me in GitHub) |
| ADR-9 | Phase 4 | Written as a finished entry from my answers; ADR-4 → Superseded by 9 |
| CI runner | Phase 4 | `runs-on: ubuntu-24.04`, keeping Python 3.13.5: `ubuntu-latest` moved to 26.04, which has no 3.13.5 build (first run 44993733958 failed in `setup-python`; fixed in 44993965772) |
| Infrastructure definition | Phase 5 | Azure CLI: the initial setup run once by me and written step by step in the README (no passwords); the CD workflow only updates the Container Apps and uploads the UI. No Bicep/Terraform |
| Region | Phase 5 | `switzerlandnorth` for everything (my allowed list: austriaeast, polandcentral, switzerlandnorth, uaenorth, spaincentral; the free SQL offer isn't in spaincentral). If the free offer is refused there, ask me before moving |
| Container Apps logs | Phase 5 | Environment created with `--logs-destination none`: no Log Analytics workspace (it would be a resource outside the allowance); logs read with `az containerapp logs show` |
| Secrets on Azure | Phase 5 | GitHub secrets hold the two database passwords, `AUTH_TOKEN_SECRET` and `INTERNAL_API_KEY`; the pipeline builds each `DATABASE_URL` and sets them all as Container Apps secrets (`secretref:`) on every deploy, so rotating is changing the GitHub secret and re-running |
| Images in CD | Phase 5 | Plain `docker build --provenance=false` + `docker push`, signed in to GHCR with `GITHUB_TOKEN`; `ghcr.io/lamamoucattashieu/lockin-checkins` and `lockin-points`, tagged with the commit SHA; built after the reused CI passes |
| Post-deploy health check | Phase 5 | `/health` on each service every 10 s for up to 5 minutes, then the run fails |
| Container size | Phase 5 | 0.25 vCPU / 0.5 GiB per Container App, min 0 / max 1 replicas |
| Container Apps environment mode | Phase 5 | `--environment-mode WorkloadProfiles` (Microsoft's documented default) with both apps on the `Consumption` profile; no Dedicated profile. The CLI had created an Express (preview) environment by default, which rejected `--revision-suffix` in the first CD run (45684969529); it and the placeholder apps were deleted and recreated. Consumption-only was rejected as legacy |
| Schedule after the third slip | Phase 6 | Phase 6 on 27 (after Phase 5 ran past midnight), docs, report and the `submission` tag on 28, 29 only for fixes |
| Migration 002 | Phase 6 | Caps group names: longer names shortened (`LEFT`), `groups.name` becomes `NVARCHAR(60) NOT NULL` with a CHECK; `GROUP_NAME_MAX_LENGTH = 60` and 422 in `create_group` |
| Data on Azure before 002 | Phase 6 | Both halves of `seed_demo.py` run once from my machine against Azure through temporary exact-IP firewall rules, then one real check-in posted on the live site |
| Migration evidence | Phase 6 | A committed `docs/migration_evidence.md`: before/after query outputs, the CD run link and the startup log line |
| Partial-failure evidence | Phase 6 | Local, `docker compose stop points`, with screenshots and responses; nothing changed on Azure by hand |
| ADR-10 | Phase 6 | A message broker (Service Bus) deliberately not built; the `points_outbox` instead, and when a broker would be worth it |
| Who runs the setup | Phase 5 | Claude runs each `az` command in my session after showing it; outputs go into the README without passwords |
| Schedule after slipping a day | Phase 5 | Everything moves one day: Phase 5 on 24, Phase 6 evidence on 25, docs and the `submission` tag on 26, buffer 27-29 |
| Schedule after slipping a second day | Phase 5 | Phase 5 on 25, Phase 6 evidence on 26, docs and the `submission` tag on 27, buffer 28-29 |
| Resource group | Phase 5 | The empty `rg-lhvmoucattas-ieu2024` found in polandcentral is deleted and recreated in switzerlandnorth |
| Region, after setup started | Phase 5 | Everything in `austriaeast`: switzerlandnorth refused new SQL servers (`RegionDoesNotAllowProvisioning`), and only austriaeast reported SQL as Available. The switzerlandnorth resource group and storage account (both empty) were deleted and recreated there, so the app and its database share a region. Replaces the `switzerlandnorth` Region row |
| Databases without the free offer | Phase 5 | austriaeast refuses the free offer (`ProvisioningDisabled`) and it is the only allowed region that accepts SQL servers, so both databases are serverless without it: General Purpose, Gen5, 0.5-1 vCore, LRS backups, 2 GB max, 60-minute auto-pause (I chose 15, but Azure's minimum for GP_S_Gen5_1 here is 60, the same as the free offer). Paid from the student credit only while awake; a justified deviation from spec 7.3 in ADR-8, and I email the professor |
| UI upload | Phase 5 | The identity gets Storage Blob Data Contributor on the storage account; the pipeline uploads with `--auth-mode login`, never a storage key |
| GHCR pull | Phase 5 | Both packages made public after their first push (the code is public already); no registry credentials in Container Apps |
| Federated credentials | Phase 5 | Both subjects registered: the name form and the numeric-ID form, for `main` only |
| Non-secret deploy settings | Phase 5 | GitHub repository variables `PREFIX`, `RESOURCE_GROUP`, `UI_STORAGE` |
| `sqlcmd` for the Azure setup | Phase 5 | Run from the pinned SQL Server image, as `db-init` does |
| SQL admin | Phase 5 | SQL authentication admin (contained users with passwords need it); password generated locally, kept only in my password manager, never in the repo or GitHub |

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
| What a "week" is: start day, timezone, boundary time | Phase 4 | A check-in's `created_at` decides its week; weeks run Monday 00:00 UTC to Sunday 23:59:59 UTC |
| What earns points: each valid check-in, or meeting a goal's weekly target | Phase 4 | Each accepted check-in, but only the first `times_per_week` per goal per week; a rejected one frees its slot for a later one |
| Point values, and whether streaks give bonuses | Phase 4 | 1 point per counted check-in (`POINTS_PER_COMPLETION`). Streak bonus: +1 (`STREAK_BONUS`) per goal that hit its full weekly target this week and the previous week; flat, not growing |
| Tie-breaking for lowest score | Phase 5 | No tie-break: everyone tied at the lowest score shares the forfeit, each with their own proof. If every eligible member has the same score (including all zero), nobody loses. No random tie-break (untestable, feels unfair) |
| How the forfeit is agreed and when it locks | Phase 5 (changed in the UI redesign) | Only last week's #1 sets it (everyone tied at #1 can; after a week where nobody scored, everyone is #1), using last week's ranking as it stands (403 otherwise). Text trimmed, 1-200 chars, else 422. Append-only, never edited. A week's forfeit is the latest one set before that week's Monday 00:00 UTC, so it locks when the week starts; a mid-week change applies from next week |
| What happens if the loser never posts proof | Phase 5 | Deadline: 7 days after the settlement's settled_at. Overdue is computed on read, never stored. Late proof is accepted and shown as late. No point penalty, so scoring stays independent of forfeits |
| Whether members with zero check-ins can "lose" | Phase 5 | Yes; otherwise not participating would be a way out |

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

**Phase 4: Weekly scoring & leaderboard** (besides the table above)
- Ties share a rank with gaps (`RANK()`: 1, 1, 3). Members with zero points are shown, ranked last.
- A rejection after its week ended rescores that old week (and can end a streak). Points from a
  goal archived later are kept.
- Members only (404 missing group, then 403), for the current week or any week via
  `?week=YYYY-MM-DD` (any day of it).
- Streaks are per goal: a goal "hits" a week when its valid check-ins reach the target stored on
  that week's latest check-in. Recomputed on every read, never stored.
- Storage is a ledger, `point_events` (one row per check-in, `revoked_at` on rejection), not stored
  weekly totals, because the cap, freed slots, late rejections and streaks need recomputing.
  It has no foreign keys to other domains' tables.
- Idempotency is enforced in SQL: `ON CONFLICT (checkin_id) DO NOTHING` (not `INSERT OR IGNORE`,
  which would also hide CHECK violations) and `UPDATE ... WHERE revoked_at IS NULL`.
- The seam signature is fixed as `record_completion(conn, *, checkin_id, group_id, user_id,
  goal_id, times_per_week, completed_at)`. `conn` and `times_per_week` are deliberate exceptions to
  "only IDs and timestamps", because Points needs the target as it was at check-in time.
- `create_checkin` deletes the photo if either the insert or `record_completion` fails.
- New auth seam function `list_members` (plain dicts of id and username). No backfill of points
  for check-ins made before Phase 4.

**Phase 5: Forfeits** (besides the table above)
- Settlement time: a week settles only once `now >= week end + 48h` (Wednesday 00:00 UTC), when
  every voting window for its check-ins has closed, so its ranking can no longer change. After
  that it is final. Until then the leaderboard marks that week as provisional.
- Eligibility: members at settlement time who joined before the week started. Known limitation:
  there is no leave feature, so eligibility is "current members who joined before the week".
- No forfeit set: the week is still settled (so it isn't retried on every request) with no
  assignment, and the response says no forfeit was set.
- Backlog: when triggered, every settleable week since the group was created is settled, oldest
  first, each in its own transaction. Weeks before the group existed are never settled, and the
  creation week has no losers (nobody joined before it started).
- Visibility: group members see settlements, assignments, proof status and proof photos (404 for a
  missing group, then 403). Only the assigned member uploads proof, and only once (409 after).
  Nobody votes on proof: deliberately not built.
- Tables: `settlements` (one row per group and week, `UNIQUE (group_id, week_start)`, nullable
  `forfeit_id`, `settled_at`) and `forfeit_assignments` (one row per loser,
  `UNIQUE (settlement_id, user_id)`, the losing `score` frozen at settlement, proof path and time).
- Settlement runs inside the points service through one function, `ensure_settled(conn, group_id,
  now)`, never from route handlers. It is the first call before any other write in every function
  that uses it, and it refuses to start if `conn.in_transaction` is true, so it can never commit a
  caller's half-done work. **This is the one documented exception to the 2b rule that commits stay
  in `get_db()`**: each backlog week commits on its own.
- A GET (the leaderboard, forfeit and settlement reads) can write settlements. Accepted REST
  smell, because lazy settlement has no other trigger; settling is idempotent.
- Pure rules live in `app/points/rules.py` (single responsibility: rules separate from the
  service that orchestrates them).
- The 48h voting window, the settlement delay (defined as the voting window, so they can't drift
  apart), the 7-day proof deadline and the 200-char forfeit limit are named constants in
  `config.py`.
- Seam changes: `get_leaderboard` takes `now` and returns `provisional`; `auth_service.list_members`
  also returns `joined_at`; new `auth_service.group_created_at`.

**Phase 6: Frontend**
- Plain HTML/CSS/JS in `app/static/` (index.html, styles.css, api.js, app.js), served by the same
  FastAPI process at `/` and `/static`. No build step, npm, CDN or external fonts; relative URLs only.
- Auth is the existing httponly session cookie, not a token: JS can't read it, so XSS can't steal
  it. `api.js` sends `credentials: "same-origin"` and treats any 401 (except a wrong password) as
  logged out. Every state-changing endpoint is POST/PATCH, so `SameSite=Lax` blocks cross-site
  CSRF; the GETs that run `ensure_settled` are idempotent and take no attacker input.
- `api.js` is a Facade over fetch (the only file with URLs and status codes), grouped by domain;
  `app.js` holds state and rendering, with a view map and a tab map instead of if/else chains.
  User content is only ever set through `textContent` (no `innerHTML`).
- Usernames come from a new read-only `GET /groups/{id}/members` in auth (reusing `list_members`
  behind the 404/403 check). The UI maps the feed's `user_id`s to these names, the composition a
  gateway would do after a service split; getting names from the leaderboard was rejected because
  it would make the Goals & Check-ins UI depend on Points.
- Display-only rules in the UI: no vote button on your own check-ins, no proof upload on others'
  assignments, and a vote cast this session is remembered from the vote response. The server
  still enforces all of them.
- Known limitation (G2): the feed doesn't expose vote state (whether you voted, the current count,
  votes needed), so a vote's count is shown only after you cast it; a repeat vote shows the
  server's 409 message.
- Known limitation (G3): the voting window isn't exposed, and re-implementing `created_at + 48h` in
  JS would duplicate a business rule, so the vote button stays and a late vote shows the server's
  409 "voting has closed".

**UI redesign and social features** (branch `feat/ui-redesign`, after Phase 6)
- The UI follows my "lockin." design references (cream, thick black outlines, hard shadows,
  purple/lime/coral/yellow, bottom nav with a camera button on phones). Only real data is shown:
  notifications lists, chat and daily percentages from the references are left out, not faked.
- Comments on proof: any member can comment on any check-in in their group, including their own
  (to reply). Trimmed, 1-280 chars (`COMMENT_MAX_LENGTH`), oldest first, no editing or deleting.
  The feed carries `comment_count`; comments load on demand.
- Forfeit rule changed: only last week's #1 (ties: everyone at #1) can set the forfeit. The Phase
  5 lock rule is unchanged, so a forfeit set during this week applies from next Monday.
- Nudges, kept as simple as possible inside Goals & Check-ins (the rule needs goals and check-ins,
  so no third domain): someone can be nudged when they haven't hit every goal's weekly target
  (no goals counts as not done) and haven't posted proof today (UTC day). The server enforces it.
  The nudger writes the message (max 140 chars, `NUDGE_MAX_LENGTH`); blank sends "don't be a
  loser, get to work and get it done." One nudge per person per nudger per day (UNIQUE), never
  yourself (CHECK). The recipient sees today's nudges as a banner on Home and a dot on the avatar;
  there's no read/unread state, they expire with the day.
- The week definition (`monday_of`, `week_start_for`, `week_begins_at`) moved to
  `app/shared/timeutils.py` so both domains use the same Monday 00:00 UTC.
- Direct messages (DMs) were requested but deliberately not built: with the deadline a day away,
  a chat (conversations, threads, unread state, no live updates without WebSockets) would have
  taken time from testing, docs and the report. Future work.

**Phase 7: Hardening & docs**
- Coverage is measured on core logic: `.coveragerc` omits the `routes.py` files (thin HTTP glue,
  checked end to end instead). Chosen over TestClient route tests, which would need `httpx` as a
  new dependency. Result: 303 tests, 99% of core logic. Recorded as ADR-4.
- Auth service tests added (40% to 99%): registration rules, login, sessions, groups.
- Auth routes return 422, not 400, for invalid registration and group input.
- Security pass: passwords are PBKDF2-SHA256 with a per-password salt and a constant-time
  compare; the session cookie is HttpOnly and SameSite=Lax, and now Secure when
  `COOKIE_SECURE=true` (off by default because local runs are plain http). An outsider and a
  logged-out user were checked against all 18 group-scoped endpoints: every one returns 403 or
  401. Uploads keep their content/size/pixel/path-traversal checks. Accepted gaps: no rate
  limiting on login, and 8-character invite codes (32 bits), fine for friend groups.
- File count is 53 against the ~50 guideline: the extra files are tests, the README and the
  small `.coveragerc`. A `pyproject.toml` could have held the coverage config, but the deployment
  script might mistake it for a second dependency manifest.
- Verified from a fresh clone: starts in under a second with no `.env` and the default
  `DATA_DIR`, creates the schema itself, and the README's coverage command gives the same result.

**Demo data** (after Phase 7)
- A separate command, `python seed_demo.py`, fills an empty `DATA_DIR` with a demo crew so a grader
  sees every feature (log in as maya / lockin-demo). Chosen over seeding on startup with an env
  var, so the app itself never seeds and the Azure deployment can't pick up fake data by accident.
- It uses the real service functions, so every rule holds, and only moves timestamps back to
  create past weeks. It refuses to run if the database already has users.

---

## A2 phases
Following the professor's whiteboard roadmap (Context section). Each phase runs the full How we
work protocol.
1. **Split** (step 1): two services in `services/checkins/` and `services/points/`, auth moved into
   Checkins, the seam as HTTP calls with timeouts and the designed failure behaviour, static UI in
   `ui/`.
2. **Data** (step 1, a database per service): SQLite to SQL Server, versioned migrations per
   service, `/health`, request logs.
3. **Containers** (steps 2-3): one Dockerfile per service, `docker-compose.yml` with SQL Server,
   `db/init.sql` and nginx for the UI.
4. **CI** (step 4): lint, tests, coverage ≥70% per service, `system.yaml` and OpenAPI validation,
   image builds.
5. **Azure + CD** (step 4): initial Azure setup, images to GHCR, deploy to Container Apps, UI to
   the storage static website, post-deploy health check.
6. **Evidence:** a migration on Azure against existing data, docs and diagrams, report evidence,
   the `submission` tag.

## A2 schedule
Deadline **Sunday 2026-11-29 23:59** (moved from 11-22). Target: tag `submission` by **Friday
2026-11-27 23:59** (moved from 11-25 after Mon 23 slipped, then from 11-26 after Tue 24 slipped). Every day needs at least one pushed
commit (push timestamps count).

| Day | Phases | Roughly what |
|---|---|---|
| Thu 19 | 1. Split | Done. Two services talking over HTTP, UI in `ui/`, partial-failure behaviour, tests per service. ADR-6. |
| Fri 20 | 2. Data, 3. Containers | Done. SQL Server per service, migrations, retries, `/health`, request logs; Dockerfiles, compose, db-init, nginx. ADR-7. |
| Sat 21 | (none) | No commits: the deadline moved. |
| Sun 22 | 4. CI | Done. GitHub Actions CI (lint, tests, coverage ≥70%, validation, image builds), OpenAPI files. ADR-9. |
| Mon 23 | (none) | Slipped: no commits. |
| Tue 24 | (none) | Slipped: only the Phase 5 decisions commit. |
| Wed 25 | 5. Azure + CD | Azure initial setup from `docs/azure_deployment_guide.md`, images to GHCR, CD to Container Apps + the storage static website, post-deploy health check, with only migration 001 deployed. ADR-8. |
| Thu 26 | 6. Evidence | Data on Azure, then migration 002 deployed and the data shown to survive; partial-failure and pipeline evidence (a failed run that was fixed). ADR-10. |
| Fri 27 | Docs and submission | README, diagrams, report, AI_USAGE.md complete, final checks; tag `submission` on `main` before 23:59. |
| Sat 28 - Sun 29 | Buffer | Only if something slips. |

- Commit rule check: 2026-11-20 holds 18 commits, so A2 needs at least 45 commits in total for no
  day to exceed 40%; spreading Phases 5-6 and the docs over 25-27 gives 9 distinct days (17, 18, 19, 20, 22, 24, 25, 26, 27).
- The detail of each phase comes from me at the start of that phase. This table is only the outline.
- If a phase runs late, tell me as soon as you see it and ask me what to cut. Never cut on your
  own, and never cut the commit days, the migration evidence, partial-failure handling, the
  coverage gate, ADR 6-10 or the AI log.
- At the end of each phase, remind me what is next on the schedule and whether we are on time.

---

## A1 phases (done)
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
3. **Rejection votes** (done, PR #6): voting endpoint, the rejection rule as a pure function, an
   atomic vote + status change, and `revoke_completion` called exactly once per rejection.
   *Done when:* the rule is unit-tested at the threshold boundary; duplicate votes, author votes,
   non-member votes, closed-window votes, and votes on rejected check-ins are all rejected
   correctly; tests prove `revoke_completion` fires once.
4. **Weekly scoring & leaderboard** (done, PR #7): real
   `record_completion` / `revoke_completion`, weekly totals, and ranking computed in SQL, plus
   the streak bonus. ADR-3 was revised to cover the points ledger and the database diagram.
   *Done when:* scoring is unit-tested across week boundaries and revocations; the leaderboard
   endpoint returns a correct ranking.
5. **Forfeits** (done, PR #8): forfeit set in advance per group, lazy settlement, and the loser
   uploads proof.
   *Done when:* settlement is tested for ties, empty weeks, and concurrent first requests (the
   UNIQUE constraint holds); proof upload reuses `app/shared/uploads.py`.
6. **Frontend** (done, PR #10; restyled with social features on `feat/ui-redesign`): simple HTML/JS pages for everything
   above. If time is short, cut to the minimum usable pages rather than eat into Phase 7.
7. **Hardening & docs** (done, PR #13): coverage to ≥70% on service logic, README (setup + coverage command),
   and a security pass (password hashing, session cookie flags, upload size/type/path-traversal
   checks, group membership checked on every group-scoped endpoint). Also generate the
   architecture diagram and database schema diagram from the **actual** code, so they match
   the repo.

**Stretch features are cut** unless I explicitly bring them back (image-hash duplicates, EXIF
stripping, per-group timezones).

---

## Testing
- pytest + pytest-cov. Tests live per service, in `services/<name>/tests/`.
- They follow the **testing pyramid**:
  - **Unit tests are the majority:** pure rule functions first, then services.
  - **Integration tests** cover how components work together: service + repository against a
    SQL Server container, and **at least one test across the seam** (spec §5).
  - **One end-to-end smoke test** on the compose stack.
- Tests never connect to Azure SQL (spec §5) and never touch real data.
- Test behavior and edge cases, not framework glue or routing.
- Coverage is ≥70% **per service** on core logic, measured in each service folder; the commands
  go in the README.
- At the end of each phase, report coverage per service.

---

## Process deliverables
- **ADR.md:** entries 1-5 stay unchanged. If A2 changes one, set it to `Status: Superseded by
  [N]`. A2 adds exactly ADR-6 to ADR-10 in the same format (6 the split, 7 data and migrations,
  8 serverless hosting on Azure, 9 pipeline and testing, 10 one thing deliberately not built).
  When work produces an ADR-worthy decision, draft the entry from **my answers** to your questions
  and tell me which number it is. I edit and commit it. The new entries must span at least 3
  distinct commit dates.
- **AI_USAGE.md:** you update it yourself at the end of every phase, like my A1 rows: one row for
  the plan + questions, and one row for my answers + the build (more if there were several
  rounds). Fill Date/commit, Tool, Prompt (my actual prompts and answers, faithfully summarised),
  Disposition, and What changed & why (including every place you deviated from the approved
  plan). **Leave "In my own words, how this works" empty: that column is mine.** Infrastructure
  files (Dockerfiles, compose, workflows, SQL, scripts) are logged like code. Commit the AI log
  update as its own docs commit.
- **Report:** the SDLC section draws on the phase reports, so keep them honest about deviations.

---

## End of every phase: stop and give me
1. **Walkthrough:** each new or changed file and key function in plain language, with the data
   flow (request -> route -> service -> repository -> the database (or the other service))
2. **Why:** the design reasoning (naming any SOLID principle, smell, or pattern involved) and one
   alternative we didn't choose, with the reason
3. **3 closed-book questions** like the comprehension check would ask, using real function names
4. **Notes reminder**, and whether this phase needs an ADR entry (and which one)
5. **AI_USAGE.md rows written**, with "In my own words" left empty
6. **Coverage** per service
7. **Commit count and distinct push days so far** (since the A1 submission)
8. **Git:** a conventional commit message (or several, if the work splits naturally) and the
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