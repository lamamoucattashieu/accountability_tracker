-- 001_init: the Goals & Check-ins schema (auth lives here too since the split).
-- Never edit this file once it has been applied: add 002_..., 003_... instead.
--
-- Timestamps are ISO 8601 UTC strings ("2026-11-20T10:00:00+00:00"), as in A1:
-- they all share one format, so ordering them as text orders them in time.
-- Length limits written here must match app/config.py and the services; a test
-- compares them (a migration can't read the config).

CREATE TABLE dbo.users (
    id INT IDENTITY(1, 1) CONSTRAINT PK_users PRIMARY KEY,
    -- Case-sensitive, like A1 (SQL Server compares text ignoring case by default).
    username NVARCHAR(50) COLLATE Latin1_General_100_CS_AS NOT NULL CONSTRAINT UQ_users_username UNIQUE,
    password_hash NVARCHAR(200) NOT NULL,
    created_at NVARCHAR(32) NOT NULL
);

CREATE TABLE dbo.sessions (
    id NVARCHAR(64) COLLATE Latin1_General_100_CS_AS CONSTRAINT PK_sessions PRIMARY KEY,
    user_id INT NOT NULL CONSTRAINT FK_sessions_user REFERENCES dbo.users (id),
    created_at NVARCHAR(32) NOT NULL,
    expires_at NVARCHAR(32) NOT NULL
);

CREATE TABLE dbo.groups (
    id INT IDENTITY(1, 1) CONSTRAINT PK_groups PRIMARY KEY,
    name NVARCHAR(MAX) NOT NULL,
    invite_code NVARCHAR(8) COLLATE Latin1_General_100_CS_AS NOT NULL CONSTRAINT UQ_groups_invite_code UNIQUE,
    created_by INT NOT NULL CONSTRAINT FK_groups_created_by REFERENCES dbo.users (id),
    created_at NVARCHAR(32) NOT NULL
);

CREATE TABLE dbo.group_members (
    group_id INT NOT NULL CONSTRAINT FK_group_members_group REFERENCES dbo.groups (id),
    user_id INT NOT NULL CONSTRAINT FK_group_members_user REFERENCES dbo.users (id),
    joined_at NVARCHAR(32) NOT NULL,
    CONSTRAINT PK_group_members PRIMARY KEY (group_id, user_id)
);

CREATE TABLE dbo.goals (
    id INT IDENTITY(1, 1) CONSTRAINT PK_goals PRIMARY KEY,
    group_id INT NOT NULL CONSTRAINT FK_goals_group REFERENCES dbo.groups (id),
    user_id INT NOT NULL CONSTRAINT FK_goals_user REFERENCES dbo.users (id),
    title NVARCHAR(80) NOT NULL,
    description NVARCHAR(500) NULL,
    times_per_week INT NOT NULL CONSTRAINT CK_goals_times_per_week CHECK (times_per_week BETWEEN 1 AND 7),
    created_at NVARCHAR(32) NOT NULL,
    archived_at NVARCHAR(32) NULL
);
CREATE INDEX IX_goals_group ON dbo.goals (group_id);

-- The photo is stored in the row (it used to be a file): the row and its photo
-- commit together, so neither can exist without the other.
CREATE TABLE dbo.checkins (
    id INT IDENTITY(1, 1) CONSTRAINT PK_checkins PRIMARY KEY,
    goal_id INT NOT NULL CONSTRAINT FK_checkins_goal REFERENCES dbo.goals (id),
    photo VARBINARY(MAX) NOT NULL,
    photo_type NVARCHAR(20) NOT NULL CONSTRAINT CK_checkins_photo_type CHECK (photo_type IN (N'image/jpeg', N'image/png')),
    caption NVARCHAR(200) NULL,
    status NVARCHAR(10) NOT NULL CONSTRAINT DF_checkins_status DEFAULT N'accepted'
        CONSTRAINT CK_checkins_status CHECK (status IN (N'accepted', N'rejected')),
    created_at NVARCHAR(32) NOT NULL
);
CREATE INDEX IX_checkins_goal_created ON dbo.checkins (goal_id, created_at);

CREATE TABLE dbo.checkin_votes (
    checkin_id INT NOT NULL CONSTRAINT FK_checkin_votes_checkin REFERENCES dbo.checkins (id),
    voter_id INT NOT NULL CONSTRAINT FK_checkin_votes_voter REFERENCES dbo.users (id),
    created_at NVARCHAR(32) NOT NULL,
    CONSTRAINT UQ_checkin_votes_once UNIQUE (checkin_id, voter_id)
);

CREATE TABLE dbo.checkin_comments (
    id INT IDENTITY(1, 1) CONSTRAINT PK_checkin_comments PRIMARY KEY,
    checkin_id INT NOT NULL CONSTRAINT FK_checkin_comments_checkin REFERENCES dbo.checkins (id),
    author_id INT NOT NULL CONSTRAINT FK_checkin_comments_author REFERENCES dbo.users (id),
    text NVARCHAR(280) NOT NULL CONSTRAINT CK_checkin_comments_length CHECK (LEN(text) BETWEEN 1 AND 280),
    created_at NVARCHAR(32) NOT NULL
);
CREATE INDEX IX_checkin_comments_checkin ON dbo.checkin_comments (checkin_id);

-- One nudge per person, per nudger, per UTC day: UNIQUE makes spamming impossible.
CREATE TABLE dbo.nudges (
    id INT IDENTITY(1, 1) CONSTRAINT PK_nudges PRIMARY KEY,
    group_id INT NOT NULL CONSTRAINT FK_nudges_group REFERENCES dbo.groups (id),
    nudger_id INT NOT NULL CONSTRAINT FK_nudges_nudger REFERENCES dbo.users (id),
    nudged_id INT NOT NULL CONSTRAINT FK_nudges_nudged REFERENCES dbo.users (id),
    message NVARCHAR(140) NOT NULL CONSTRAINT CK_nudges_length CHECK (LEN(message) BETWEEN 1 AND 140),
    day NVARCHAR(10) NOT NULL,
    created_at NVARCHAR(32) NOT NULL,
    CONSTRAINT UQ_nudges_once_a_day UNIQUE (group_id, nudger_id, nudged_id, day),
    CONSTRAINT CK_nudges_not_yourself CHECK (nudger_id <> nudged_id)
);

-- Transactional outbox: points changes for the Points service, written in the
-- same transaction as the check-in or rejection, delivered afterwards.
-- Pending = neither sent nor failed.
CREATE TABLE dbo.points_outbox (
    id INT IDENTITY(1, 1) CONSTRAINT PK_points_outbox PRIMARY KEY,
    kind NVARCHAR(10) NOT NULL CONSTRAINT CK_points_outbox_kind CHECK (kind IN (N'record', N'revoke')),
    checkin_id INT NOT NULL CONSTRAINT FK_points_outbox_checkin REFERENCES dbo.checkins (id),
    group_id INT NOT NULL CONSTRAINT FK_points_outbox_group REFERENCES dbo.groups (id),
    payload NVARCHAR(MAX) NOT NULL CONSTRAINT CK_points_outbox_payload CHECK (ISJSON(payload) = 1),
    created_at NVARCHAR(32) NOT NULL,
    sent_at NVARCHAR(32) NULL,
    failed_at NVARCHAR(32) NULL,
    last_error NVARCHAR(MAX) NULL
);
-- Only the pending rows, oldest first: what every delivery reads.
CREATE INDEX IX_points_outbox_pending ON dbo.points_outbox (id) INCLUDE (group_id, checkin_id)
    WHERE sent_at IS NULL AND failed_at IS NULL;

-- One row that /health updates, to prove the service can write its database.
CREATE TABLE dbo.service_health (
    id INT NOT NULL CONSTRAINT PK_service_health PRIMARY KEY CONSTRAINT CK_service_health_one_row CHECK (id = 1),
    checked_at NVARCHAR(32) NOT NULL
);
INSERT INTO dbo.service_health (id, checked_at) VALUES (1, N'never');
