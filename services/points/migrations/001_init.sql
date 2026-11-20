-- 001_init: the Points & Forfeits schema.
-- Never edit this file once it has been applied: add 002_..., 003_... instead.
--
-- Timestamps are ISO 8601 UTC strings ("2026-11-20T10:00:00+00:00") and week
-- starts are dates ("2026-11-16"), as in A1: one format, so text order is time order.
-- Ids of the other service (check-in, group, user, goal) are plain columns with
-- no foreign key: that data lives in another database (ADR-3, ADR-6).
-- Length limits written here must match app/config.py; a test compares them.

-- The points ledger: one row per check-in, revoked_at set when it is rejected.
CREATE TABLE dbo.point_events (
    id INT IDENTITY(1, 1) CONSTRAINT PK_point_events PRIMARY KEY,
    -- Recording the same check-in twice is impossible: the idempotent receiver relies on it.
    checkin_id INT NOT NULL CONSTRAINT UQ_point_events_checkin UNIQUE,
    group_id INT NOT NULL,
    user_id INT NOT NULL,
    goal_id INT NOT NULL,
    times_per_week INT NOT NULL CONSTRAINT CK_point_events_times_per_week CHECK (times_per_week BETWEEN 1 AND 7),
    -- 1900-01-01 was a Monday, so this is a Monday check that doesn't depend on DATEFIRST.
    week_start NVARCHAR(10) NOT NULL
        CONSTRAINT CK_point_events_monday CHECK (DATEDIFF(day, '19000101', CAST(week_start AS date)) % 7 = 0),
    completed_at NVARCHAR(32) NOT NULL,
    revoked_at NVARCHAR(32) NULL
);
CREATE INDEX IX_point_events_group_week ON dbo.point_events (group_id, week_start);

-- Append-only: a forfeit is never updated or deleted, so past weeks keep theirs.
CREATE TABLE dbo.forfeits (
    id INT IDENTITY(1, 1) CONSTRAINT PK_forfeits PRIMARY KEY,
    group_id INT NOT NULL,
    text NVARCHAR(200) NOT NULL CONSTRAINT CK_forfeits_length CHECK (LEN(text) BETWEEN 1 AND 200),
    set_by INT NOT NULL,
    created_at NVARCHAR(32) NOT NULL
);
CREATE INDEX IX_forfeits_group ON dbo.forfeits (group_id);

-- One row per group and week: UNIQUE makes settling a week twice impossible.
CREATE TABLE dbo.settlements (
    id INT IDENTITY(1, 1) CONSTRAINT PK_settlements PRIMARY KEY,
    group_id INT NOT NULL,
    week_start NVARCHAR(10) NOT NULL
        CONSTRAINT CK_settlements_monday CHECK (DATEDIFF(day, '19000101', CAST(week_start AS date)) % 7 = 0),
    forfeit_id INT NULL CONSTRAINT FK_settlements_forfeit REFERENCES dbo.forfeits (id),
    settled_at NVARCHAR(32) NOT NULL,
    CONSTRAINT UQ_settlements_group_week UNIQUE (group_id, week_start)
);

-- One row per loser of a settled week; the score is frozen at settlement. The
-- proof photo is stored in the row (it used to be a file), with its type and time.
CREATE TABLE dbo.forfeit_assignments (
    id INT IDENTITY(1, 1) CONSTRAINT PK_forfeit_assignments PRIMARY KEY,
    settlement_id INT NOT NULL CONSTRAINT FK_forfeit_assignments_settlement REFERENCES dbo.settlements (id),
    user_id INT NOT NULL,
    score INT NOT NULL,
    proof_photo VARBINARY(MAX) NULL,
    proof_type NVARCHAR(20) NULL CONSTRAINT CK_forfeit_assignments_proof_type CHECK (proof_type IN (N'image/jpeg', N'image/png')),
    proof_at NVARCHAR(32) NULL,
    CONSTRAINT UQ_forfeit_assignments_once UNIQUE (settlement_id, user_id),
    -- The photo, its type and its time exist together or not at all.
    CONSTRAINT CK_forfeit_assignments_proof_complete CHECK (
        (proof_photo IS NULL AND proof_type IS NULL AND proof_at IS NULL)
        OR (proof_photo IS NOT NULL AND proof_type IS NOT NULL AND proof_at IS NOT NULL))
);

-- The last answer Checkins gave about a group (cache-aside). Read only when
-- Checkins can't be reached, so Points can keep serving its own domain.
CREATE TABLE dbo.group_snapshots (
    group_id INT NOT NULL CONSTRAINT PK_group_snapshots PRIMARY KEY,
    created_at NVARCHAR(32) NOT NULL,
    members NVARCHAR(MAX) NOT NULL CONSTRAINT CK_group_snapshots_members CHECK (ISJSON(members) = 1),
    pending_points_sync BIT NOT NULL,
    fetched_at NVARCHAR(32) NOT NULL
);

-- One row that /health updates, to prove the service can write its database.
CREATE TABLE dbo.service_health (
    id INT NOT NULL CONSTRAINT PK_service_health PRIMARY KEY CONSTRAINT CK_service_health_one_row CHECK (id = 1),
    checked_at NVARCHAR(32) NOT NULL
);
INSERT INTO dbo.service_health (id, checked_at) VALUES (1, N'never');
