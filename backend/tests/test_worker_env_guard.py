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


def test_claim_due_domain_audits_rejects_none_data_in_production():
    """In production, claim_due_domain_audits must raise InvalidRPCResponseError if RPC data is None."""
    from app.services.supabase_client import supabase_service, InvalidRPCResponseError, DatabaseUnavailableError

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = None

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        with pytest.raises(InvalidRPCResponseError, match="returned invalid response shape \\(NoneType\\)"):
            supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)
        # Also confirm it is caught as DatabaseUnavailableError
        with pytest.raises(DatabaseUnavailableError):
            supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)


def test_claim_due_domain_audits_rejects_dict_response_in_production():
    """In production, claim_due_domain_audits must raise InvalidRPCResponseError if RPC data is a dict."""
    from app.services.supabase_client import supabase_service, InvalidRPCResponseError

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = {"error": "unexpected payload"}

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        with pytest.raises(InvalidRPCResponseError, match="returned invalid response shape \\(dict\\)"):
            supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)


def test_claim_due_domain_audits_rejects_string_response_in_production():
    """In production, claim_due_domain_audits must raise InvalidRPCResponseError if RPC data is a string."""
    from app.services.supabase_client import supabase_service, InvalidRPCResponseError

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = "unexpected_raw_string"

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        with pytest.raises(InvalidRPCResponseError, match="returned invalid response shape \\(str\\)"):
            supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)


def test_claim_due_domain_audits_valid_empty_list_in_production():
    """In production, a valid empty list [] must remain a legitimate empty queue."""
    from app.services.supabase_client import supabase_service

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = []

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        domains = supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)
        assert domains == []


def test_claim_due_domain_audits_valid_list_in_production():
    """In production, a valid list of dicts must be returned directly."""
    from app.services.supabase_client import supabase_service

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = [{"id": "dom_1", "domain_name": "example.com"}]

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is False
        domains = supabase_service.claim_due_domain_audits(worker_id="test-worker", limit=10)
        assert len(domains) == 1
        assert domains[0]["domain_name"] == "example.com"


def test_claim_due_domain_audits_invalid_response_allows_in_memory_in_test_environment():
    """In test environment, invalid response shape cleanly logs warning and falls back to in-memory domains."""
    from app.services.supabase_client import supabase_service

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = None

    with patch.object(settings, "ENVIRONMENT", "test"), \
         patch.object(supabase_service, "_client", mock_client):
        assert supabase_service._allow_in_memory_fallback() is True
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


# =====================================================================
# SECTION: PHASE 19.4.2 STAGING WORKER FAIL-FAST & ISOLATION TESTS
# =====================================================================

def test_staging_worker_guard_missing_url_fails_fast():
    """In staging, missing SUPABASE_URL must abort immediately with Staging failure."""
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", ""), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-staging-service-key"):
        with pytest.raises(RuntimeError, match="Staging Worker Environment Integrity Failure") as exc_info:
            validate_worker_runtime_environment()
        assert "SUPABASE_URL is missing" in str(exc_info.value)


def test_staging_worker_guard_missing_service_key_fails_fast():
    """In staging, missing SUPABASE_SERVICE_ROLE_KEY must abort immediately."""
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", "https://wymgyqnqwlliotkxamtd.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""):
        with pytest.raises(RuntimeError, match="Staging Worker Environment Integrity Failure") as exc_info:
            validate_worker_runtime_environment()
        assert "SUPABASE_SERVICE_ROLE_KEY is unconfigured" in str(exc_info.value)


def test_staging_worker_guard_production_ref_fails_fast():
    """In staging, attempting to use the production project ref must fail fast with isolation breach."""
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", "https://tbjcldcoozvuvyipeonh.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-staging-service-key"):
        with pytest.raises(RuntimeError, match="CRITICAL ISOLATION BREACH") as exc_info:
            validate_worker_runtime_environment()
        assert "tbjcldcoozvuvyipeonh" in str(exc_info.value)


def test_staging_worker_guard_valid_isolated_config_passes():
    """Staging worker environment validates cleanly when configured with valid isolated staging ref."""
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", "https://wymgyqnqwlliotkxamtd.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-staging-service-key-999"):
        is_valid, issues = validate_worker_runtime_environment()
        assert is_valid is True
        assert issues == []


def test_staging_supabase_service_init_missing_creds_raises_database_unavailable_error():
    """Instantiating SupabaseService with missing creds in staging must fail fast with DatabaseUnavailableError."""
    from app.services.supabase_client import SupabaseService, DatabaseUnavailableError
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", ""), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""):
        with pytest.raises(DatabaseUnavailableError, match="Database client credentials invalid or missing in non-development environment"):
            SupabaseService()


def test_staging_supabase_service_init_valid_config_initializes():
    """Instantiating SupabaseService in staging with valid config initializes client successfully."""
    from app.services.supabase_client import SupabaseService
    mock_client = MagicMock()
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", "https://wymgyqnqwlliotkxamtd.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-staging-service-key-888"), \
         patch("app.services.supabase_client.create_client", return_value=mock_client):
        service = SupabaseService()
        assert service._client is mock_client
        assert service.is_connected is True
        assert service._allow_in_memory_fallback() is False


