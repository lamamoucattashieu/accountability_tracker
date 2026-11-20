import pytest

from app.config import FORFEIT_MAX_LENGTH, SETTLEMENT_DELAY, VOTING_WINDOW, MissingSecret, Settings


def test_defaults_work_without_any_environment(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert Settings().port == 8001  # Checkins has 8000, so both can run on one machine


def test_everything_is_configurable_through_environment_variables(monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "mssql+pymssql://app:pw@db:1433/points")
    settings = Settings()
    assert settings.port == 9001
    assert settings.auth_token_secret == "s3cret"
    assert settings.database_url == "mssql+pymssql://app:pw@db:1433/points"


@pytest.mark.parametrize("name", ["DATABASE_URL", "AUTH_TOKEN_SECRET", "INTERNAL_API_KEY"])
@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_secret_stops_the_service_at_startup(monkeypatch, name, value):
    """Secrets have no default (A2 spec 8a), and DATABASE_URL holds a password."""
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(MissingSecret, match=name):
        Settings().check_secrets()


def test_settlement_waits_for_the_whole_voting_window():
    assert SETTLEMENT_DELAY == VOTING_WINDOW


def test_the_forfeit_limit_matches_the_schema(conn):
    """migrations/001_init.sql can't read config.py, so the two numbers are compared here."""
    size = conn.execute(
        "SELECT max_length FROM sys.columns WHERE object_id = OBJECT_ID('dbo.forfeits') AND name = 'text'"
    ).fetchone()["max_length"] // 2
    check = conn.execute(
        "SELECT definition FROM sys.check_constraints WHERE name = 'CK_forfeits_length'"
    ).fetchone()["definition"]
    assert size == FORFEIT_MAX_LENGTH
    assert f"({FORFEIT_MAX_LENGTH})" in check
