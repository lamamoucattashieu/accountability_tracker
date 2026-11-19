import pytest

from app.config import SETTLEMENT_DELAY, VOTING_WINDOW, MissingSecret, Settings


def test_defaults_work_without_any_environment(monkeypatch):
    for name in ("PORT", "DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.port == 8001  # Checkins has 8000, so both can run on one machine
    assert settings.db_path.as_posix().endswith("data/points.db")


def test_everything_is_configurable_through_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "s3cret")
    settings = Settings()
    assert settings.port == 9001
    assert settings.db_path == tmp_path / "points.db"
    assert settings.uploads_dir == tmp_path / "uploads"
    assert settings.auth_token_secret == "s3cret"


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_secret_stops_the_service_at_startup(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    else:
        monkeypatch.setenv("AUTH_TOKEN_SECRET", value)
    with pytest.raises(MissingSecret, match="AUTH_TOKEN_SECRET"):
        Settings().check_secrets()


def test_settlement_waits_for_the_whole_voting_window():
    assert SETTLEMENT_DELAY == VOTING_WINDOW
