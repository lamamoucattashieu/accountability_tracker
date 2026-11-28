# lockin.

[![CI](https://github.com/lamamoucattashieu/accountability_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/lamamoucattashieu/accountability_tracker/actions/workflows/ci.yml)

**No ghosting your goals.** A habit tracker for friend groups: everyone sets weekly goals, posts
photo proof, and the crew keeps each other honest. Friends can call cap on a suspicious check-in,
reply to it, or nudge someone who's slacking. Points add up on a weekly leaderboard, and the week's
lowest scorer does the forfeit that last week's winner picked.

Software Development & DevOps (IE Madrid). Assignment 1 built it as a single-process monolith;
Assignment 2 splits it into two services, one per domain, talking over HTTP, each with its own
database, with a static UI that calls both.

**Live:** https://lhvmoucattasieu2024ui.z49.web.core.windows.net (the first request after an idle
hour can take about a minute, because the containers and the databases start from zero; the UI
shows "Starting up…" and retries).

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

| Service | Migrations |
|---|---|
| checkins | `001_init` (every table), `002_limit_group_names` (group names over 60 characters shortened, then `groups.name` becomes `NVARCHAR(60)` with a 1-60 CHECK: a change to a table that already holds data, evidenced on Azure in [docs/migration_evidence.md](docs/migration_evidence.md)) |
| points | `001_init` (every table) |

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
Each `.coveragerc` sets `fail_under = 70`, so a run below 70% fails, locally and in CI.

### Lint and OpenAPI

```bash
cd services/checkins && ruff check --select E4,E7,E9,F .   # real errors only, not style (same in points)
```

Each service's OpenAPI document (`services/<name>/openapi.json`) is generated from the code and
committed. After changing an endpoint, regenerate it from the service's folder:

```bash
python -c "import json, pathlib, main; pathlib.Path('openapi.json').write_text(json.dumps(main.app.openapi(), indent=2) + '
', encoding='utf-8', newline='
')"
```

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to a branch other than
`main`, on every pull request, and as the first job of CD on `main` (so it never runs twice for one
commit). It never connects to Azure.

- **One job per service** (`checkins`, `points`, in parallel): install `requirements-dev.txt`, lint
  with ruff, run the tests with the 70% coverage gate against a SQL Server service container (the
  same image as compose), regenerate `openapi.json` and fail if it differs from the committed file,
  and build the Docker image (not pushed).
- **One validation job:** `system.yaml` against `system.schema.json`, both OpenAPI documents against
  the OpenAPI specification, every cross-service call listed in `system.yaml` present in the called
  service's document, and the code copied into both services (`app/shared/`, `app/auth/tokens.py`,
  the 48h voting window) still identical.

The SQL Server password is the repository secret `CI_MSSQL_SA_PASSWORD` (letters and digits, 16+
characters, like the `.env` passwords). `main` only accepts changes through pull requests whose
CI has passed (branch protection). The end-to-end smoke test is not part of CI; run it locally on
the compose stack (see above).

## Deployment (CD)

[`.github/workflows/cd.yml`](.github/workflows/cd.yml) runs on every push to `main` (that is,
every merged pull request), one run at a time:

1. **ci**: the whole of `ci.yml`. Nothing below runs unless it passes.
2. **images**: each service's image is built with `--provenance=false` and pushed to GHCR as
   `ghcr.io/lamamoucattashieu/lockin-checkins:<commit sha>` and `lockin-points:<commit sha>`,
   signed in with the run's own `GITHUB_TOKEN`.
3. **deploy**: signs in to Azure as the managed identity `lhvmoucattas-ieu2024-github` over OIDC
   (no Azure password exists anywhere), then:
   - sets each Container App's secrets (its `DATABASE_URL`, built from the GitHub secret holding its
     database password, `AUTH_TOKEN_SECRET`, `INTERNAL_API_KEY`) and points it at the new image,
     with the secrets passed as `secretref:` and the other service's URL and the UI's origin
     (`CORS_ORIGINS`) as plain variables;
   - writes `ui/config.js` with both services' HTTPS addresses and uploads `ui/` to the `$web`
     container of `lhvmoucattasieu2024ui` (`--auth-mode login`, no storage key);
   - calls `/health` on both services every 10 s and fails the run unless both return 200 within
     5 minutes (a cold start plus a paused database resuming takes about a minute).

Each service runs its migrations on startup; Container Apps has at most one replica, so they never
run twice at once. To rotate a secret: change the GitHub secret, then re-run the last CD run's
`deploy` job (each run creates a new revision, which reads the current secrets).

