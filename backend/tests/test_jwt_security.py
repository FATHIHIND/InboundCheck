"""
InboundCheck - Adversarial JWT Security & Cryptographic Verification Test Suite
==============================================================================
Validates remediation of P0 - Cryptographic JWT Forgery:
1. Rejection of tokens signed with public anon key (SUPABASE_KEY).
2. Rejection of tokens signed with service-role key (SUPABASE_SERVICE_ROLE_KEY).
3. Strict algorithm allowlist (rejects 'none', HS384, HS512, RS512, etc.).
4. Mandatory claims enforcement (aud, role='authenticated', exp, nbf, sub).
5. Production fail-closed behavior when verification configuration is missing or placeholder.
6. Opaque error details (no internal information disclosure).
7. Zero credential / raw token leakage in logs.
"""

import pytest
import jwt
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from fastapi import HTTPException

from app.main import app
from app.core.config import settings
from app.core.security import verify_supabase_jwt, get_current_user_id, ALLOWED_ALGORITHMS
from tests.conftest import TEST_JWT_SECRET, auth_headers


# Mock Supabase Keys for adversarial testing
TEST_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJvbGUiOiJhbm9uIn0.public_anon_key_sample"
TEST_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJvbGUiOiJzZXJ2aWNlX3JvbGUifQ.service_key_sample"


def generate_custom_jwt(
    payload: dict,
    secret: str = TEST_JWT_SECRET,
    algorithm: str = "HS256",
    headers: dict = None,
) -> str:
    """Helper to generate JWTs with arbitrary algorithms, secrets, and headers."""
    return jwt.encode(payload, secret, algorithm=algorithm, headers=headers)


# =============================================================================
# 1. Primary P0 Vulnerability Proof: Public Anon Key Forgery Rejection
# =============================================================================

@pytest.mark.asyncio
async def test_forged_jwt_signed_with_public_anon_key_rejected():
    """
    CRITICAL PROOF OF P0 REMEDIATION:
    Attempt to authenticate with an HS256 token signed using SUPABASE_KEY (public anon key).
    The backend MUST reject it with HTTP 401.
    """
    victim_user_id = str(uuid.uuid4())
    now = int(time.time())

    # Set mock public anon key in settings
    with patch.object(settings, "SUPABASE_KEY", TEST_ANON_KEY):
        # Craft attacker token signed with public anon key
        forged_payload = {
            "sub": victim_user_id,
            "role": "authenticated",
            "aud": "authenticated",
            "exp": now + 3600,
            "iat": now,
        }
        forged_token = generate_custom_jwt(forged_payload, secret=TEST_ANON_KEY, algorithm="HS256")

        # 1. Direct function test: verify_supabase_jwt must raise HTTP 401
        with pytest.raises(HTTPException) as exc_info:
            verify_supabase_jwt(forged_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired authentication token"

        # 2. End-to-end HTTP endpoint test: GET /api/v1/domains must reject with 401
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                "/api/v1/domains",
                headers={"Authorization": f"Bearer {forged_token}"}
            )
            assert res.status_code == 401
            assert res.json()["detail"] == "Invalid or expired authentication token"


@pytest.mark.asyncio
async def test_forged_jwt_with_arbitrary_user_id_rejected():
    """Prove that an attacker cannot forge access to an arbitrary victim UUID using the anon key."""
    victim_user_id = "00000000-0000-0000-0000-000000000001"
    now = int(time.time())

    with patch.object(settings, "SUPABASE_KEY", TEST_ANON_KEY):
        forged_token = generate_custom_jwt(
            {"sub": victim_user_id, "role": "authenticated", "aud": "authenticated", "exp": now + 3600},
            secret=TEST_ANON_KEY,
            algorithm="HS256"
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                "/api/v1/billing/subscription",
                headers={"Authorization": f"Bearer {forged_token}"}
            )
            assert res.status_code == 401


# =============================================================================
# 2. Service-Role Key Conflation Rejection
# =============================================================================

