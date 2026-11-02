"""
InboundCheck - Comprehensive Settings & Alert Credential Security Tests (Group 45B.2)
====================================================================================
Verifies production mock fallback elimination, Fernet credential encryption,
tenant isolation, and fail-closed database reliability:
1. Production database failure returns HTTP 503.
2. Staging database failure returns HTTP 503.
3. Development fallback only when explicitly allowed.
4. No mock profile returned in Production.
5. No mock alert configuration returned in Production.
6. Telegram token encrypted before persistence.
7. Slack webhook encrypted before persistence.
8. GET endpoints never expose plaintext secrets.
9. Existing secrets remain unchanged when omitted from updates.
10. Invalid encrypted credentials fail safely.
11. Cross-tenant credential access is rejected.
12. Existing settings and failover functionality remains compatible.
"""

import sys
import os
import time
import base64
import hashlib
from typing import Dict, Any, Optional
from unittest.mock import patch, MagicMock

# Ensure backend directory is in python path
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Mock third-party dependencies if not installed globally in sandbox runtime
if "cryptography" not in sys.modules:
    class MockInvalidToken(Exception):
        pass

    class MockFernet:
        def __init__(self, key):
            self.key = key

        def encrypt(self, data: bytes) -> bytes:
            encoded = base64.urlsafe_b64encode(b"simulated_fernet:" + data)
            return encoded

        def decrypt(self, token: bytes) -> bytes:
            try:
                decoded = base64.urlsafe_b64decode(token)
                if not decoded.startswith(b"simulated_fernet:"):
                    raise MockInvalidToken("Invalid token prefix")
                return decoded[len(b"simulated_fernet:"):]
            except Exception as e:
                raise MockInvalidToken(str(e))

    mock_crypto = MagicMock()
    mock_fernet_mod = MagicMock()
    mock_fernet_mod.Fernet = MockFernet
    mock_fernet_mod.InvalidToken = MockInvalidToken
    sys.modules["cryptography"] = mock_crypto
    sys.modules["cryptography.fernet"] = mock_fernet_mod

if "fastapi" not in sys.modules:
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: Any = None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"HTTPException(status_code={status_code}, detail={detail})")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass
        def get(self, *args, **kwargs):
            def decorator(fn): return fn
            return decorator
        def post(self, *args, **kwargs):
            def decorator(fn): return fn
            return decorator
        def put(self, *args, **kwargs):
            def decorator(fn): return fn
            return decorator

    class Status:
        HTTP_200_OK = 200
        HTTP_400_BAD_REQUEST = 400
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403
        HTTP_404_NOT_FOUND = 404
        HTTP_500_INTERNAL_SERVER_ERROR = 500
        HTTP_503_SERVICE_UNAVAILABLE = 503

    def Depends(fn=None):
        return fn

    fastapi_mock = MagicMock()
    fastapi_mock.HTTPException = HTTPException
    fastapi_mock.APIRouter = APIRouter
    fastapi_mock.status = Status
    fastapi_mock.Depends = Depends
    sys.modules["fastapi"] = fastapi_mock

if "pydantic" not in sys.modules:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self, *args, **kwargs):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        def dict(self, *args, **kwargs):
            return self.model_dump()

    def Field(default=None, **kwargs):
        return default

    pydantic_mock = MagicMock()
    pydantic_mock.BaseModel = BaseModel
    pydantic_mock.Field = Field
    sys.modules["pydantic"] = pydantic_mock

if "pydantic_settings" not in sys.modules:
    class BaseSettings:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    class SettingsConfigDict(dict):
        pass
    pyd_set_mock = MagicMock()
    pyd_set_mock.BaseSettings = BaseSettings
    pyd_set_mock.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = pyd_set_mock

if "supabase" not in sys.modules:
    sys.modules["supabase"] = MagicMock()
if "httpx" not in sys.modules:
    sys.modules["httpx"] = MagicMock()
if "jwt" not in sys.modules:
    sys.modules["jwt"] = MagicMock()
if "dns" not in sys.modules:
    dns_mock = MagicMock()
    dns_mock.__path__ = []
    sys.modules["dns"] = dns_mock
    sys.modules["dns.asyncresolver"] = MagicMock()
    sys.modules["dns.resolver"] = MagicMock()
    sys.modules["dns.name"] = MagicMock()
    sys.modules["dns.exception"] = MagicMock()
    sys.modules["dns.rdatatype"] = MagicMock()