| GitHub secret | What it is |
|---|---|
| `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | Which identity, directory and subscription to sign in to (IDs, not passwords) |
| `CHECKINS_DB_PASSWORD`, `POINTS_DB_PASSWORD` | The passwords of the Azure database users `checkins_app` and `points_app` |
| `AUTH_TOKEN_SECRET`, `INTERNAL_API_KEY` | The services' two shared secrets (different from the local `.env` ones) |
| `CI_MSSQL_SA_PASSWORD` | Only for CI's throwaway SQL Server container |

Repository variables (not secret): `PREFIX` = `lhvmoucattas-ieu2024`, `RESOURCE_GROUP` =
`rg-lhvmoucattas-ieu2024`, `UI_STORAGE` = `lhvmoucattasieu2024ui`.

To read a service's logs: `az containerapp logs show --name lhvmoucattas-ieu2024-checkins
--resource-group rg-lhvmoucattas-ieu2024 --follow` (add `--type system` for start-up and probe
events). There is no Log Analytics workspace (it would be an extra resource).

## Azure initial setup

Done once, by hand, with the Azure CLI (Bash) on 2026-11-25. After it, only the CD pipeline
changes anything. Passwords are shown as `$NAME`: they were generated locally (32 letters and
digits) and live only in GitHub secrets and, for the SQL admin, my password manager.

Everything is in **austriaeast**. The plan was switzerlandnorth, but it refused new SQL servers
(`RegionDoesNotAllowProvisioning`), and of the five regions this subscription allows, only
austriaeast accepts SQL servers. There, Azure SQL's free offer is refused for the spec's size
(`ProvisioningDisabled` for `GP_S_Gen5_1`, max 1 vCore). The portal only offers it for a new
database at 2 vCores. On 2026-11-28, switching the existing databases to it in place was
refused at both 1 and 2 vCores, so the databases are serverless without the free offer (ADR-8),
and the professor was told by email.

```bash
# 1. Subscription and region (the "Allowed resource deployment regions" policy)
az account set --subscription "Azure for Students"
az policy assignment list --query "[?contains(displayName,'region')].parameters"
#    -> austriaeast, polandcentral, switzerlandnorth, uaenorth, spaincentral

# 2. Providers (already registered) and the resource group
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register --namespace $ns
done
az group create --name rg-lhvmoucattas-ieu2024 --location austriaeast

# 3. The UI: a storage account with a static website
az storage account create --name lhvmoucattasieu2024ui --resource-group rg-lhvmoucattas-ieu2024 \
  --location austriaeast --kind StorageV2 --sku Standard_LRS --min-tls-version TLS1_2
az storage blob service-properties update --account-name lhvmoucattasieu2024ui \
  --static-website --index-document index.html --auth-mode key
#    -> https://lhvmoucattasieu2024ui.z49.web.core.windows.net/

# 4. SQL server, firewall, two serverless databases
az sql server create --name lhvmoucattas-ieu2024-sql --resource-group rg-lhvmoucattas-ieu2024 \
  --location austriaeast --admin-user lockinadmin --admin-password "$SQL_ADMIN_PASSWORD" --minimal-tls-version 1.2
az sql server firewall-rule create --server lhvmoucattas-ieu2024-sql --resource-group rg-lhvmoucattas-ieu2024 \
  --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
for svc in checkins points; do
  az sql db create --name lhvmoucattas-ieu2024-$svc-db --server lhvmoucattas-ieu2024-sql \
    --resource-group rg-lhvmoucattas-ieu2024 --edition GeneralPurpose --compute-model Serverless \
    --family Gen5 --min-capacity 0.5 --capacity 1 --backup-storage-redundancy Local \
    --auto-pause-delay 60 --max-size 2GB
done
#    (--use-free-limit true was refused in austriaeast; 60 minutes is the shortest auto-pause allowed)

# 4b. One contained user per database, each only in its own database. My IP was allowed only
#     for this step; sqlcmd ran from the same SQL Server image as compose's db-init, connected
#     to each database as lockinadmin, running (for checkins_app, then points_app):
#       CREATE USER [checkins_app] WITH PASSWORD = N'$CHECKINS_DB_PASSWORD', DEFAULT_SCHEMA = dbo;
#       ALTER ROLE db_ddladmin ADD MEMBER [checkins_app];
#       ALTER ROLE db_datareader ADD MEMBER [checkins_app];
#       ALTER ROLE db_datawriter ADD MEMBER [checkins_app];
az sql server firewall-rule create --server lhvmoucattas-ieu2024-sql --resource-group rg-lhvmoucattas-ieu2024 \
  --name SetupMyIP --start-ip-address <my ip> --end-ip-address <my ip>
docker run --rm -e SQLCMDPASSWORD="$SQL_ADMIN_PASSWORD" --entrypoint /opt/mssql-tools18/bin/sqlcmd \
  mcr.microsoft.com/mssql/server:2022-CU28-ubuntu-22.04 \
  -S tcp:lhvmoucattas-ieu2024-sql.database.windows.net,1433 -d lhvmoucattas-ieu2024-checkins-db \
  -U lockinadmin -N -b -Q "<the statements above>"        # and the same for points_app on points-db
