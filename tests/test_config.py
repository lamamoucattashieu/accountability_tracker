import pytest

from app.config import Settings


def test_defaults_work_without_any_environment(monkeypatch):
    for name in ("PORT", "DATA_DIR", "COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.port == 8000
    assert settings.db_path.as_posix().endswith("data/app.db")
    assert settings.cookie_secure is False


def test_everything_is_configurable_through_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COOKIE_SECURE", "true")
    settings = Settings()
    assert settings.port == 9000
    assert settings.db_path == tmp_path / "app.db"
    assert settings.uploads_dir == tmp_path / "uploads"
    assert settings.cookie_secure is True


@pytest.mark.parametrize("value, secure", [("1", True), ("YES", True), ("false", False), ("0", False)])
def test_cookie_secure_accepts_common_spellings(monkeypatch, value, secure):
    monkeypatch.setenv("COOKIE_SECURE", value)
    assert Settings().cookie_secure is secure
