# Architecture Decision Records

## 1. Backend language/framework: Python with FastAPI
Date: 2026-09-28
Status: Decided
Context: The app needs a small JSON API (auth, groups, photo check-ins, weekly points) running as a single process on SQLite, and I have to be able to explain every line of it closed-book.
Decision: Use Python with FastAPI, served by uvicorn, with raw SQL through the standard-library sqlite3 module.
Alternatives considered: Django, rejected because it is too heavy for this app: its ORM, migrations and admin panel solve problems I don't have with a handful of SQLite tables, and would add framework code I'd need to understand and justify.
Consequences: I work in the language I know best and keep the dependency list short (fastapi + uvicorn); in exchange I write my own SQL and schema setup instead of getting them from a framework.
