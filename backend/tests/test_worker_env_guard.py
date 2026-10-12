"""
InboundCheck - Dedicated Background Worker Runtime Guard & Isolation Tests (Phase 18A.7.3)
========================================================================================
Validates:
1. Fail-fast validation of SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
2. HTTPS protocol enforcement for production Supabase endpoints.
3. Successful worker validation when Stripe keys and SUPABASE_JWT_SECRET are omitted.
4. Regression protection: API validation still strictly requires Stripe and JWT secrets.
5. Runner staging isolation gate remains enforced.
6. Validation issues and error messages never leak sensitive credential values.
"""

from unittest.mock import patch, MagicMock
import pytest

from app.core.config import settings
from app.core.env_guard import (
    validate_worker_runtime_environment,
    validate_runtime_environment,
)
from app.core.staging_guard import StagingIsolationError


def test_worker_guard_missing_supabase_url_fails_closed():
    """In production, missing SUPABASE_URL must abort immediately."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", ""), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-999"):
        with pytest.raises(RuntimeError, match="Production Worker Environment Integrity Failure") as exc_info:
            validate_worker_runtime_environment()
        assert "SUPABASE_URL is missing" in str(exc_info.value)


def test_worker_guard_placeholder_supabase_url_fails_closed():
    """In production, placeholder SUPABASE_URL must abort immediately."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://your-project.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-999"):
        with pytest.raises(RuntimeError, match="Production Worker Environment Integrity Failure") as exc_info:
            validate_worker_runtime_environment()
        assert "contains placeholder values" in str(exc_info.value)


def test_worker_guard_non_https_url_fails_closed_in_production():
    """In production, HTTP (non-SSL) SUPABASE_URL must abort immediately."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "http://secureproject.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-999"):
        with pytest.raises(RuntimeError, match="SUPABASE_URL must use HTTPS in production"):
            validate_worker_runtime_environment()


def test_worker_guard_missing_service_role_key_fails_closed():
    """In production, missing SUPABASE_SERVICE_ROLE_KEY must abort immediately."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://secureproject.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""):
        with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY is unconfigured"):
            validate_worker_runtime_environment()


def test_worker_guard_placeholder_service_role_key_fails_closed():
    """In production, placeholder SUPABASE_SERVICE_ROLE_KEY must abort immediately."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://secureproject.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "your_service_role_key_dummy"):
        with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY is unconfigured or placeholder"):
            validate_worker_runtime_environment()


def test_worker_guard_does_not_fall_back_to_anon_key():
    """Worker guard must require SUPABASE_SERVICE_ROLE_KEY specifically, not accepting anon key alone."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://secureproject.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""), \
         patch.object(settings, "SUPABASE_KEY", "valid-anon-key-only"):
        with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY is unconfigured"):
            validate_worker_runtime_environment()


def test_worker_guard_valid_without_stripe_or_jwt_passes():
    """Worker boots cleanly with database credentials even when Stripe keys and JWT secret are completely absent."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://secureproject.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-12345"), \
         patch.object(settings, "SUPABASE_JWT_SECRET", ""), \
         patch.object(settings, "STRIPE_SECRET_KEY", ""), \
         patch.object(settings, "STRIPE_WEBHOOK_SECRET", ""), \
         patch.object(settings, "STRIPE_PRICE_STARTER", ""), \
         patch.object(settings, "STRIPE_PRICE_GROWTH", ""):
        is_valid, issues = validate_worker_runtime_environment()
        assert is_valid is True
        assert issues == []


def test_api_guard_regression_still_requires_stripe_and_jwt():
    """API validator validate_runtime_environment must continue enforcing Stripe and JWT in production."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://secureproject.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-12345"), \
         patch.object(settings, "SUPABASE_JWT_SECRET", ""), \
         patch.object(settings, "STRIPE_SECRET_KEY", ""):
        with pytest.raises(RuntimeError, match="Production Environment Integrity Failure") as exc_info:
            validate_runtime_environment()
        err_text = str(exc_info.value)
        assert "SUPABASE_JWT_SECRET is required in production" in err_text
        assert "STRIPE_SECRET_KEY is required in production" in err_text


def test_worker_guard_dev_mode_warns_without_crashing():
    """In development mode, validation issues return (False, issues) without raising RuntimeError."""
    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "SUPABASE_URL", ""), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""):
        is_valid, issues = validate_worker_runtime_environment()
        assert is_valid is False
        assert len(issues) >= 2


def test_worker_guard_no_secrets_in_error_or_log_messages():
    """Ensure error messages and logs never leak secret strings."""
    secret_token = "super_confidential_secret_value_xyz123"
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "http://insecure-endpoint.com"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "placeholder_secret_key"):
        with pytest.raises(RuntimeError) as exc_info:
            validate_worker_runtime_environment()
        msg = str(exc_info.value)
        assert secret_token not in msg
        assert "placeholder_secret_key" not in msg


