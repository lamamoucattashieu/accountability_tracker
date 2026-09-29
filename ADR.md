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
Status: Decided
Context: The app runs as one process now but should be splittable into services later. Goals & Check-ins and Points & Forfeits both need user/group data and photos, which would easily tangle them together through shared tables.
Decision: Each domain owns its tables and exposes a service layer; other code may call a domain's service functions but never query its tables. Check-ins asks auth only through auth.service.is_member/group_exists, will notify Points only through points.service.record_completion/revoke_completion, and photo handling lives in shared/uploads.py so neither domain imports the other for it.
Alternatives considered: Letting app/checkins/repository.py query group_members directly (simpler, one JOIN). Rejected because it couples Check-ins to auth's table layout, so a service split would mean rewriting SQL instead of replacing one function with an HTTP call. A separate SQLite file per domain was also rejected: the spec requires one SQLite file at one path, and it would lose cross-domain transactions immediately rather than at split time.
Consequences: A future split mostly changes the seam functions, plus dropping the cross-domain foreign keys (goals → users/groups) and handling what one SQLite transaction currently gives for free: a check-in and its point event being written together. Day to day, it costs cross-domain JOINs: the goals list returns user_id rather than username, and some checks need extra queries.
