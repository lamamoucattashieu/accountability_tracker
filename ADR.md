# Architecture Decision Records

## 1. Backend language/framework: Python with FastAPI
Date: 2026-09-28
Status: Decided
Context: The app needs a small JSON API (auth, groups, photo check-ins, weekly points) running as a single process on SQLite, and I have to be able to explain every line of it closed-book.
Decision: Use Python with FastAPI, served by uvicorn, with raw SQL through the standard-library sqlite3 module.
Alternatives considered: Django, rejected because it is too heavy for this app: its ORM, migrations and admin panel solve problems I don't have with a handful of SQLite tables, and would add framework code I'd need to understand and justify. Flask, rejected because it has no built-in request validation or automatic API docs, so I'd need extra libraries for what FastAPI gives me through Pydantic models and /docs.
Consequences: I work in the language I know best and keep the dependency list short (fastapi + uvicorn); in exchange I write my own SQL and schema setup instead of getting them from a framework.

## 2. Scoping the two feature domains to be independently modularizable
Date: 2026-09-29
Status: Superseded by 6
Context: The app runs as one process now but should be splittable into services later. Goals & Check-ins and Points & Forfeits both need user/group data and photos, which would easily tangle them together through shared tables.
Decision: Each domain owns its tables and exposes a service layer; other code may call a domain's service functions but never query its tables. Both domains ask auth only through auth.service functions (e.g. is_member, list_members), check-ins notifies Points only through points.service.record_completion/revoke_completion, and photo handling lives in shared/uploads.py so neither domain imports the other for it.
Alternatives considered: Letting app/checkins/repository.py query group_members directly (simpler, one JOIN). Rejected because it couples Check-ins to auth's table layout, so a service split would mean rewriting SQL instead of replacing one function with an HTTP call. A separate SQLite file per domain was also rejected: the spec requires one SQLite file at one path, and it would lose cross-domain transactions immediately rather than at split time.
Consequences: A future split mostly changes the seam functions, plus dropping the cross-domain foreign keys (goals → users/groups) and handling what one SQLite transaction currently gives for free: a check-in and its point event being written together. Day to day, it costs cross-domain JOINs: the goals list returns user_id rather than username, and some checks need extra queries.

## 3. Data model: soft-archived goals, and a points ledger linked to check-ins by id only
Date: 2026-10-01
Status: Superseded by 7
Context: Check-ins and their points must keep pointing at the goal and check-in they came from even after a goal is archived or a check-in is rejected, and there is no migration tool, so columns later phases need must exist from the start. Points also needs per-check-in data without reading the check-ins tables (ADR-2).
Decision: Goals are soft-archived (archived_at), and a check-in stores only goal_id, a photo path relative to DATA_DIR and a status column for voting, with its group and owner derived by a same-domain JOIN. Points keeps a ledger, point_events, with one row per check-in (UNIQUE checkin_id, revoked_at on rejection) that holds other domains' ids without foreign keys, and weekly scores and streak bonuses are computed from it in SQL rather than stored; only a settled week is stored (settlements, forfeit_assignments), because it must not change once final.
Alternatives considered: Hard-deleting goals with ON DELETE CASCADE, rejected because it would erase check-ins and their points. Storing weekly totals per member, rejected because incrementing is not idempotent and a rejection could not free a capped slot, rescore a past week or end a streak without recounting. Foreign keys from point_events to check-ins, rejected because they tie Points to the check-ins schema and would have to be dropped in a split.
Consequences: History survives archiving and rejection, scoring a check-in twice is impossible at the database level, and rankings and streaks always match the events. In exchange, every leaderboard read recomputes two weeks with window functions, and the database cannot stop point_events from holding an id that does not exist in another domain.

Diagram for ADR-3 (solid lines are foreign keys; the dotted line is the domain seam, an id with no foreign key, written only through points.service.record_completion):