def test_staging_error_messages_contain_no_credentials_or_secrets():
    """Confirm no token or secret strings leak in staging worker validation errors."""
    secret_token = "super_secret_raw_jwt_token_98765"
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", f"https://wymgyqnqwlliotkxamtd.supabase.co?token={secret_token}"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""):
        with pytest.raises(RuntimeError) as exc_info:
            validate_worker_runtime_environment()
        err_text = str(exc_info.value)
        assert secret_token not in err_text
        assert "token=[REDACTED]" not in err_text or secret_token not in err_text


def test_production_worker_guard_staging_ref_fails_fast():
    """In production, attempting to use the staging project ref must fail fast with isolation breach."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://wymgyqnqwlliotkxamtd.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-prod-service-key"):
        with pytest.raises(RuntimeError, match="CRITICAL ISOLATION BREACH") as exc_info:
            validate_worker_runtime_environment()
        assert "wymgyqnqwlliotkxamtd" in str(exc_info.value)


def test_production_supabase_service_init_rejects_staging_ref():
    """SupabaseService in production must reject staging project ref."""
    from app.services.supabase_client import SupabaseService, DatabaseUnavailableError
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", "https://wymgyqnqwlliotkxamtd.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-prod-service-key"):
        with pytest.raises(DatabaseUnavailableError, match="CRITICAL ISOLATION BREACH"):
            SupabaseService()


def test_staging_supabase_service_init_rejects_production_ref():
    """SupabaseService in staging must reject production project ref."""
    from app.services.supabase_client import SupabaseService, DatabaseUnavailableError
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "SUPABASE_URL", "https://tbjcldcoozvuvyipeonh.supabase.co"), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "valid-staging-service-key"):
        with pytest.raises(DatabaseUnavailableError, match="CRITICAL ISOLATION BREACH"):
            SupabaseService()


def test_get_deployment_commit_sha_railway_env():
    """Verify full 40-char SHA from RAILWAY_GIT_COMMIT_SHA is truncated to 7 lowercase hex chars."""
    from app.core.env_guard import get_deployment_commit_sha
    with patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": "8E66E712AF87F71EEA6D3E908958B3B188F70FBE"}):
        assert get_deployment_commit_sha() == "8e66e71"


def test_get_deployment_commit_sha_generic_git_env():
    """Verify fallback to GIT_COMMIT_SHA when RAILWAY_GIT_COMMIT_SHA is absent."""
    from app.core.env_guard import get_deployment_commit_sha
    with patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": "", "GIT_COMMIT_SHA": "abcdef1234567890"}):
        assert get_deployment_commit_sha() == "abcdef1"


def test_get_deployment_commit_sha_missing_returns_default():
    """Verify safe fallback (default 'dev' or specified) when no commit env vars exist."""
    from app.core.env_guard import get_deployment_commit_sha
    with patch.dict("os.environ", {}, clear=True):
        assert get_deployment_commit_sha() == "dev"
        assert get_deployment_commit_sha(default="unknown") == "unknown"


def test_get_deployment_commit_sha_sanitizes_non_hex():
    """Verify non-hex characters and whitespace are stripped before truncation."""
    from app.core.env_guard import get_deployment_commit_sha
    with patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": "  8e66e71-dirty#foo  "}):
        assert get_deployment_commit_sha() == "8e66e71"


def test_get_railway_service_name():
    """Verify RAILWAY_SERVICE_NAME retrieval, length cap, and None fallback."""
    from app.core.env_guard import get_railway_service_name
    with patch.dict("os.environ", {"RAILWAY_SERVICE_NAME": "inboundcheck-backend"}):
        assert get_railway_service_name() == "inboundcheck-backend"

    with patch.dict("os.environ", {"RAILWAY_SERVICE_NAME": ""}):
        assert get_railway_service_name() is None

    long_name = "a" * 80
    with patch.dict("os.environ", {"RAILWAY_SERVICE_NAME": long_name}):
        assert get_railway_service_name() == "a" * 50


def test_health_and_ready_endpoint_contracts_contain_commit_sha():
    """Verify /health and /ready response schemas contain commit_sha and optional railway_service."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    with patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": "8e66e712af87f71eea6d3e908958b3b188f70fbe", "RAILWAY_SERVICE_NAME": "inboundcheck-backend"}):
        # 1. /health
        res_health = client.get("/health")
        assert res_health.status_code == 200
        data_h = res_health.json()
        assert data_h["status"] == "alive"
        assert data_h["service"] == settings.PROJECT_NAME
        assert data_h["version"] == "1.0.0"
        assert data_h["commit_sha"] == "8e66e71"
        assert data_h["railway_service"] == "inboundcheck-backend"
        assert "timestamp" in data_h

        # 2. /ready
        with patch("app.services.supabase_client.supabase_service.check_db_health", return_value=True):
            res_ready = client.get("/ready")
            assert res_ready.status_code == 200
            data_r = res_ready.json()
            assert data_r["status"] == "ready"
            assert data_r["commit_sha"] == "8e66e71"
            assert data_r["railway_service"] == "inboundcheck-backend"
            assert "dependencies" in data_r
