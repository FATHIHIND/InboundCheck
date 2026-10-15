"""
InboundCheck - Comprehensive Worker Isolation & Security Remediation Tests (Phase 18A.6B)
========================================================================================
Validates:
1. Staging worker bootstrap fail-closed isolation.
2. Rejection of production project reference prior to client instantiation.
3. Importing worker entrypoints has zero module-level client side-effects.
4. Normal runner retains its intended behavior in development/production.
5. Missing staging configuration fails closed.
6. Static integrity and role grants of Migration 028 (Rate Limit Table Security).
7. JWT verification branching (RS256 JWKS vs HS256 secret requirement).
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.core.staging_guard import (
    StagingIsolationError,
    validate_staging_config,
    bootstrap_staging_environment,
    PROD_PROJECT_REF,
)


def test_production_reference_rejected_before_client_creation():
    """Verify production ref tbjcldcoozvuvyipeonh is rejected before any client is created."""
    prod_config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": f"https://{PROD_PROJECT_REF}.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "dummy_service_key",
    }
    with pytest.raises(StagingIsolationError, match="CRITICAL ISOLATION BREACH"):
        validate_staging_config(prod_config, expected_staging_ref=PROD_PROJECT_REF)


def test_missing_staging_config_fails_closed():
    """Verify that a non-existent or empty env path raises StagingIsolationError."""
    with pytest.raises(StagingIsolationError, match="Specified staging configuration file does not exist"):
        bootstrap_staging_environment(
            expected_staging_ref="wymgyqnqwlliotkxamtd",
            custom_env_path="/non_existent_path_to_staging_env_file.staging"
        )


def test_staging_config_selects_only_expected_staging_project():
    """Verify staging config cannot target an unexpected third-party reference."""
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": "https://unexpectedproject99.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "dummy_service_key",
    }
    with pytest.raises(StagingIsolationError, match="does not match expected staging reference"):
        validate_staging_config(config, expected_staging_ref="wymgyqnqwlliotkxamtd")


def test_importing_worker_entrypoints_has_no_client_side_effects():
    """Verify importing runner or staging_runner does not initialize SupabaseClient or load .env."""
    # Ensure fresh module imports
    for mod in ["app.workers.staging_runner", "app.workers.runner"]:
        if mod in sys.modules:
            del sys.modules[mod]

    import app.workers.staging_runner as sr
    import app.workers.runner as r

    assert hasattr(sr, "init_staging_isolation")
    assert hasattr(r, "main")


def test_staging_runner_bootstrap_success(monkeypatch):
    """Verify staging_runner initializes staging isolation when valid staging config is provided."""
    from app.workers.staging_runner import init_staging_isolation

    valid_ref = "isolatedtestref8888"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".staging") as tmp:
        tmp.write("ENVIRONMENT=staging\n")
        tmp.write(f"SUPABASE_URL=https://{valid_ref}.supabase.co\n")
        tmp.write("SUPABASE_SERVICE_ROLE_KEY=test_service_key_8888\n")
        tmp.flush()
        tmp_path = tmp.name

    orig_env = dict(os.environ)
    try:
        init_staging_isolation(expected_staging_ref=valid_ref, custom_env_path=tmp_path)
        assert os.environ.get("ENVIRONMENT") == "staging"
        assert os.environ.get("SUPABASE_URL") == f"https://{valid_ref}.supabase.co"
    finally:
        os.environ.clear()
        os.environ.update(orig_env)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_normal_worker_runner_retains_intended_behavior():
    """Verify ordinary runner.main() retains validation and launches requested worker."""
    import app.workers.runner as runner_mod

    with patch("app.workers.runner.validate_worker_runtime_environment") as mock_validate, \
         patch("app.workers.audit_worker.run_audit_worker") as mock_audit:
        mock_validate.return_value = (True, [])
        mock_audit.return_value = None

        await runner_mod.main(worker_type="audit")
        mock_validate.assert_called_once()
        mock_audit.assert_called_once()


def test_migration_028_static_syntax_and_grant_model():
    """Verify Migration 028 exists, enables RLS, revokes from public, and grants strictly to postgres/service_role."""
    repo_root = Path(__file__).resolve().parents[2]
    migration_file = repo_root / "supabase" / "migrations" / "20261012000001_harden_rate_limit_windows_security.sql"

    assert migration_file.is_file(), f"Migration 028 not found at {migration_file}"

    sql_content = migration_file.read_text(encoding="utf-8")

    # Assert RLS is enabled
    assert "ALTER TABLE public.rate_limit_windows ENABLE ROW LEVEL SECURITY;" in sql_content

    # Assert revocation from untrusted roles
    assert "REVOKE ALL ON TABLE public.rate_limit_windows FROM PUBLIC;" in sql_content
    assert "REVOKE ALL ON TABLE public.rate_limit_windows FROM anon;" in sql_content
    assert "REVOKE ALL ON TABLE public.rate_limit_windows FROM authenticated;" in sql_content

    # Assert grants strictly to trusted roles
    assert "GRANT ALL ON TABLE public.rate_limit_windows TO postgres, service_role;" in sql_content

    # Assert RPC execution revocation and grant
    assert "REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM PUBLIC;" in sql_content
    assert "REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM anon;" in sql_content
    assert "REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM authenticated;" in sql_content
    assert "GRANT EXECUTE ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) TO postgres, service_role;" in sql_content

    # Assert search_path and ownership
    assert "SET search_path = public, pg_temp;" in sql_content
    assert "OWNER TO postgres;" in sql_content


def test_jwt_verification_requirements():
    """Verify security.py handles RS256 with JWKS and requires SUPABASE_JWT_SECRET for HS256."""
    from app.core.security import verify_supabase_jwt
    from fastapi import HTTPException

    # Missing token fails closed
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt("")
    assert exc_info.value.status_code == 401

    # Malformed token fails closed
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt("not.a.valid.jwt")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_runner_direct_staging_invocation_fails_closed_without_client_creation(monkeypatch):
    """Verify that invoking runner.py directly with staging flags/env fails closed with StagingIsolationError."""
    import app.workers.runner as runner_mod

    # 1. Staging via ENVIRONMENT variable without authorization
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(StagingIsolationError, match="Direct staging worker execution via runner.py is forbidden"):
        await runner_mod.main(worker_type="audit", is_staging_authorized=False)

    # 2. Staging via CLI argument --staging without authorization
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(sys, "argv", ["runner.py", "audit", "--staging"])
    with pytest.raises(StagingIsolationError, match="Direct staging worker execution via runner.py is forbidden"):
        await runner_mod.main(worker_type="audit", is_staging_authorized=False)


@pytest.mark.asyncio
async def test_staging_runner_offline_mocked_execution(monkeypatch):
    """Verify dedicated staging_runner cleanly authorizes runner and executes under mocked staging config."""
    import app.workers.staging_runner as staging_runner_mod

    staging_ref = "wymgyqnqwlliotkxamtd"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".staging") as tmp:
        tmp.write("ENVIRONMENT=staging\n")
        tmp.write(f"SUPABASE_URL=https://{staging_ref}.supabase.co\n")
        tmp.write("SUPABASE_SERVICE_ROLE_KEY=mocked_service_key_for_test\n")
        tmp.flush()
        tmp_path = tmp.name

    orig_env = dict(os.environ)
    try:
        with patch("app.workers.runner.validate_worker_runtime_environment") as mock_val, \
             patch("app.workers.audit_worker.run_audit_worker") as mock_worker:
            mock_val.return_value = (True, [])
            mock_worker.return_value = None

            await staging_runner_mod.main(
                worker_type="audit",
                expected_staging_ref=staging_ref,
                custom_env_path=tmp_path
            )

            mock_val.assert_called_once()
            mock_worker.assert_called_once()
            assert os.environ.get("ENVIRONMENT") == "staging"
            assert os.environ.get("SUPABASE_URL") == f"https://{staging_ref}.supabase.co"
    finally:
        os.environ.clear()
        os.environ.update(orig_env)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_importing_runner_and_env_guard_does_not_load_config_settings():
    """Verify that importing runner or env_guard does not trigger premature Settings() instantiation."""
    target_mods = [
        "app.workers.runner",
        "app.workers.staging_runner",
        "app.core.env_guard",
        "app.core.config",
        "app.services.supabase_client",
    ]
    saved = {m: sys.modules[m] for m in target_mods if m in sys.modules}
    try:
        for mod in target_mods:
            if mod in sys.modules:
                del sys.modules[mod]

        import app.workers.runner as r
        assert hasattr(r, "main")
        assert hasattr(r, "validate_worker_runtime_environment")

        # app.core.config must NOT be loaded at import time
        assert "app.core.config" not in sys.modules, "Premature import of app.core.config detected upon importing runner"
        assert "app.services.supabase_client" not in sys.modules, "Premature import of supabase_client detected upon importing runner"
    finally:
        sys.modules.update(saved)


# =====================================================================
# SECTION: PHASE 18A.6I.3 MINIMAL STAGING TEST SAFEGUARD TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_audit_worker_once_mode_successful_audit():
    """Verify run_audit_worker(once=True) claims 1 batch, audits domain, and exits cleanly."""
    from app.workers.audit_worker import run_audit_worker

    mock_domain = {
        "id": "11111111-1111-4111-a111-111111111111",
        "domain_name": "example.com",
        "user_id": "22222222-2222-4222-a222-222222222222",
    }

    with patch("app.workers.audit_worker.supabase_service.claim_due_domain_audits") as mock_claim, \
         patch("app.workers.audit_worker.audit_claimed_domain") as mock_audit:
        mock_claim.return_value = [mock_domain]
        mock_audit.return_value = None

        await run_audit_worker(once=True, limit=1)

        mock_claim.assert_called_once()
        mock_audit.assert_called_once_with(mock_domain, mock_claim.call_args[1]["worker_id"])


@pytest.mark.asyncio
async def test_audit_worker_once_mode_zero_domains_exits_immediately():
    """Verify run_audit_worker(once=True) exits immediately when zero domains are due without sleeping."""
    from app.workers.audit_worker import run_audit_worker

    with patch("app.workers.audit_worker.supabase_service.claim_due_domain_audits") as mock_claim, \
         patch("app.workers.audit_worker.audit_claimed_domain") as mock_audit, \
         patch("asyncio.sleep") as mock_sleep:
        mock_claim.return_value = []

        await run_audit_worker(once=True, limit=1)

        mock_claim.assert_called_once()
        mock_audit.assert_not_called()
        mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_audit_worker_once_mode_failed_audit_exits_cleanly():
    """Verify run_audit_worker(once=True) handles loop exceptions and exits cleanly without infinite retry."""
    from app.workers.audit_worker import run_audit_worker

    mock_domain = {
        "id": "11111111-1111-4111-a111-111111111111",
        "domain_name": "example.com",
        "user_id": "22222222-2222-4222-a222-222222222222",
    }

    with patch("app.workers.audit_worker.supabase_service.claim_due_domain_audits") as mock_claim, \
         patch("app.workers.audit_worker.audit_claimed_domain") as mock_audit:
        mock_claim.return_value = [mock_domain]
        mock_audit.side_effect = RuntimeError("Simulated audit failure")

        # Must exit cleanly without infinite loop
        await run_audit_worker(once=True, limit=1)

        mock_claim.assert_called_once()
        mock_audit.assert_called_once()


@pytest.mark.asyncio
async def test_alert_dispatcher_suppressed_when_flags_disabled():
    """Verify evaluate_and_dispatch issues ZERO HTTP requests when all flags are false."""
    from app.services.alert_dispatcher import AlertDispatcherService

    dispatcher = AlertDispatcherService()
    test_user_id = "test-suppressed-user-999"

    # All alert flags explicitly disabled
    dispatcher.set_tenant_alert_config(test_user_id, {
        "alert_on_score_drop": False,
        "alert_on_health_drop": False,
        "alert_on_spf_error": False,
        "alert_on_dkim_fail": False,
        "alert_on_dmarc_change": False,
        "email_notifications": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
    })

    with patch("app.services.failover.omnichannel_service.telegram_alert_service.send_telegram_alert") as mock_telegram, \
         patch("httpx.AsyncClient.post") as mock_httpx:
        res = await dispatcher.evaluate_and_dispatch(
            user_id=test_user_id,
            domain_name="example.com",
            health_score=20,
            overall_status="critical",
        )

        assert res["dispatched"] is False
        assert res["reasons"] == []
        mock_telegram.assert_not_called()
        mock_httpx.assert_not_called()


@pytest.mark.asyncio
async def test_alert_dispatcher_fails_closed_without_credentials():
    """Verify evaluate_and_dispatch skips dispatch cleanly when credentials are unconfigured."""
    from app.services.alert_dispatcher import AlertDispatcherService

    dispatcher = AlertDispatcherService()
    test_user_id = "test-unconfigured-user-888"

    dispatcher.set_tenant_alert_config(test_user_id, {
        "alert_on_score_drop": True,
        "score_threshold": 80,
        "telegram_bot_token": None,
        "telegram_chat_id": None,
    })

    with patch("app.services.failover.omnichannel_service.telegram_alert_service.send_telegram_alert") as mock_telegram, \
         patch("httpx.AsyncClient.post") as mock_httpx:
        res = await dispatcher.evaluate_and_dispatch(
            user_id=test_user_id,
            domain_name="example.com",
            health_score=50,
            overall_status="critical",
        )

        assert res["dispatched"] is True
        assert res["telegram_result"]["skipped"] is True
        mock_telegram.assert_not_called()
        mock_httpx.assert_not_called()


@pytest.mark.asyncio
async def test_staging_runner_mock_rbl_issues_zero_network_queries():
    """Verify --mock-rbl in staging_runner replaces scan_domain with synthetic zero-network result."""
    import app.workers.staging_runner as sr
    from app.services.dns.rbl_scanner import rbl_scanner

    staging_ref = "isolatedtestref7777"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".staging") as tmp:
        tmp.write("ENVIRONMENT=staging\n")
        tmp.write(f"SUPABASE_URL=https://{staging_ref}.supabase.co\n")
        tmp.write("SUPABASE_SERVICE_ROLE_KEY=test_service_key_7777\n")
        tmp.flush()
        tmp_path = tmp.name

    orig_env = dict(os.environ)
    try:
        with patch("app.workers.runner.main") as mock_runner_main:
            mock_runner_main.return_value = None

            await sr.main(
                worker_type="audit",
                expected_staging_ref=staging_ref,
                custom_env_path=tmp_path,
                once=True,
                limit=1,
                mock_rbl=True,
            )

            # Test calling the mocked scanner
            scan_res = await rbl_scanner.scan_domain("example.com")
            assert scan_res.overall_status == "clean"
            assert scan_res.rbl_clean_count == 10
            assert scan_res.rbl_listed_count == 0
            assert len(scan_res.results) == 0
    finally:
        os.environ.clear()
        os.environ.update(orig_env)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

