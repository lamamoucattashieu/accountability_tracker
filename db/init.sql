-- db/init.sql: the two databases and one login per service, for the local compose stack.
--
-- Run by the one-off db-init service on every "docker compose up", with sqlcmd as sa.
-- Every statement checks first, so a second run changes nothing and never deletes data.
-- The passwords are never written here: sqlcmd replaces $(CHECKINS_DB_PASSWORD) and
-- $(POINTS_DB_PASSWORD) with the environment variables of the same name, which compose
-- reads from .env. The tables themselves come from each service's migrations.
--
-- Each service gets a contained database user (it exists only inside its own database,
-- like on Azure SQL), with exactly db_ddladmin (its migrations), db_datareader and
-- db_datawriter on that database, and no way into the other one (least privilege).

-- Lets a database have its own users. Setting it again to 1 changes nothing.
EXEC sp_configure 'contained database authentication', 1;
RECONFIGURE;
GO

IF DB_ID(N'checkins') IS NULL CREATE DATABASE checkins;
IF DB_ID(N'points') IS NULL CREATE DATABASE points;
GO

IF (SELECT containment FROM sys.databases WHERE name = N'checkins') = 0
    ALTER DATABASE checkins SET CONTAINMENT = PARTIAL;
IF (SELECT containment FROM sys.databases WHERE name = N'points') = 0
    ALTER DATABASE points SET CONTAINMENT = PARTIAL;
GO

-- checkins_app: Checkins' user, in the checkins database only.
USE checkins;
-- Created once; on later runs its password is set again, so .env stays the source of truth.
IF USER_ID(N'checkins_app') IS NULL
    CREATE USER checkins_app WITH PASSWORD = N'$(CHECKINS_DB_PASSWORD)', DEFAULT_SCHEMA = dbo;
ELSE
    ALTER USER checkins_app WITH PASSWORD = N'$(CHECKINS_DB_PASSWORD)';
IF IS_ROLEMEMBER(N'db_ddladmin', N'checkins_app') = 0 ALTER ROLE db_ddladmin ADD MEMBER checkins_app;
IF IS_ROLEMEMBER(N'db_datareader', N'checkins_app') = 0 ALTER ROLE db_datareader ADD MEMBER checkins_app;
IF IS_ROLEMEMBER(N'db_datawriter', N'checkins_app') = 0 ALTER ROLE db_datawriter ADD MEMBER checkins_app;
GO

-- points_app: Points' user, in the points database only.
USE points;
IF USER_ID(N'points_app') IS NULL
    CREATE USER points_app WITH PASSWORD = N'$(POINTS_DB_PASSWORD)', DEFAULT_SCHEMA = dbo;
ELSE
    ALTER USER points_app WITH PASSWORD = N'$(POINTS_DB_PASSWORD)';
IF IS_ROLEMEMBER(N'db_ddladmin', N'points_app') = 0 ALTER ROLE db_ddladmin ADD MEMBER points_app;
IF IS_ROLEMEMBER(N'db_datareader', N'points_app') = 0 ALTER ROLE db_datareader ADD MEMBER points_app;
IF IS_ROLEMEMBER(N'db_datawriter', N'points_app') = 0 ALTER ROLE db_datawriter ADD MEMBER points_app;
GO