```mermaid
erDiagram
    users ||--o{ sessions : has
    users ||--o{ group_members : joins
    groups ||--o{ group_members : has
    users ||--o{ groups : creates
    groups ||--o{ goals : contains
    users ||--o{ goals : owns
    goals ||--o{ checkins : "proved by"
    checkins ||--o{ checkin_votes : receives
    users ||--o{ checkin_votes : casts
    checkins ||--o{ checkin_comments : "replied to by"
    users ||--o{ checkin_comments : writes
    groups ||--o{ nudges : "happen in"
    users ||--o{ nudges : "send and receive"
    checkins ||..o| point_events : "checkin_id (no FK)"
    forfeits ||--o{ settlements : "locked for"
    settlements ||--o{ forfeit_assignments : assigns

    users {
        int id PK
        text username UK
        text password_hash
        text created_at
    }
    sessions {
        text id PK
        int user_id FK
        text created_at
        text expires_at
    }
    groups {
        int id PK
        text name
        text invite_code UK
        int created_by FK
        text created_at
    }
    group_members {
        int group_id PK, FK
        int user_id PK, FK
        text joined_at
    }
    goals {
        int id PK
        int group_id FK
        int user_id FK
        text title
        text description
        int times_per_week "CHECK 1-7"
        text created_at
        text archived_at "NULL = active"
    }
    checkins {
        int id PK
        int goal_id FK
        text photo_path "relative to DATA_DIR"
        text caption
        text status "CHECK accepted or rejected"
        text created_at
    }
    checkin_votes {
        int checkin_id FK "UNIQUE with voter_id"
        int voter_id FK
        text created_at
    }
    checkin_comments {
        int id PK
        int checkin_id FK
        int author_id FK
        text text "CHECK 1-280 chars"
        text created_at
    }
    nudges {
        int id PK
        int group_id FK "UNIQUE with nudger, nudged, day"
        int nudger_id FK "CHECK != nudged_id"
        int nudged_id FK
        text message "CHECK 1-140 chars"
        text day "UTC date"
        text created_at
    }
    point_events {
        int id PK
        int checkin_id UK "no FK"
        int group_id "no FK"
        int user_id "no FK"
        int goal_id "no FK"
        int times_per_week "CHECK 1-7"
        text week_start "CHECK is a Monday"
        text completed_at
        text revoked_at "NULL = counts"
    }
    forfeits {
        int id PK
        int group_id "no FK"
        text text "CHECK 1-200 chars"
        int set_by "no FK"
        text created_at
    }
    settlements {
        int id PK
        int group_id "no FK, UNIQUE with week_start"
        text week_start "CHECK is a Monday"
        int forfeit_id FK "NULL = no forfeit set"
        text settled_at
    }
    forfeit_assignments {
        int id PK
        int settlement_id FK "UNIQUE with user_id"
        int user_id "no FK"
        int score "frozen at settlement"
        text proof_path "relative to DATA_DIR"
        text proof_at
    }
```

## 4. Testing approach: pure rules and services against a real temporary SQLite, routes checked end to end
Date: 2026-10-03
Status: Superseded by 9
Context: The assignment asks for at least 70% coverage of core business logic, and the riskiest code is where rules meet the database: scoring a check-in only once, rejecting and settling exactly once under concurrent requests, and week boundaries. Mocking the database would fake exactly the SQL constraints those guarantees rely on.
Decision: Business rules are pure functions tested with plain values and an explicit `now`, and every service is tested against a fresh SQLite file in pytest's tmp_path (the real schema from init_db, never the real database), including a two-connection race on settlement. Coverage is measured on core logic only (services, rules, repositories, config, shared modules), with the thin routes.py files excluded in .coveragerc.
Alternatives considered: Route tests through FastAPI's TestClient, rejected because they need httpx as a new dependency and would mostly test framework glue; the routes were checked with end-to-end runs against a real server instead. Mocking the repository layer, rejected because the guarantees live in UNIQUE, CHECK and conditional UPDATE statements that a mock would only pretend to have.
Consequences: Core logic is at 99%, with tests that exercise the real constraints and a real race, so the 70% bar is met with a wide margin. In exchange the HTTP layer (request parsing, status-code mapping) has no automated tests, so a mistake there would only show up in a manual or end-to-end run.