@pytest.mark.asyncio
async def test_runner_preserves_staging_isolation_gate():
    """runner.main() must continue rejecting direct staging invocation."""
    from app.workers.runner import main as runner_main
    with patch.dict("os.environ", {"ENVIRONMENT": "staging"}):
        with pytest.raises(StagingIsolationError, match="Direct staging worker execution via runner.py is forbidden"):
            await runner_main(worker_type="audit", is_staging_authorized=False)


# =====================================================================
# SECTION: PHASE 18A.7.7 URL CONTROL-CHARACTER & RPC FAIL-CLOSED TESTS
# =====================================================================

def test_supabase_url_with_crlf_fails_closed():
    """URL with \\n, \\r, or other ASCII control characters must fail closed."""
    for dirty_url in [
        "https://secureproject.supabase.co\n",
        "https://secureproject.supabase.co\r\n",
        "https://secureproject.supabase.co\r",
        "https://secure\nproject.supabase.co",
        "https://secureproject.supabase.co\x00",
    ]:
        with patch.object(settings, "ENVIRONMENT", "production"), \
             patch.object(settings, "SUPABASE_URL", dirty_url), \
             patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-12345"):
            with pytest.raises(RuntimeError, match="invalid ASCII control characters") as exc_info:
                validate_worker_runtime_environment()
            assert "CR, LF, NUL" in str(exc_info.value)


def test_supabase_url_with_outer_whitespace_normalized():
    """Outer spaces (strictly non-control chars) normalize cleanly and pass validation."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "  https://secureproject.supabase.co/  "), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-12345"):
        is_valid, issues = validate_worker_runtime_environment()
        assert is_valid is True
        assert issues == []


def test_supabase_url_malformed_host_or_query_fails_closed():
    """Malformed hosts, query parameters, or fragments must fail closed."""
    invalid_cases = [
        ("https:///path", "missing a valid host"),
        ("https://invalid-host", "invalid or missing domain suffix"),
        ("https://secureproject.supabase.co?token=secret", "must not contain query parameters"),
        ("https://secureproject.supabase.co#fragment", "must not contain query parameters or fragments"),
    ]
    for bad_url, expected_match in invalid_cases:
        with patch.object(settings, "ENVIRONMENT", "production"), \
             patch.object(settings, "SUPABASE_URL", bad_url), \
             patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-service-role-key-12345"):
            with pytest.raises(RuntimeError) as exc_info:
                validate_worker_runtime_environment()
            assert expected_match in str(exc_info.value)


def test_claim_due_domain_audits_fails_closed_in_production_on_rpc_error():
    """In production, claim_due_domain_audits must raise DatabaseUnavailableError on RPC error, never returning empty list."""
    from app.services.supabase_client import supabase_service, DatabaseUnavailableError

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.side_effect = Exception("Invalid non-printable ASCII character in URL")

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        with pytest.raises(DatabaseUnavailableError, match="Database RPC claim_due_domain_audits failed in production"):
            supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)


def test_claim_due_domain_audits_disconnected_client_fails_closed_in_production():
    """In production, claim_due_domain_audits must fail closed if client is None."""
    from app.services.supabase_client import supabase_service, DatabaseUnavailableError

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", None):
        assert supabase_service._allow_in_memory_fallback() is False
        with pytest.raises(DatabaseUnavailableError, match="Database client is not connected in production"):
            supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)


def test_claim_due_domain_audits_allows_in_memory_in_test_environment():
    """In test environment, claim_due_domain_audits cleanly falls back to memory without crashing."""
    from app.services.supabase_client import supabase_service

    with patch.object(settings, "ENVIRONMENT", "test"), \
         patch.object(supabase_service, "_client", None):
        assert supabase_service._allow_in_memory_fallback() is True
        # In test mode, fallback is allowed and returns empty list or in-memory items
        domains = supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)
        assert isinstance(domains, list)


def test_claim_pending_delivery_failure_events_fails_closed_in_production():
    """In production, claim_pending_delivery_failure_events must raise DatabaseUnavailableError on RPC error."""
    from app.services.supabase_client import supabase_service, DatabaseUnavailableError

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.side_effect = Exception("Invalid non-printable ASCII character in URL")

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        with pytest.raises(DatabaseUnavailableError, match="Database RPC claim_pending_delivery_failure_events failed in production"):
            supabase_service.claim_pending_delivery_failure_events(worker_id="test-worker", limit=10)


def test_failover_repository_fails_closed_in_production():
    """In production, failover_repository must propagate DatabaseUnavailableError on RPC error."""
    from app.services.failover.failover_repository import FailoverRepository
    from app.services.supabase_client import supabase_service, DatabaseUnavailableError

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.side_effect = Exception("Invalid non-printable ASCII character in URL")

    repo = FailoverRepository()
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert repo.supabase._allow_in_memory_fallback() is False
        with pytest.raises(DatabaseUnavailableError, match="Database RPC claim_pending_delivery_failure_events failed in production"):
            repo.claim_pending_delivery_failure_events(worker_id="test-worker", limit=10)
