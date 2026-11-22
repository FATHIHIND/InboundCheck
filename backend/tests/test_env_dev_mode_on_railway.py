import pytest
import asyncio

from app.core.config import Settings
from app.core import env_guard


@pytest.fixture(autouse=True)
def clear_railway(monkeypatch):
    monkeypatch.delenv("RAILWAY_SERVICE_NAME", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)


@pytest.mark.parametrize("marker", ["RAILWAY_SERVICE_NAME", "RAILWAY_GIT_COMMIT_SHA"])
@pytest.mark.parametrize("value,expected", [("production", "production"), (" PROD ", "prod"), (" STAGING ", "staging")])
def test_settings_normalize_approved_railway_modes(monkeypatch, marker, value, expected):
    monkeypatch.setenv(marker, "present")
    assert Settings(_env_file=None, ENVIRONMENT=value).ENVIRONMENT == expected


@pytest.mark.parametrize("value", [None, "", "  ", "development", "test", "testing", "local", "unknown"])
def test_settings_reject_unsafe_railway_modes(monkeypatch, value):
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "present")
    kwargs = {} if value is None else {"ENVIRONMENT": value}
    with pytest.raises(RuntimeError, match="Railway ENVIRONMENT"):
        Settings(_env_file=None, **kwargs)


def test_local_mode_remains_unchanged():
    assert Settings(_env_file=None, ENVIRONMENT=" Development ").ENVIRONMENT == " Development "


def test_guard_rejects_unknown_mode_on_railway(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "present")
    with pytest.raises(RuntimeError, match="Railway ENVIRONMENT"):
        env_guard.assert_not_development_mode_on_railway("unknown")


def test_direct_worker_rejects_staging_loaded_from_settings(monkeypatch):
    from app.core.config import settings
    from app.core.staging_guard import StagingIsolationError
    from app.workers.runner import main

    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    with pytest.raises(StagingIsolationError):
        asyncio.run(main(once=True))


def test_both_markers_accept_only_approved_mode(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "api")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    assert Settings(_env_file=None, ENVIRONMENT=" Staging ").ENVIRONMENT == "staging"
    with pytest.raises(RuntimeError, match="Railway ENVIRONMENT"):
        Settings(_env_file=None, ENVIRONMENT="testing")


def test_resolved_dotenv_value_is_validated_before_use(monkeypatch, tmp_path):
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "api")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text("ENVIRONMENT= STAGING \n", encoding="utf-8")
    assert Settings(_env_file=dotenv).ENVIRONMENT == "staging"
    monkeypatch.setenv("ENVIRONMENT", " PROD ")
    assert Settings(_env_file=dotenv).ENVIRONMENT == "prod"


def test_railway_rejection_does_not_echo_input(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "api")
    with pytest.raises(RuntimeError) as error:
        Settings(_env_file=None, ENVIRONMENT="sensitive-unknown-value")
    assert "sensitive-unknown-value" not in str(error.value)
