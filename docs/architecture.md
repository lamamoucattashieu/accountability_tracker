# Architecture diagrams

Drawn from the code at the graded commit: the A1 monolith from its last commit (`89ba165`,
2026-10-04), the split system from `services/`, the deployment from `.github/workflows/cd.yml`
and the README's Azure setup, and the database diagrams from each service's `migrations/`
(001 and 002). GitHub draws the Mermaid blocks; each one can be exported to PNG from
https://mermaid.live for the report.

## 1. Before: the Assignment 1 monolith

One process, one SQLite file. The domains are separate packages; they only meet through each
other's `service` module (ADR-2), so the seam already existed as Python calls.

```mermaid
flowchart LR
    browser["Browser"]

    subgraph proc["One FastAPI process: python main.py (one container)"]
        static["Static UI<br/>app/static/ (same origin, session cookie)"]
        auth["auth<br/>users, sessions, groups, membership"]
        checkins["checkins<br/>goals, check-ins, votes, comments, nudges"]
        points["points<br/>scoring, leaderboard, forfeits, settlement"]
    end

    db[("SQLite: DATA_DIR/app.db<br/>all 13 tables")]
    files[("DATA_DIR/uploads/<br/>photo files")]

    browser -->|"HTTP, same origin"| proc
    checkins -->|"auth.service.is_member()"| auth
    points -->|"auth.service.list_members()"| auth
    checkins -->|"points.service.record_completion() /<br/>revoke_completion(), same transaction"| points
    auth --> db
    checkins --> db
    points --> db
    checkins --> files
    points --> files
```

## 2. After: two services, each with its own database

The seam is now HTTP. Auth moved into Checkins (it checks membership on almost every request).
The browser calls both services; the services call each other only on `/internal/...`
endpoints, with the shared `X-Internal-Key` and a 2 s timeout.

```mermaid
flowchart LR
    browser["Browser"]
    ui["Static UI: ui/<br/>(Storage static website $web,<br/>config.js written by CD)"]

    subgraph c["checkins service (services/checkins, port 8000)"]
        cauth["auth: users, sessions, groups,<br/>membership, signed tokens"]
        cdomain["goals, check-ins, votes,<br/>comments, nudges"]
        outbox["points_outbox<br/>(written in the same transaction)"]
    end

    subgraph p["points service (services/points, port 8001)"]
        pdomain["scoring, leaderboard, forfeits,<br/>lazy settlement, proof"]
        snap["group_snapshots<br/>(last answer from checkins)"]
    end

    cdb[("checkins database<br/>login checkins_app")]
    pdb[("points database<br/>login points_app")]

    browser -->|"loads"| ui
    browser -->|"HTTPS, Bearer token<br/>(CORS: the UI origin only)"| c
    browser -->|"HTTPS, Bearer token<br/>(CORS: the UI origin only)"| p

    outbox -->|"POST /internal/completions<br/>POST /internal/completions/{checkin_id}/revocation<br/>timeout 2 s, idempotent, retried lazily"| pdomain
    pdomain -->|"GET /internal/groups/{group_id}<br/>timeout 2 s, falls back to the snapshot"| cauth

    c --> cdb
    p --> pdb
```

When **points** is down, a check-in or rejection is still saved, marked "points pending", and its
outbox row waits for a later check-in, vote or feed load. When **checkins** is down, points serves
reads from its last snapshot, marked possibly out of date, and answers changes with a 503.

## 3. Deployment

```mermaid
flowchart LR
    dev["Developer"] -->|"pull request"| gh

    subgraph gh["GitHub: lamamoucattashieu/accountability_tracker"]
        ci["ci.yml: every push and PR<br/>lint, tests + coverage >= 70%<br/>per service (SQL Server service<br/>container), OpenAPI and system.yaml<br/>checks, image builds"]
        cd["cd.yml: push to main<br/>ci -> images -> deploy"]
    end

    ghcr[("GHCR<br/>ghcr.io/lamamoucattashieu/<br/>lockin-checkins:sha<br/>lockin-points:sha")]

    subgraph rg["Azure: rg-lhvmoucattas-ieu2024 (austriaeast)"]
        id["Managed identity<br/>lhvmoucattas-ieu2024-github<br/>(Contributor on the group,<br/>Blob Data Contributor on storage)"]
        subgraph env["Container Apps environment lhvmoucattas-ieu2024-env<br/>(workload profiles, Consumption, 0-1 replicas)"]
            capc["Container App<br/>lhvmoucattas-ieu2024-checkins"]
            capp["Container App<br/>lhvmoucattas-ieu2024-points"]
        end
        subgraph sql["SQL server lhvmoucattas-ieu2024-sql"]
            dbc[("lhvmoucattas-ieu2024-checkins-db<br/>serverless, 0.5-1 vCore")]
            dbp[("lhvmoucattas-ieu2024-points-db<br/>serverless, 0.5-1 vCore")]
        end
        st["Storage account lhvmoucattasieu2024ui<br/>static website $web"]
    end

    user["Browser<br/>https://lhvmoucattasieu2024ui.z49.web.core.windows.net"]

    cd -->|"docker push (GITHUB_TOKEN)"| ghcr
    cd -->|"OIDC sign-in, no password"| id
    id -->|"az containerapp update<br/>(image, secrets as secretref:)"| env
    id -->|"az storage blob upload-batch<br/>(ui/ + config.js)"| st
    ghcr -->|"image pull (public package)"| env
    capc --> dbc
    capp --> dbp
    capc <-->|"HTTPS /internal/..."| capp
    user --> st
    user --> capc
    user --> capp
    cd -.->|"GET /health until 200 (5 min)"| env
```

