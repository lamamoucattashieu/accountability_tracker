# Migration evidence on Azure (A2 spec 4.6)

Migration `services/checkins/migrations/002_limit_group_names.sql` changes a table that already
held data on Azure (`groups`), keeping every row: names over 60 characters are shortened, then
`groups.name` goes from `NVARCHAR(MAX)` to `NVARCHAR(60) NOT NULL` with a 1-60 CHECK.

## Timeline (2026-11-27, UTC)

| When | What |
|---|---|
| 2026-11-25 19:56 | First deploy: `001_init` applied on an empty `lhvmoucattas-ieu2024-checkins-db` |
| 2026-11-27, before 12:13 | Demo crew seeded through the services' own code (`seed_demo.py`, both halves) |
| 2026-11-27, by 13:17 | On the live site: a real check-in, a nudge, and a crew with a 72-character name |
| 2026-11-27 13:19 | **Before** queried (below) |
| 2026-11-27 13:21:47 | PR #26 merged; CD run [46006459555](https://github.com/lamamoucattashieu/accountability_tracker/actions/runs/46006459555) built, pushed and deployed `75927ad` (13:21:50 to 13:25:54) |
| 2026-11-27 13:25:01 | Checkins started and applied 002 (log line below) |
| 2026-11-27 13:26 | **After** queried (below) |

The queries ran as `checkins_app` (the service's own login) from a laptop through a firewall rule
that existed only for the query and was deleted straight after.

## Startup log line (`az containerapp logs show --name lhvmoucattas-ieu2024-checkins`)

```
{"TimeStamp": "2026-11-27T13:25:01.7304076+00:00", "Log": "F INFO app.shared.migrations: migration 002_limit_group_names applied"}
```

Points, deployed in the same run, logged `migrations: nothing to apply`.

## Before

```
-- BEFORE migration 002, queried 2026-11-27T13:19:33+00:00 on lhvmoucattas-ieu2024-checkins-db as checkins_app

schema_migrations:
  001_init  applied 2026-11-25T19:56:28+00:00

groups.name column:
  nvarchar(MAX), nullable: NO

groups rows:
  id 1  name 'gym gremlins'  length 12  created 2026-11-01T12:00:00+00:00
  id 2  name 'the extremely long name of our accountability crew that just keeps going'  length 72  created 2026-11-27T13:17:36+00:00

row counts:
  users             4
  groups            2
  group_members     5
  goals             5
  checkins          22
  checkin_votes     2
  checkin_comments  6
  nudges            1
  points_outbox     23
```

## After

```
-- AFTER migration 002, queried 2026-11-27T13:26:46+00:00 on lhvmoucattas-ieu2024-checkins-db as checkins_app

schema_migrations:
  001_init  applied 2026-11-25T19:56:28+00:00
  002_limit_group_names  applied 2026-11-27T13:25:01+00:00

groups.name column:
  nvarchar(60), nullable: NO

groups rows:
  id 1  name 'gym gremlins'  length 12  created 2026-11-01T12:00:00+00:00
  id 2  name 'the extremely long name of our accountability crew that just'  length 60  created 2026-11-27T13:17:36+00:00

row counts:
  users             4
  groups            2
  group_members     5
  goals             5
  checkins          22
  checkin_votes     2
  checkin_comments  6
  nudges            1
  points_outbox     23
```

## What this shows

- Every table has the same number of rows after the migration as before: nothing was dropped or
  recreated.
- `gym gremlins` (12 characters) is unchanged; the 72-character name keeps its first 60
  characters (trailing space removed), and the crew keeps its id, members and invite code.
- `schema_migrations` records `002_limit_group_names` once, at the same second as the log line,
  so a restart applies nothing.
- Screenshots of the live crew list before and after are in the report.
