"""
InboundCheck - Comprehensive Telegram Client Hardening, Tenant Isolation & Zero-PII Tests (Group 45B.3A)
========================================================================================================
Verifies:
1. test_telegram_dispatch_fails_closed_when_tenant_unconfigured
2. test_telegram_dispatch_never_uses_global_credentials
3. test_telegram_rate_limit_429_respects_retry_after
4. test_telegram_429_retry_budget_is_bounded
5. test_telegram_transient_5xx_exponential_backoff
6. test_telegram_timeout_retry_is_bounded
7. test_telegram_permanent_errors_are_not_retried
8. test_telegram_synchronous_dispatch_zero_pii
9. test_telegram_logs_do_not_expose_credentials_or_pii
10. test_existing_worker_dispatch_compatibility
"""

import sys
import os
import asyncio
import json
import base64
from typing import Dict, Any, Optional
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Add backend directory to sys.path
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
        if callable(default):
            return default()
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
if "jwt" not in sys.modules:
    sys.modules["jwt"] = MagicMock()
if "dns" not in sys.modules:
    dns_mock = MagicMock()
    dns_mock.__path__ = []
    sys.modules["dns"] = dns_mock

if "httpx" not in sys.modules:
    class TimeoutException(Exception): pass
    class ReadTimeout(TimeoutException): pass
    class ConnectTimeout(TimeoutException): pass
    class NetworkError(Exception): pass
    class ConnectError(NetworkError): pass
    class AsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): pass

    httpx_mock = MagicMock()
    httpx_mock.TimeoutException = TimeoutException
    httpx_mock.ReadTimeout = ReadTimeout
    httpx_mock.ConnectTimeout = ConnectTimeout
    httpx_mock.NetworkError = NetworkError
    httpx_mock.ConnectError = ConnectError
    httpx_mock.AsyncClient = AsyncClient
    sys.modules["httpx"] = httpx_mock
else:
    import httpx

from app.core.config import settings
from app.services.failover.omnichannel_service import (
    omnichannel_service,
    telegram_alert_service,
    TelegramAlertService,
    TelegramIncidentContext,
    TelegramDispatchResult,
    MAX_TELEGRAM_ATTEMPTS,
    MAX_SYNCHRONOUS_RETRY_DELAY_SECONDS,
    MAX_TOTAL_RETRY_BUDGET_SECONDS,
    sanitize_log_message,
)
from app.services.supabase_client import supabase_service


class MockHttpResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or (json.dumps(json_data) if json_data else "")

    def json(self):
        return self._json_data


# ==============================================================================
# TEST 1: Unconfigured tenant fails closed
# ==============================================================================
def test_telegram_dispatch_fails_closed_when_tenant_unconfigured():
    """Verify dispatch fails closed cleanly when tenant has no Telegram credentials configured."""
    unconf_user = "user-unconfigured-zero-creds"
    omnichannel_service._mock_mode = False

    # Ensure config has no token and no chat_id
    omnichannel_service.update_config(unconf_user, {
        "is_enabled": True,
        "telegram_bot_token": None,
        "telegram_chat_id": None,
    })

    # 1. Test dispatch_alert path
    ctx = TelegramIncidentContext(
        delivery_failure_event_id="evt-unconf-001",
        user_id=unconf_user,
        order_id="ORD-101",
        domain_name="store.com",
        store_name="Store",
        esp_provider="sendgrid",
        failure_type="bounce",
        failure_reason="Mailbox unavailable",
    )

    dispatch_res = asyncio.run(omnichannel_service.dispatch_alert(ctx))
    assert dispatch_res.success is False
    assert dispatch_res.provider_status == "failed"
    assert "explicitly configured" in dispatch_res.error_message

    # 2. Test trigger_failover_dispatch path
    sync_res = asyncio.run(omnichannel_service.trigger_failover_dispatch(
        user_id=unconf_user,
        order_id="ORD-101",
    ))
    assert sync_res["dispatched"] is False
    assert "explicitly configured" in sync_res["error"]