## 4. Database: checkins (migrations 001 and 002)

Every relationship is a foreign key inside this database. Not drawn: `schema_migrations`
(written by the migration runner) and `service_health` (one row `/health` writes).

```mermaid
erDiagram
    users {
        int id PK
        nvarchar50 username UK "case-sensitive"
        nvarchar password_hash
        nvarchar created_at
    }
    sessions {
        nvarchar64 id PK
        int user_id FK
        nvarchar created_at
        nvarchar expires_at
    }
    groups {
        int id PK
        nvarchar60 name "002: NVARCHAR(MAX) to (60), CHECK 1-60"
        nvarchar8 invite_code UK
        int created_by FK
        nvarchar created_at
    }
    group_members {
        int group_id PK, FK
        int user_id PK, FK
        nvarchar joined_at
    }
    goals {
        int id PK
        int group_id FK
        int user_id FK
        nvarchar80 title
        nvarchar500 description
        int times_per_week "CHECK 1-7"
        nvarchar created_at
        nvarchar archived_at
    }
    checkins {
        int id PK
        int goal_id FK
        varbinary photo
        nvarchar photo_type
        nvarchar200 caption
        nvarchar status "accepted or rejected"
        nvarchar created_at
    }
    checkin_votes {
        int checkin_id FK "UQ with voter_id"
        int voter_id FK
        nvarchar created_at
    }
    checkin_comments {
        int id PK
        int checkin_id FK
        int author_id FK
        nvarchar280 text
        nvarchar created_at
    }
    nudges {
        int id PK
        int group_id FK
        int nudger_id FK
        int nudged_id FK "CHECK not the nudger"
        nvarchar140 message
        nvarchar day "UQ per pair and day"
        nvarchar created_at
    }
    points_outbox {
        int id PK
        nvarchar kind "record or revoke"
        int checkin_id FK
        int group_id FK
        nvarchar payload "JSON, as at write time"
        nvarchar created_at
        nvarchar sent_at
        nvarchar failed_at
        nvarchar last_error
    }

    users ||--o{ sessions : "logs in"
    users ||--o{ groups : "creates"
    groups ||--o{ group_members : "has"
    users ||--o{ group_members : "joins"
    groups ||--o{ goals : "holds"
    users ||--o{ goals : "owns"
    goals ||--o{ checkins : "proved by"
    checkins ||--o{ checkin_votes : "rejection votes"
    users ||--o{ checkin_votes : "casts"
    checkins ||--o{ checkin_comments : "has"
    users ||--o{ checkin_comments : "writes"
    groups ||--o{ nudges : "in"
    users ||--o{ nudges : "sends and receives"
    checkins ||--o{ points_outbox : "queues points change"
    groups ||--o{ points_outbox : "for"
```

## 5. Database: points (migration 001)

`group_id`, `user_id`, `goal_id`, `checkin_id` and `set_by` are ids from the checkins service:
plain columns, no foreign keys (ADR-7). The only foreign keys are inside this database.
Not drawn: `schema_migrations` and `service_health`.

```mermaid
erDiagram
    point_events {
        int id PK
        int checkin_id UK "id from checkins: idempotent receiver"
        int group_id "id from checkins"
        int user_id "id from checkins"
        int goal_id "id from checkins"
        int times_per_week "CHECK 1-7, as at check-in"
        nvarchar10 week_start "CHECK a Monday"
        nvarchar completed_at
        nvarchar revoked_at "set once on rejection"
    }
    forfeits {
        int id PK
        int group_id "id from checkins"
        nvarchar200 text "CHECK 1-200"
        int set_by "id from checkins"
        nvarchar created_at
    }
    settlements {
        int id PK
        int group_id "UQ with week_start"
        nvarchar10 week_start "CHECK a Monday"
        int forfeit_id FK "NULL: no forfeit set"
        nvarchar settled_at
    }
    forfeit_assignments {
        int id PK
        int settlement_id FK "UQ with user_id"
        int user_id "id from checkins"
        int score "frozen at settlement"
        varbinary proof_photo "all three or none"
        nvarchar proof_type
        nvarchar proof_at
    }
    group_snapshots {
        int group_id PK "id from checkins"
        nvarchar created_at
        nvarchar members "JSON"
        bit pending_points_sync
        nvarchar fetched_at
    }

    forfeits |o--o{ settlements : "applied to"
    settlements ||--o{ forfeit_assignments : "losers"
```