@pytest.mark.asyncio
async def test_token_signed_with_service_role_key_rejected():
    """
    SUPABASE_SERVICE_ROLE_KEY must NEVER be accepted as an HMAC signing secret.
    Tokens signed with the service-role key string must be rejected.
    """
    now = int(time.time())
    with patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", TEST_SERVICE_ROLE_KEY):
        token = generate_custom_jwt(
            {"sub": str(uuid.uuid4()), "role": "authenticated", "aud": "authenticated", "exp": now + 3600},
            secret=TEST_SERVICE_ROLE_KEY,
            algorithm="HS256"
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_supabase_jwt(token)
        assert exc_info.value.status_code == 401


# =============================================================================
# 3. Algorithm Whitelist & Confusion Defense
# =============================================================================

def test_alg_none_rejected():
    """Tokens with alg='none' or unsigned tokens must be rejected unconditionally."""
    now = int(time.time())
    payload = {"sub": "user-none", "role": "authenticated", "aud": "authenticated", "exp": now + 3600}
    import base64
    import json
    h_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    unsigned_token = f"{h_b64}.{p_b64}."

    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(unsigned_token)
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize("bad_alg", ["HS384", "HS512", "RS384", "RS512", "ES384", "ES512", "none", "UNAPPROVED"])
def test_unsupported_algorithms_rejected(bad_alg: str):
    """Algorithms not explicitly in ALLOWED_ALGORITHMS must be rejected immediately."""
    now = int(time.time())
    payload = {"sub": "test-user", "role": "authenticated", "aud": "authenticated", "exp": now + 3600}
    
    try:
        token = jwt.encode(payload, "dummy-secret-32-chars-long-for-testing", algorithm=bad_alg if bad_alg in jwt.algorithms.get_default_algorithms() else "HS256", headers={"alg": bad_alg})
    except Exception:
        import base64, json
        h_b64 = base64.urlsafe_b64encode(json.dumps({"alg": bad_alg, "typ": "JWT"}).encode()).decode().rstrip("=")
        p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token = f"{h_b64}.{p_b64}.fakesig"

    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


# =============================================================================
# 4. Mandatory Claims Enforcement (aud, role, exp, nbf, sub)
# =============================================================================

def test_missing_audience_rejected():
    """Tokens missing 'aud' claim must fail closed."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_wrong_audience_rejected():
    """Tokens with mismatched audience claim must fail closed."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "aud": "attacker_audience", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_role_anon_rejected():
    """
    Tokens with role='anon' (such as the raw public anon key) must be rejected
    from authenticated tenant user endpoints.
    """
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "anon-user", "role": "anon", "aud": "authenticated", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_role_service_role_rejected():
    """
    Tokens with role='service_role' must be rejected from tenant user endpoints
    to preserve user authentication boundaries.
    """
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "service-worker", "role": "service_role", "aud": "authenticated", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_missing_role_rejected():
    """Tokens lacking the 'role' claim must be rejected."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "aud": "authenticated", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_missing_sub_rejected():
    """Tokens lacking a 'sub' claim must fail closed."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"role": "authenticated", "aud": "authenticated", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_empty_sub_rejected():
    """Tokens with empty or whitespace-only 'sub' claim must fail closed."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "   ", "role": "authenticated", "aud": "authenticated", "exp": now + 3600}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_expired_token_rejected():
    """Expired tokens must be rejected."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "aud": "authenticated", "exp": now - 100}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_future_nbf_token_rejected():
    """Tokens with a future not-before ('nbf') claim must be rejected."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "aud": "authenticated", "exp": now + 3600, "nbf": now + 300}
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_invalid_issuer_rejected():
    """Tokens with an untrusted issuer claim must be rejected."""
    now = int(time.time())
    token = generate_custom_jwt(
        {
            "sub": "test-user",
            "role": "authenticated",
            "aud": "authenticated",
            "exp": now + 3600,
            "iss": "https://attacker-idp.com/auth/v1"
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_malformed_token_rejected():
    """Tokens that cannot be parsed as valid JWT structure must be rejected."""
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt("not.a.valid.jwt.string")
    assert exc_info.value.status_code == 401


def test_invalid_signature_rejected():
    """Tokens signed with the wrong HMAC secret must be rejected."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "aud": "authenticated", "exp": now + 3600},
        secret="different-wrong-secret-key-32-chars"
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


# =============================================================================
# 5. Production Fail-Closed Behavior
# =============================================================================

def test_production_missing_jwt_secret_rejected():
    """In production, missing SUPABASE_JWT_SECRET must fail closed (raise 401)."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "aud": "authenticated", "exp": now + 3600},
        secret=TEST_JWT_SECRET
    )
    with patch.object(settings, "ENVIRONMENT", "production"), patch.object(settings, "SUPABASE_JWT_SECRET", ""):
        with pytest.raises(HTTPException) as exc_info:
            verify_supabase_jwt(token)
        assert exc_info.value.status_code == 401


def test_production_placeholder_jwt_secret_rejected():
    """In production, placeholder SUPABASE_JWT_SECRET must fail closed (raise 401)."""
    now = int(time.time())
    token = generate_custom_jwt(
        {"sub": "test-user", "role": "authenticated", "aud": "authenticated", "exp": now + 3600},
        secret="your_supabase_jwt_secret_placeholder"
    )
    with patch.object(settings, "ENVIRONMENT", "production"), patch.object(settings, "SUPABASE_JWT_SECRET", "your_supabase_jwt_secret_placeholder"):
        with pytest.raises(HTTPException) as exc_info:
            verify_supabase_jwt(token)
        assert exc_info.value.status_code == 401


# =============================================================================
# 6. Information Disclosure & Logging Hygiene
# =============================================================================

@pytest.mark.asyncio
async def test_authentication_errors_opaque_no_internal_disclosure():
    """
    Error responses must never expose internal cryptographic errors, stack traces,
    or library exception details to clients.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Invalid signature
        res1 = await ac.get("/api/v1/domains", headers={"Authorization": "Bearer invalid.signature.token"})
        assert res1.status_code == 401
        assert res1.json()["detail"] in ["Invalid or expired authentication token", "Authentication required. Please provide a valid Bearer token."]
        assert "traceback" not in res1.text.lower()
        assert "secret" not in res1.text.lower()
        assert "signature" not in res1.text.lower()

        # Missing token
        res2 = await ac.get("/api/v1/domains")
        assert res2.status_code == 401
        assert res2.json()["detail"] == "Authentication required. Please provide a valid Bearer token."


def test_credentials_and_tokens_not_logged(caplog):
    """Assert that raw JWT tokens, secrets, and credentials never appear in application logs."""
    sensitive_token = generate_custom_jwt(
        {"sub": "secret-victim-id", "role": "authenticated", "aud": "authenticated", "exp": int(time.time()) + 3600},
        secret="wrong-secret-causing-verification-failure-32b"
    )
    
    with caplog.at_level(logging.DEBUG):
        try:
            verify_supabase_jwt(sensitive_token)
        except HTTPException:
            pass

    log_output = caplog.text
    # Sensitive items must NOT appear in logs
    assert sensitive_token not in log_output
    assert TEST_JWT_SECRET not in log_output
    assert "wrong-secret-causing-verification-failure" not in log_output


def test_anon_and_service_role_keys_not_in_candidate_list():
    """Static inspection verifying candidate secrets do not include anon or service-role keys."""
    import inspect
    import app.core.security as sec_module

    source = inspect.getsource(sec_module.verify_supabase_jwt)
    assert "settings.SUPABASE_KEY" not in source
    assert "settings.SUPABASE_SERVICE_ROLE_KEY" not in source
    assert "secret_candidates" not in source


# =============================================================================
# 7. Legitimate Authenticated Token End-to-End Success
# =============================================================================

@pytest.mark.asyncio
async def test_legitimate_authenticated_token_succeeds():
    """Verify that a legitimate, properly signed Supabase token authenticates successfully."""
    transport = ASGITransport(app=app)
    valid_headers = auth_headers("test-legitimate-user")

    async with AsyncClient(transport=transport, base_url="http://test", headers=valid_headers) as ac:
        res = await ac.get("/api/v1/billing/plans")
        assert res.status_code == 200
        assert "plans" in res.json()