# ==============================================================================
# TEST 2: Never uses global platform credentials
# ==============================================================================
def test_telegram_dispatch_never_uses_global_credentials():
    """Verify unconfigured tenant NEVER inherits settings.TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID."""
    unconf_user = "user-unconfigured-global-leak-check"
    omnichannel_service._mock_mode = False

    omnichannel_service.update_config(unconf_user, {
        "is_enabled": True,
        "telegram_bot_token": None,
        "telegram_chat_id": None,
    })

    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "8888888888:AAHGlobalBotTokenThatMustNeverLeak"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-1008888888888"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        # Direct send_telegram_alert with empty credentials
        direct_res = asyncio.run(omnichannel_service.send_telegram_alert(
            bot_token="",
            chat_id="",
            text="Intrusion check",
        ))
        assert direct_res["success"] is False
        assert "explicitly configured" in direct_res["error"]
        mock_post.assert_not_called()

        # Trigger failover dispatch for unconfigured tenant
        sync_res = asyncio.run(omnichannel_service.trigger_failover_dispatch(
            user_id=unconf_user,
            order_id="ORD-INTRUSION-1",
        ))
        assert sync_res["dispatched"] is False
        mock_post.assert_not_called()


# ==============================================================================
# TEST 3: Rate limit HTTP 429 respects retry_after
# ==============================================================================
def test_telegram_rate_limit_429_respects_retry_after():
    """Verify HTTP 429 with valid retry_after is respected and succeeds on retry."""
    omnichannel_service._mock_mode = False
    bot_token = "1234567890:AAHTestToken429ValidRetry123"
    chat_id = "-100123456789"

    resp_429 = MockHttpResponse(
        status_code=429,
        json_data={
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after 1",
            "parameters": {"retry_after": 1},
        },
    )
    resp_200 = MockHttpResponse(
        status_code=200,
        json_data={"ok": True, "result": {"message_id": 42911}},
    )

    slept_durations = []

    async def mock_sleep(seconds):
        slept_durations.append(seconds)

    with patch("httpx.AsyncClient.post", side_effect=[resp_429, resp_200]) as mock_post, \
         patch("asyncio.sleep", side_effect=mock_sleep):

        res = asyncio.run(omnichannel_service.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text="Rate limit test message",
        ))

        assert res["success"] is True
        assert res["data"]["result"]["message_id"] == 42911
        assert mock_post.call_count == 2
        assert len(slept_durations) == 1
        assert slept_durations[0] == 1.0


# ==============================================================================
# TEST 4: 429 retry budget is bounded
# ==============================================================================
def test_telegram_429_retry_budget_is_bounded():
    """Verify HTTP 429 exceeding synchronous delay threshold aborts immediately without sleeping."""
    omnichannel_service._mock_mode = False
    bot_token = "1234567890:AAHTestToken429LargeDelay123"
    chat_id = "-100123456789"

    # Excessive retry_after = 60s
    resp_429_excessive = MockHttpResponse(
        status_code=429,
        json_data={
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after 60",
            "parameters": {"retry_after": 60},
        },
    )

    slept_durations = []

    async def mock_sleep(seconds):
        slept_durations.append(seconds)

    with patch("httpx.AsyncClient.post", side_effect=[resp_429_excessive]) as mock_post, \
         patch("asyncio.sleep", side_effect=mock_sleep):

        res = asyncio.run(omnichannel_service.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text="Large backoff test",
        ))

        assert res["success"] is False
        assert res["status_code"] == 429
        assert res["retryable"] is True
        assert res["retry_after"] == 60
        assert "exceeds synchronous retry budget" in res["error"]
        assert len(slept_durations) == 0  # Did not perform a long blocking sleep!
        assert mock_post.call_count == 1


# ==============================================================================
# TEST 5: Transient 5xx exponential backoff
# ==============================================================================
def test_telegram_transient_5xx_exponential_backoff():
    """Verify HTTP 502/503 errors trigger exponential backoff with jitter and recover."""
    omnichannel_service._mock_mode = False
    bot_token = "1234567890:AAHTestToken5xxBackoff12345"
    chat_id = "-100123456789"

    resp_503 = MockHttpResponse(status_code=503, text="Service Unavailable Gateway")
    resp_502 = MockHttpResponse(status_code=502, text="Bad Gateway")
    resp_200 = MockHttpResponse(status_code=200, json_data={"result": {"message_id": 555}})

    slept_durations = []

    async def mock_sleep(seconds):
        slept_durations.append(seconds)

    with patch("httpx.AsyncClient.post", side_effect=[resp_503, resp_502, resp_200]) as mock_post, \
         patch("asyncio.sleep", side_effect=mock_sleep):

        res = asyncio.run(omnichannel_service.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text="Server transient retry test",
        ))

        assert res["success"] is True
        assert res["data"]["result"]["message_id"] == 555
        assert mock_post.call_count == 3
        assert len(slept_durations) == 2
        # Backoff attempt 1: base ~0.5s, attempt 2: base ~1.0s
        assert slept_durations[0] >= 0.5
        assert slept_durations[1] >= 1.0