## 5. Deliberately not built: voting on forfeit proof
Date: 2026-10-02
Status: Decided
Context: A forfeit loser uploads photo proof, and check-ins already let the group vote to reject a suspicious photo, so the same could be built for proof. Points must stay independent of the check-ins domain, and the deadline left little time.
Decision: Proof is accepted as uploaded: only the assigned member can upload it, once, and every group member can see it, but nobody can vote it down.
Alternatives considered: Reusing the check-in rejection vote for proof, rejected because Points would either depend on check-ins' voting code or duplicate it, and a second 48h window would delay when a forfeit counts as done. A point penalty for missing proof, rejected so that scoring stays independent of forfeits.
Consequences: A loser could upload an unrelated photo; the group sees it and deals with it socially, as with goal farming in Phase 2a. Proof voting can be added later as a new table and endpoint inside Points without changing existing tables.

## 6. Splitting the monolith into a checkins service and a points service
Date: 2026-11-19
Status: Decided
Context: A2 requires one service per domain, each with its own database, talking only over HTTP. The A1 seam (ADR-2) assumed shared auth and one SQLite transaction covering a check-in and its points.
Decision: The seam stayed where ADR-2 put it, and Checkins still calls Points. Auth moved into Checkins because it checks membership on nearly every request. Points changes go through a transactional outbox delivered to idempotent endpoints. Points reads membership through one call per request, cached as a snapshot, and verifies signed tokens itself.
Alternatives considered: Points validating each request with Checkins. Rejected because Points could then serve nothing while Checkins is down. Auth inside Points was rejected because most Checkins requests would then cross the seam.
Consequences: Each user-visible flow makes at most one call across the seam. Either service keeps serving its own domain when the other is down. The leaderboard is eventually consistent, and a logged-out token stays valid in Points until it expires.

## 7. Data and migrations: one SQL Server database per service, schema only in versioned migrations
Date: 2026-11-20
Status: Decided
Context: The split gives each service its own database, and A2 moves from SQLite to SQL Server (Azure SQL serverless). A1 created its schema on startup and kept photos as files, neither of which works for a database that already holds data or for containers without a disk.
Decision: Each service has its own database and DATABASE_URL, and its schema exists only in numbered SQL migrations. A small runner of our own applies each one in its own transaction, records it with a checksum, and refuses an edited one. Photos are stored in the row they belong to. Integrity across the seam is kept in code by the idempotent outbox and receiver (ADR-6). Within a service, foreign keys, CHECK and UNIQUE constraints still guard every rule.
Alternatives considered: Alembic with SQLAlchemy was rejected because it adds two packages and its generated migrations hide the SQL. Typed DATETIMEOFFSET timestamps were rejected for now because they would change every read and response, while ISO UTC strings keep A1's behaviour.
Consequences: Recovery from a bad migration is forward-only. A migration that fails rolls itself back, and the service won't start until a corrected new migration replaces it. One that succeeded but was wrong is fixed with another migration, using Azure SQL's point-in-time restore if data was lost. Every connection retries while a paused database resumes.

## 9. Pipeline and testing: one CI job per service against a throwaway SQL Server
Date: 2026-11-22
Status: Decided
Context: A2 requires every push and pull request to be linted, tested, held to 70% coverage per service and built, with the system description validated, and CI must never touch Azure SQL. The services' guarantees live in SQL Server constraints, locks and migrations, so the tests need a real SQL Server.
Decision: A GitHub Actions job per service runs ruff (error rules only), the tests against a SQL Server service container with the compose image, the 70% gate from `.coveragerc`, an OpenAPI drift check and the image build. A second job validates `system.yaml` and both OpenAPI documents, checks every cross-service call against the called service's document, and checks that the code copied into both services is identical. The cross-seam test starts both real services as processes on their own scratch databases, including with one stopped. httpx's TestClient now tests `/health`, the internal endpoints, the internal key and CORS, but `routes.py` stays outside coverage.
Alternatives considered: Running the compose stack and the smoke test in CI was rejected: the cross-seam test already runs both services for real, and compose would need a `.env` built from secrets plus several more minutes per run. A stub of the other service was rejected because it would only repeat our own assumptions about it. Pinning actions to commit SHAs instead of major tags is stricter against a compromised action, but was rejected for readability.
Consequences: A change reaches `main` only when both services pass on their own, enforced by branch protection. The browser UI, nginx and the compose wiring are tested only by the local smoke test, and real Azure behaviour (cold starts, a paused database) only by the post-deploy health check in CD. The cross-seam test relies on the two services having identical requirements, since the checkins job also starts `../points`.
