"""
OPS-3 / P0-7: production alerting must be configured.

REV-3: only the failover WORKER fails closed in production when no ops alert
channel is configured (unless OPS_ALERT_REQUIRED is explicitly false). The API
process never refuses to start for missing alerting (that would also take down
billing / Shopify / GDPR webhooks): it logs CRITICAL and /ready reports
`alerting: unconfigured`. Non-production environments only warn. The guard and
OpsAlertService resolve channels with the same placeholder-skipping helper.
"""

import logging
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.env_guard import get_ops_alerting_status, validate_ops_alerting_configuration

_ALERT_ENV_KEYS = (
    "OPS_ALERT_WEBHOOK_URL",
    "OPS_ALERT_TELEGRAM_BOT_TOKEN",
    "OPS_ALERT_TELEGRAM_CHAT_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


@pytest.fixture
def no_alert_channels(monkeypatch):
    for key in _ALERT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "OPS_ALERT_REQUIRED", True)
    yield


def test_status_unconfigured_when_no_channel(no_alert_channels):
    assert get_ops_alerting_status() == "unconfigured"


def test_status_configured_with_webhook(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "OPS_ALERT_WEBHOOK_URL", "https://hooks.internal.invalid/ops")
    assert get_ops_alerting_status() == "configured"


def test_status_configured_with_telegram_pair(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "OPS_ALERT_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(settings, "OPS_ALERT_TELEGRAM_CHAT_ID", "-100")
    assert get_ops_alerting_status() == "configured"


def test_status_unconfigured_with_telegram_token_only(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "OPS_ALERT_TELEGRAM_BOT_TOKEN", "123:abc")
    assert get_ops_alerting_status() == "unconfigured"


def test_placeholder_channel_is_unconfigured(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "OPS_ALERT_WEBHOOK_URL", "your_webhook_url_here")
    assert get_ops_alerting_status() == "unconfigured"


def test_production_worker_without_channel_fails_startup(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="OPS_ALERT"):
        validate_ops_alerting_configuration(component="failover-worker")


def test_production_api_without_channel_logs_critical_and_does_not_raise(no_alert_channels, monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert validate_ops_alerting_configuration(component="api") is False
    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical and "OPS_ALERT" in critical[0].getMessage()


def test_production_with_channel_passes(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "OPS_ALERT_WEBHOOK_URL", "https://hooks.internal.invalid/ops")
    assert validate_ops_alerting_configuration(component="api") is True


def test_production_opt_out_only_warns(no_alert_channels, monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "OPS_ALERT_REQUIRED", False)
    assert validate_ops_alerting_configuration(component="failover-worker") is False
    assert "OPS_ALERT_REQUIRED" in caplog.text


def test_non_production_only_warns(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert validate_ops_alerting_configuration(component="api") is False


def test_secret_values_never_in_error(no_alert_channels, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "OPS_ALERT_TELEGRAM_BOT_TOKEN", "999:supersecrettoken")
    with pytest.raises(RuntimeError) as exc_info:
        validate_ops_alerting_configuration(component="failover-worker")
    assert "supersecrettoken" not in str(exc_info.value)


def test_ops_alert_required_defaults_true():
    from app.core.config import Settings

    assert Settings.model_fields["OPS_ALERT_REQUIRED"].default is True


@pytest.mark.asyncio
async def test_api_lifespan_starts_without_alerting_in_production(no_alert_channels, monkeypatch, caplog):
    from app import main as app_main

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    started = False
    with patch.object(app_main, "validate_runtime_environment", return_value=(True, [])):
        async with app_main.lifespan(app_main.app):
            started = True
    assert started
    assert any(r.levelno >= logging.CRITICAL and "OPS_ALERT" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_failover_worker_startup_enforces_alerting_in_production(no_alert_channels, monkeypatch):
    from app.core.schema_contract import SchemaContractResult
    from app.services.failover.failover_repository import failure_event_repository as repository
    from app.workers.failover_worker import run_failover_worker

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with patch.object(repository, "claim_pending_delivery_failure_events") as mock_claim:
        with pytest.raises(RuntimeError, match="OPS_ALERT"):
            await run_failover_worker(
                once=True, schema_probe=lambda: SchemaContractResult(status="ok")
            )
    mock_claim.assert_not_called()


def test_ready_payload_exposes_alerting_status(no_alert_channels):
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.services.supabase_client.supabase_service.check_db_health", return_value=True):
        res = TestClient(app).get("/ready")
    assert res.status_code == 200
    assert res.json()["alerting"] == "unconfigured"


# ---------------------------------------------------------------------------
# REV-3: guard and OpsAlertService agree on channel resolution
# ---------------------------------------------------------------------------

def test_service_skips_placeholder_webhook_like_guard(no_alert_channels, monkeypatch):
    from app.services.alerting.ops_alert_service import OpsAlertService

    monkeypatch.setattr(settings, "OPS_ALERT_WEBHOOK_URL", "your_webhook_url_here")
    svc = OpsAlertService()
    assert svc.webhook_url == ""
    assert svc.is_configured() is False
    assert get_ops_alerting_status() == "unconfigured"


def test_service_falls_back_past_placeholder_token_like_guard(no_alert_channels, monkeypatch):
    from app.services.alerting.ops_alert_service import OpsAlertService

    # Placeholder OPS_* values must not shadow working TELEGRAM_* fallbacks (and vice versa).
    monkeypatch.setattr(settings, "OPS_ALERT_TELEGRAM_BOT_TOKEN", "placeholder_token")
    monkeypatch.setattr(settings, "OPS_ALERT_TELEGRAM_CHAT_ID", "change_me")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:realtoken")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "-100200")
    svc = OpsAlertService()
    assert svc.telegram_bot_token == "123:realtoken"
    assert svc.telegram_chat_id == "-100200"
    assert svc.is_configured() is True
    assert get_ops_alerting_status() == "configured"


@pytest.mark.parametrize("env", [
    {},
    {"OPS_ALERT_WEBHOOK_URL": "https://hooks.internal.invalid/ops"},
    {"OPS_ALERT_WEBHOOK_URL": "dummy"},
    {"OPS_ALERT_TELEGRAM_BOT_TOKEN": "1:a", "OPS_ALERT_TELEGRAM_CHAT_ID": "-1"},
    {"OPS_ALERT_TELEGRAM_BOT_TOKEN": "your_token", "OPS_ALERT_TELEGRAM_CHAT_ID": "-1"},
    {"OPS_ALERT_TELEGRAM_BOT_TOKEN": "1:a"},
    {"TELEGRAM_BOT_TOKEN": "1:a", "TELEGRAM_CHAT_ID": "-1"},
])
def test_guard_status_matches_service_is_configured(no_alert_channels, monkeypatch, env):
    from app.services.alerting.ops_alert_service import OpsAlertService

    for key, value in env.items():
        monkeypatch.setattr(settings, key, value)
    assert (get_ops_alerting_status() == "configured") is OpsAlertService().is_configured()