# ==============================================================================
# TEST 6: Timeout retry is bounded
# ==============================================================================
def test_telegram_timeout_retry_is_bounded():
    """Verify network timeouts retry up to MAX_TELEGRAM_ATTEMPTS (3) and fail closed."""
    import sys
    httpx_mod = sys.modules.get("httpx")
    timeout_exc = getattr(httpx_mod, "ReadTimeout", Exception)

    omnichannel_service._mock_mode = False
    bot_token = "1234567890:AAHTestTokenTimeoutBounded12"
    chat_id = "-100123456789"

    slept_durations = []

    async def mock_sleep(seconds):
        slept_durations.append(seconds)

    with patch("httpx.AsyncClient.post", side_effect=timeout_exc("Timed out reading data")) as mock_post, \
         patch("asyncio.sleep", side_effect=mock_sleep):

        res = asyncio.run(omnichannel_service.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text="Timeout bounded test",
        ))

        assert res["success"] is False
        assert res["retryable"] is True
        assert "Telegram network error" in res["error"]
        assert mock_post.call_count == MAX_TELEGRAM_ATTEMPTS
        assert len(slept_durations) == (MAX_TELEGRAM_ATTEMPTS - 1)


# ==============================================================================
# TEST 7: Permanent errors are not retried
# ==============================================================================
def test_telegram_permanent_errors_are_not_retried():
    """Verify permanent 4xx errors (400, 401, 403, 404) are NOT retried."""
    omnichannel_service._mock_mode = False
    bot_token = "1234567890:AAHTestTokenPermErrors12345"
    chat_id = "-100123456789"

    for code in [400, 401, 403, 404]:
        resp_perm = MockHttpResponse(
            status_code=code,
            json_data={"ok": False, "error_code": code, "description": f"Permanent error {code}"},
        )

        with patch("httpx.AsyncClient.post", side_effect=[resp_perm]) as mock_post, \
             patch("asyncio.sleep") as mock_sleep:

            res = asyncio.run(omnichannel_service.send_telegram_alert(
                bot_token=bot_token,
                chat_id=chat_id,
                text="Permanent error test",
            ))

            assert res["success"] is False
            assert res["status_code"] == code
            assert res["retryable"] is False
            assert f"Telegram API error ({code})" in res["error"]
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()


# ==============================================================================
# TEST 8: Synchronous dispatch zero PII
# ==============================================================================
def test_telegram_synchronous_dispatch_zero_pii():
    """Verify trigger_failover_dispatch completely excludes customer email and phone from alert text."""
    user_id = "user-pii-scrub-test-777"
    omnichannel_service._mock_mode = False

    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "1234567890:AAHValidTokenForPIITest123456",
        "telegram_chat_id": "-1009988776655",
    })

    synthetic_email = "shopper.victim.999@private-domain.org"
    synthetic_phone = "+1 (555) 987-6543"
    order_id = "ORD-TEST-9988"
    store_name = "Luxury Streetwear DTC"
    domain_name = "luxurystreetwear.com"

    posted_payloads = []

    async def mock_post(url, **kwargs):
        posted_payloads.append(kwargs.get("json", {}))
        return MockHttpResponse(200, {"ok": True, "result": {"message_id": 9988}})

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        res = asyncio.run(omnichannel_service.trigger_failover_dispatch(
            user_id=user_id,
            order_id=order_id,
            customer_phone=synthetic_phone,
            customer_email=synthetic_email,
            trigger_reason="hard_bounce",
            domain_name=domain_name,
            store_name=store_name,
        ))

        assert res["dispatched"] is True
        assert len(posted_payloads) == 1
        dispatched_text = posted_payloads[0].get("text", "")

        # Strict Zero-PII assertions:
        assert synthetic_email not in dispatched_text
        assert "shopper.victim" not in dispatched_text
        assert synthetic_phone not in dispatched_text
        assert "555" not in dispatched_text
        assert "Customer Email" not in dispatched_text

        # Operational non-PII attributes must be preserved:
        assert order_id in dispatched_text
        assert domain_name in dispatched_text
        assert store_name in dispatched_text
        assert "hard_bounce" in dispatched_text


