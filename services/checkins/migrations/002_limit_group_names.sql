-- 002: group names get a length limit, like usernames, comments and nudges already have.
--
-- 001 created groups.name as NVARCHAR(MAX) and the code only refused empty names, so a
-- name could be any length. This changes a table that already holds data (A2 spec 4.3),
-- keeping every row:
--   1. any name longer than 60 characters is shortened to its first 60 (trailing spaces
--      removed); shorter names are not touched;
--   2. the column becomes NVARCHAR(60) NOT NULL, which only works once step 1 is done;
--   3. a CHECK keeps every name between 1 and 60 characters from now on.
-- 60 is GROUP_NAME_MAX_LENGTH in app/config.py (tests/test_schema_limits.py compares them).
-- The runner applies all three batches in one transaction: all of it, or none of it.

UPDATE dbo.groups SET name = RTRIM(LEFT(name, 60)) WHERE LEN(name) > 60;
GO

ALTER TABLE dbo.groups ALTER COLUMN name NVARCHAR(60) NOT NULL;
GO

ALTER TABLE dbo.groups ADD CONSTRAINT CK_groups_name_length CHECK (LEN(name) BETWEEN 1 AND 60);
