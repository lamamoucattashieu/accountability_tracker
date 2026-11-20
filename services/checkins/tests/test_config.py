import pytest

from app.config import MissingSecret, Settings


def test_defaults_work_without_any_environment(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert Settings().port == 8000


def test_everything_is_configurable_through_environment_variables(monkeypatch):
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "mssql+pymssql://app:pw@db:1433/checkins")
    settings = Settings()
    assert settings.port == 9000
    assert settings.auth_token_secret == "s3cret"
    assert settings.database_url == "mssql+pymssql://app:pw@db:1433/checkins"


@pytest.mark.parametrize("name", ["DATABASE_URL", "AUTH_TOKEN_SECRET", "INTERNAL_API_KEY"])
@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_secret_stops_the_service_at_startup(monkeypatch, name, value):
    """Secrets have no default (A2 spec 8a), and DATABASE_URL holds a password."""
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(MissingSecret, match=name):
        Settings().check_secrets()