# ==============================================================================
# TEST 9: Logs do not expose credentials or PII
# ==============================================================================
def test_telegram_logs_do_not_expose_credentials_or_pii():
    """Verify failover_logs record customer_email=None and sanitize sensitive tokens."""
    user_id = "user-log-sanitization-test-555"
    omnichannel_service._mock_mode = False

    bot_token = "1234567890:AAHTokenToSanitizeInLogs1234"
    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": bot_token,
        "telegram_chat_id": "-1007777777777",
    })

    synthetic_email = "confidential.customer@secret.com"
    synthetic_phone = "+44 7700 900077"

    with patch("httpx.AsyncClient.post", return_value=MockHttpResponse(200, {"result": {"message_id": 111}})):
        res = asyncio.run(omnichannel_service.trigger_failover_dispatch(
            user_id=user_id,
            order_id="ORD-LOG-111",
            customer_email=synthetic_email,
            customer_phone=synthetic_phone,
        ))

        log = res["log"]
        # Database log must NOT store personal email or telephone
        assert log.get("customer_email") is None
        assert log.get("customer_phone") is None

        # Verify token stripping in sanitize_log_message
        raw_msg = f"Failed to POST to https://api.telegram.org/bot{bot_token}/sendMessage"
        sanitized = sanitize_log_message(raw_msg, bot_token)
        assert bot_token not in sanitized
        assert "[REDACTED_TOKEN]" in sanitized


# ==============================================================================
# TEST 10: Existing worker dispatch compatibility
# ==============================================================================
def test_existing_worker_dispatch_compatibility():
    """Verify dispatch_alert provides full TelegramDispatchResult compatibility for workers."""
    user_id = "user-worker-compat-test-333"
    omnichannel_service._mock_mode = False

    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "1234567890:AAHWorkerCompatToken123456789",
        "telegram_chat_id": "-1003333333333",
    })

    ctx = TelegramIncidentContext(
        delivery_failure_event_id="evt-worker-compat-333",
        user_id=user_id,
        order_id="ORD-WORKER-333",
        domain_name="worker-store.com",
        store_name="Worker Brand",
        esp_provider="postmark",
        failure_type="hard_bounce",
        failure_reason="550 5.1.1 User unknown",
    )

    with patch("httpx.AsyncClient.post", return_value=MockHttpResponse(200, {"result": {"message_id": 88333}})):
        result = asyncio.run(omnichannel_service.dispatch_alert(ctx))

        assert isinstance(result, TelegramDispatchResult)
        assert result.success is True
        assert result.provider == "telegram"
        assert result.provider_status == "delivered"
        assert result.telegram_message_id == "88333"
        assert result.target_chat_id == "-1003333333333"

        # Worker dictionary-like compatibility check
        assert result["status"] == "delivered"
        assert result.get("status") == "delivered"
        assert result.get("success") is True


# ==============================================================================
# STANDALONE TEST RUNNER
# ==============================================================================
if __name__ == "__main__":
    print("=" * 75)
    print("Running Group 45B.3A Telegram Client Hardening & Zero-PII Test Suite...")
    print("=" * 75)

    test_cases = [
        ("1. Telegram dispatch fails closed when tenant unconfigured", test_telegram_dispatch_fails_closed_when_tenant_unconfigured),
        ("2. Telegram dispatch never uses global platform credentials", test_telegram_dispatch_never_uses_global_credentials),
        ("3. Telegram rate limit 429 respects retry_after", test_telegram_rate_limit_429_respects_retry_after),
        ("4. Telegram 429 retry budget is bounded", test_telegram_429_retry_budget_is_bounded),
        ("5. Telegram transient 5xx exponential backoff", test_telegram_transient_5xx_exponential_backoff),
        ("6. Telegram timeout retry is bounded", test_telegram_timeout_retry_is_bounded),
        ("7. Telegram permanent errors are not retried", test_telegram_permanent_errors_are_not_retried),
        ("8. Telegram synchronous dispatch zero PII", test_telegram_synchronous_dispatch_zero_pii),
        ("9. Telegram logs do not expose credentials or PII", test_telegram_logs_do_not_expose_credentials_or_pii),
        ("10. Existing worker dispatch compatibility", test_existing_worker_dispatch_compatibility),
    ]

    passed = 0
    failed = 0
    for name, test_func in test_cases:
        try:
            test_func()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 75)
    print(f"Results: {passed} passed, {failed} failed.")
    print("=" * 75)
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