az sql server firewall-rule delete --server lhvmoucattas-ieu2024-sql --resource-group rg-lhvmoucattas-ieu2024 --name SetupMyIP
#    Checked: each user logs in to its own database and gets "Login failed" on the other one.

# 5. Container Apps environment (workload profiles, no Log Analytics) and the two apps on its
#    Consumption profile, on a placeholder image. --environment-mode is explicit because the CLI
#    now defaults to an Express (preview) environment, which rejected --revision-suffix in the
#    first CD run (45684969529); that environment was deleted and recreated like this.
az containerapp env create --name lhvmoucattas-ieu2024-env --resource-group rg-lhvmoucattas-ieu2024 \
  --location austriaeast --logs-destination none --environment-mode WorkloadProfiles
az containerapp create --name lhvmoucattas-ieu2024-checkins --environment lhvmoucattas-ieu2024-env \
  --resource-group rg-lhvmoucattas-ieu2024 --workload-profile-name Consumption \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --ingress external --target-port 8000 --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi
az containerapp create --name lhvmoucattas-ieu2024-points --environment lhvmoucattas-ieu2024-env \
  --resource-group rg-lhvmoucattas-ieu2024 --workload-profile-name Consumption \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --ingress external --target-port 8001 --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi
#    -> https://lhvmoucattas-ieu2024-checkins.agreeablesand-808a27ad.austriaeast.azurecontainerapps.io
#    -> https://lhvmoucattas-ieu2024-points.agreeablesand-808a27ad.austriaeast.azurecontainerapps.io

# 6. The pipeline's identity: Contributor on the resource group, blob uploads on the storage
#    account, trusted only for runs on main of this repository (both subject formats)
az identity create --name lhvmoucattas-ieu2024-github --resource-group rg-lhvmoucattas-ieu2024 --location austriaeast
principal=$(az identity show -n lhvmoucattas-ieu2024-github -g rg-lhvmoucattas-ieu2024 --query principalId -o tsv)
az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal \
  --role Contributor --scope $(az group show -n rg-lhvmoucattas-ieu2024 --query id -o tsv)
az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope $(az storage account show -n lhvmoucattasieu2024ui -g rg-lhvmoucattas-ieu2024 --query id -o tsv)
az identity federated-credential create --name github-main --identity-name lhvmoucattas-ieu2024-github \
  --resource-group rg-lhvmoucattas-ieu2024 --issuer https://token.actions.githubusercontent.com \
  --audiences api://AzureADTokenExchange \
  --subject "repo:lamamoucattashieu/accountability_tracker:ref:refs/heads/main"
az identity federated-credential create --name github-main-ids --identity-name lhvmoucattas-ieu2024-github \
  --resource-group rg-lhvmoucattas-ieu2024 --issuer https://token.actions.githubusercontent.com \
  --audiences api://AzureADTokenExchange \
  --subject "repo:lamamoucattashieu@232588908/accountability_tracker@1393083742:ref:refs/heads/main"

# 7. GitHub secrets and variables (each value piped in from the terminal, never written to a file in the repo)
gh secret set AZURE_CLIENT_ID          # the identity's clientId
gh secret set AZURE_TENANT_ID
gh secret set AZURE_SUBSCRIPTION_ID
gh secret set CHECKINS_DB_PASSWORD
gh secret set POINTS_DB_PASSWORD
gh secret set AUTH_TOKEN_SECRET
gh secret set INTERNAL_API_KEY
gh variable set PREFIX --body lhvmoucattas-ieu2024
gh variable set RESOURCE_GROUP --body rg-lhvmoucattas-ieu2024
gh variable set UI_STORAGE --body lhvmoucattasieu2024ui

# 8. After the first CD run pushed the images: both GHCR packages made public in their GitHub
#    package settings (the code is public already), so Container Apps can pull them.

# 9. Read access for grading
for who in amartini@faculty.ie.edu bserra@faculty.ie.edu; do
  az role assignment create --assignee $who --role Reader \
    --scope $(az group show -n rg-lhvmoucattas-ieu2024 --query id -o tsv)
done
```

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

- [ADR.md](ADR.md): the architecture decision records, 1-5 from Assignment 1 (2, 3 and 4 now
  superseded) and 6-10 from Assignment 2 (the split, data and migrations, serverless hosting on
  Azure, pipeline and testing, and the message broker not built)
- [docs/architecture.md](docs/architecture.md): the A1 and A2 architecture, the deployment, and one
  database diagram per service
- [docs/migration_evidence.md](docs/migration_evidence.md): migration 002 applied on Azure over
  existing data, with the queries before and after
- [system.yaml](system.yaml) and `services/<service>/openapi.json`: the machine-readable
  description of the system, checked by CI
- [AI_USAGE.md](AI_USAGE.md): the log of how AI was used, phase by phase
- [CLAUDE.md](CLAUDE.md): the working agreement and decision log used throughout the project