if "starlette" not in sys.modules:
    sys.modules["starlette"] = MagicMock()
    sys.modules["starlette.requests"] = MagicMock()
    sys.modules["starlette.responses"] = MagicMock()

# Import application components
from app.core.config import settings
from app.core.encryption import (
    encrypt_credential,
    decrypt_credential,
    mask_credential,
    safe_decrypt_credential,
    DecryptionError,
)
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.failover.omnichannel_service import omnichannel_service
import importlib.util

def load_module_from_file(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

settings_api = load_module_from_file("app.api.v1.settings", str(REPO_ROOT / "backend" / "app" / "api" / "v1" / "settings.py"))
failover_api = load_module_from_file("app.api.v1.failover", str(REPO_ROOT / "backend" / "app" / "api" / "v1" / "failover.py"))
HTTPException = sys.modules["fastapi"].HTTPException


def test_production_database_failure_returns_http_503():
    """1. Production database failure returns HTTP 503 across all settings endpoints."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "STAGING_MODE", False), \
         patch.object(supabase_service, "_client", None):

        # Profile GET
        try:
            import asyncio
            asyncio.run(settings_api.get_user_profile(user_id="prod-user-1"))
            assert False, "Expected HTTP 503 on profile GET"
        except HTTPException as e:
            assert e.status_code == 503
            assert "temporarily unavailable" in e.detail

        # Profile PUT
        try:
            req = settings_api.UpdateProfileRequest(
                full_name="Prod Name",
                email="prod@store.com",
                company_name="Prod Corp"
            )
            asyncio.run(settings_api.update_user_profile(payload=req, user_id="prod-user-1"))
            assert False, "Expected HTTP 503 on profile PUT"
        except HTTPException as e:
            assert e.status_code == 503

        # API Key Regenerate
        try:
            asyncio.run(settings_api.regenerate_api_key(user_id="prod-user-1"))
            assert False, "Expected HTTP 503 on API key regenerate"
        except HTTPException as e:
            assert e.status_code == 503

        # Alert Config GET
        try:
            asyncio.run(settings_api.get_alert_config(user_id="prod-user-1"))
            assert False, "Expected HTTP 503 on alerts GET"
        except HTTPException as e:
            assert e.status_code == 503

        # Alert Config POST
        try:
            alert_req = settings_api.AlertConfigRequest(score_threshold=80)
            asyncio.run(settings_api.save_alert_config(payload=alert_req, user_id="prod-user-1"))
            assert False, "Expected HTTP 503 on alerts POST"
        except HTTPException as e:
            assert e.status_code == 503

        # Failover Config GET
        try:
            asyncio.run(failover_api.get_failover_config(user_id="prod-user-1"))
            assert False, "Expected HTTP 503 on failover GET"
        except HTTPException as e:
            assert e.status_code == 503


def test_staging_database_failure_returns_http_503():
    """2. Staging database failure returns HTTP 503 across settings endpoints."""
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "STAGING_MODE", True), \
         patch.object(supabase_service, "_client", None):

        import asyncio
        # Profile GET
        try:
            asyncio.run(settings_api.get_user_profile(user_id="staging-user-1"))
            assert False, "Expected HTTP 503 on staging profile GET"
        except HTTPException as e:
            assert e.status_code == 503

        # Alert Config GET
        try:
            asyncio.run(settings_api.get_alert_config(user_id="staging-user-1"))
            assert False, "Expected HTTP 503 on staging alerts GET"
        except HTTPException as e:
            assert e.status_code == 503


def test_development_fallback_only_when_explicitly_allowed():
    """3. Development fallback only when explicitly allowed."""
    # Development allowed
    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):
        assert supabase_service._allow_in_memory_fallback() is True

    # Test environment allowed
    with patch.object(settings, "ENVIRONMENT", "test"), \
         patch.object(settings, "STAGING_MODE", False):
        assert supabase_service._allow_in_memory_fallback() is True

    # Production strictly forbidden
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "STAGING_MODE", False):
        assert supabase_service._allow_in_memory_fallback() is False

    # Staging strictly forbidden
    with patch.object(settings, "ENVIRONMENT", "staging"), \
         patch.object(settings, "STAGING_MODE", False):
        assert supabase_service._allow_in_memory_fallback() is False

    # STAGING_MODE=True strictly forbidden even in development
    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", True):
        assert supabase_service._allow_in_memory_fallback() is False


def test_no_mock_profile_returned_in_production():
    """4. No mock profile ('Alex Morgan') returned in Production."""
    import asyncio
    mock_client = MagicMock()
    mock_select = MagicMock()
    mock_select.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_client.table.return_value.select.return_value = mock_select

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "STAGING_MODE", False), \
         patch.object(supabase_service, "_client", mock_client):

        try:
            asyncio.run(settings_api.get_user_profile(user_id="prod-unknown-user"))
            assert False, "Expected HTTP 404 for non-existent profile in production"
        except HTTPException as e:
            assert e.status_code == 404
            assert "not found" in e.detail.lower()


def test_no_mock_alert_configuration_returned_in_production():
    """5. No mock alert configuration ('7198234891:AAH8Fj90qWz1x9_example') returned in Production."""
    import asyncio
    mock_client = MagicMock()
    mock_select = MagicMock()
    mock_select.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_client.table.return_value.select.return_value = mock_select

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "STAGING_MODE", False), \
         patch.object(supabase_service, "_client", mock_client):

        res = asyncio.run(settings_api.get_alert_config(user_id="prod-tenant-new"))
        assert res["success"] is True
        config = res["config"]
        # Must be clean default without mock tokens
        assert config["telegram_bot_token"] is None
        assert config["telegram_bot_token_configured"] is False
        assert config["slack_webhook_url"] is None
        assert config["slack_webhook_url_configured"] is False
        assert "7198234891" not in str(config)


def test_telegram_token_encrypted_before_persistence():
    """6. Telegram token encrypted before persistence."""
    import asyncio
    raw_token = "7198234891:AAH8Fj90qWz1x9_live_token_12345"

    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):

        alert_req = settings_api.AlertConfigRequest(
            telegram_bot_token=raw_token,
            telegram_chat_id="@my_alerts"
        )
        res = asyncio.run(settings_api.save_alert_config(payload=alert_req, user_id="tenant-encrypt-tg"))
        assert res["success"] is True

        # Check raw stored config in supabase_service
        stored = supabase_service.get_alert_config("tenant-encrypt-tg")
        assert stored is not None
        stored_token = stored.get("telegram_bot_token")

        # Stored token must start with version prefix 'v1:' and never equal raw token
        assert stored_token.startswith("v1:")
        assert stored_token != raw_token
        assert raw_token not in stored_token

        # Decrypting stored token recovers original plaintext
        decrypted = safe_decrypt_credential(stored_token)
        assert decrypted == raw_token


def test_slack_webhook_encrypted_before_persistence():
    """7. Slack webhook encrypted before persistence."""
    import asyncio
    raw_webhook = "https://hooks.slack.com/services/T0123/B4567/secret89012"

    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):

        alert_req = settings_api.AlertConfigRequest(
            slack_webhook_url=raw_webhook,
            score_threshold=82
        )
        res = asyncio.run(settings_api.save_alert_config(payload=alert_req, user_id="tenant-encrypt-slack"))
        assert res["success"] is True

        stored = supabase_service.get_alert_config("tenant-encrypt-slack")
        assert stored is not None
        stored_webhook = stored.get("slack_webhook_url")

        # Must be encrypted with 'v1:' prefix
        assert stored_webhook.startswith("v1:")
        assert stored_webhook != raw_webhook
        assert "secret89012" not in stored_webhook

        # Decryption recovers exact webhook URL
        decrypted = safe_decrypt_credential(stored_webhook)
        assert decrypted == raw_webhook


def test_get_endpoints_never_expose_plaintext_secrets():
    """8. GET endpoints never expose plaintext secrets or raw ciphertext."""
    import asyncio
    raw_tg = "7198234891:AAH8Fj90qWz1x9_secret_token"
    raw_slack = "https://hooks.slack.com/services/T11/B22/SUPER_SECRET_HOOK"

    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):

        # Save credentials
        alert_req = settings_api.AlertConfigRequest(
            telegram_bot_token=raw_tg,
            slack_webhook_url=raw_slack
        )
        asyncio.run(settings_api.save_alert_config(payload=alert_req, user_id="tenant-mask-check"))

        # 1. GET /api/v1/settings/alerts
        alerts_res = asyncio.run(settings_api.get_alert_config(user_id="tenant-mask-check"))
        alert_cfg = alerts_res["config"]

        # Plaintext must not be exposed
        assert raw_tg not in alert_cfg["telegram_bot_token"]
        assert raw_slack not in alert_cfg["slack_webhook_url"]
        # Raw ciphertext must not be exposed
        assert not alert_cfg["telegram_bot_token"].startswith("v1:")
        assert not alert_cfg["slack_webhook_url"].startswith("v1:")
        # Masked indicators present
        assert alert_cfg["telegram_bot_token"].startswith("••••")
        assert alert_cfg["telegram_bot_token"].endswith(raw_tg[-4:])
        assert alert_cfg["slack_webhook_url"].startswith("••••")
        assert alert_cfg["slack_webhook_url"].endswith(raw_slack[-4:])
        assert alert_cfg["telegram_bot_token_configured"] is True
        assert alert_cfg["slack_webhook_url_configured"] is True

        # 2. GET /api/v1/failover/config
        failover_res = asyncio.run(failover_api.get_failover_config(user_id="tenant-mask-check"))
        f_cfg = failover_res["config"]
        assert raw_tg not in f_cfg["telegram_bot_token"]
        assert f_cfg["telegram_bot_token"].startswith("••••")
        assert f_cfg["telegram_bot_token_configured"] is True


def test_existing_secrets_remain_unchanged_when_omitted():
    """9. Existing secrets remain unchanged when omitted from updates."""
    import asyncio
    raw_tg = "12345:TOKEN_ORIGINAL_SECRET"
    raw_slack = "https://hooks.slack.com/services/ORIGINAL_SLACK"

    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):

        # Initial save with secrets
        req1 = settings_api.AlertConfigRequest(
            telegram_bot_token=raw_tg,
            slack_webhook_url=raw_slack,
            score_threshold=75
        )
        asyncio.run(settings_api.save_alert_config(payload=req1, user_id="tenant-preserve"))

        # Second update omitting secrets (telegram_bot_token=None, slack_webhook_url=None)
        req2 = settings_api.AlertConfigRequest(
            score_threshold=90,
            telegram_bot_token=None,
            slack_webhook_url=None
        )
        res2 = asyncio.run(settings_api.save_alert_config(payload=req2, user_id="tenant-preserve"))
        assert res2["config"]["score_threshold"] == 90

        # Verify underlying stored credentials were NOT wiped
        stored = supabase_service.get_alert_config("tenant-preserve")
        assert stored is not None
        assert safe_decrypt_credential(stored["telegram_bot_token"]) == raw_tg
        assert safe_decrypt_credential(stored["slack_webhook_url"]) == raw_slack

        # Third update sending masked placeholder (as frontend would on form resubmit)
        req3 = settings_api.AlertConfigRequest(
            score_threshold=85,
            telegram_bot_token="••••••••••••CRET",
            slack_webhook_url="••••••••••••LACK"
        )
        res3 = asyncio.run(settings_api.save_alert_config(payload=req3, user_id="tenant-preserve"))
        assert res3["config"]["score_threshold"] == 85

        stored3 = supabase_service.get_alert_config("tenant-preserve")
        assert safe_decrypt_credential(stored3["telegram_bot_token"]) == raw_tg
        assert safe_decrypt_credential(stored3["slack_webhook_url"]) == raw_slack


def test_invalid_encrypted_credentials_fail_safely():
    """10. Invalid or corrupted encrypted credentials fail safely."""
    # 1. Corrupted ciphertext prefix
    corrupted = "v1:garbage_ciphertext_that_cannot_be_decrypted"
    decrypted = safe_decrypt_credential(corrupted)
    assert decrypted is None

    # 2. Legacy plaintext passthrough
    legacy = "legacy_unencrypted_bot_token_123"
    assert safe_decrypt_credential(legacy) == legacy

    # 3. None or empty string
    assert safe_decrypt_credential(None) is None
    assert safe_decrypt_credential("") is None

    # 4. GET formatting with corrupted stored token
    corrupted_config = {
        "user_id": "corrupted-user",
        "telegram_bot_token": corrupted,
        "slack_webhook_url": corrupted,
    }
    formatted = settings_api._format_alert_config_response(corrupted_config)
    assert formatted["telegram_bot_token"] == "••••••••••••"
    assert formatted["telegram_bot_token_configured"] is True
    assert formatted["slack_webhook_url"] == "••••••••••••"
    assert formatted["slack_webhook_url_configured"] is True


def test_cross_tenant_credential_access_rejected():
    """11. Cross-tenant credential access is strictly rejected."""
    import asyncio
    tenant_a_token = "11111:TENANT_A_SECRET"
    tenant_b_token = "22222:TENANT_B_SECRET"

    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):

        # Save Tenant A credentials
        asyncio.run(settings_api.save_alert_config(
            payload=settings_api.AlertConfigRequest(telegram_bot_token=tenant_a_token),
            user_id="tenant-A"
        ))

        # Tenant B queries alerts
        b_alerts = asyncio.run(settings_api.get_alert_config(user_id="tenant-B"))
        b_cfg = b_alerts["config"]

        # Tenant B must NOT see Tenant A's token
        assert b_cfg["telegram_bot_token"] is None
        assert b_cfg["telegram_bot_token_configured"] is False

        # Tenant B queries failover config
        b_failover = asyncio.run(failover_api.get_failover_config(user_id="tenant-B"))
        b_f_cfg = b_failover["config"]
        assert b_f_cfg["telegram_bot_token"] is None

        # Omnichannel decrypted token for Tenant B must be None
        assert omnichannel_service.get_decrypted_token("tenant-B") is None
        assert omnichannel_service.get_decrypted_token("tenant-A") == tenant_a_token


def test_existing_settings_and_failover_functionality_compatible():
    """12. Existing settings and failover functionality remains compatible."""
    import asyncio
    user_id = "test-compat-user"

    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False):

        # Profile update
        prof_res = asyncio.run(settings_api.update_user_profile(
            payload=settings_api.UpdateProfileRequest(
                full_name="Alex Updated",
                email="alex.up@store.com",
                company_name="Updated Corp"
            ),
            user_id=user_id
        ))
        assert prof_res["success"] is True
        assert prof_res["profile"]["full_name"] == "Alex Updated"
        assert prof_res["profile"]["email"] == "alex.up@store.com"
        assert prof_res["profile"]["api_key"].startswith("ic_live_••••")

        # Key regenerate
        key_res = asyncio.run(settings_api.regenerate_api_key(user_id=user_id))
        assert key_res["success"] is True
        assert key_res["api_key"].startswith("ic_live_••••")

        # Alert config PUT
        put_alert_res = asyncio.run(settings_api.save_alert_config(
            payload=settings_api.AlertConfigRequest(
                score_threshold=88,
                alert_on_score_drop=True,
                telegram_chat_id="@mychat"
            ),
            user_id=user_id
        ))
        assert put_alert_res["success"] is True
        assert put_alert_res["config"]["score_threshold"] == 88

        # Failover logs endpoint
        logs_res = asyncio.run(failover_api.get_failover_logs(limit=10, offset=0, user_id=user_id))
        assert logs_res["success"] is True
        assert isinstance(logs_res["logs"], list)


if __name__ == "__main__":
    print("=" * 70)
    print("Running Group 45B.2 Settings & Alert Security Test Suite...")
    print("=" * 70)

    tests = [
        ("1. Production database failure returns HTTP 503", test_production_database_failure_returns_http_503),
        ("2. Staging database failure returns HTTP 503", test_staging_database_failure_returns_http_503),
        ("3. Development fallback only when explicitly allowed", test_development_fallback_only_when_explicitly_allowed),
        ("4. No mock profile returned in Production", test_no_mock_profile_returned_in_production),
        ("5. No mock alert configuration returned in Production", test_no_mock_alert_configuration_returned_in_production),
        ("6. Telegram token encrypted before persistence", test_telegram_token_encrypted_before_persistence),
        ("7. Slack webhook encrypted before persistence", test_slack_webhook_encrypted_before_persistence),
        ("8. GET endpoints never expose plaintext secrets", test_get_endpoints_never_expose_plaintext_secrets),
        ("9. Existing secrets remain unchanged when omitted from updates", test_existing_secrets_remain_unchanged_when_omitted),
        ("10. Invalid encrypted credentials fail safely", test_invalid_encrypted_credentials_fail_safely),
        ("11. Cross-tenant credential access is rejected", test_cross_tenant_credential_access_rejected),
        ("12. Existing settings and failover functionality remains compatible", test_existing_settings_and_failover_functionality_compatible),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed.")
    print("=" * 70)
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
