"""
InboundCheck - Pytest Configuration & Test Fixtures
===================================================
Configures JWT signing secrets and authenticated test client helpers for test execution.
"""

import pytest
import jwt
from datetime import datetime, timedelta, timezone
from app.core.config import settings

TEST_JWT_SECRET = "inboundcheck-super-secret-key-for-test-suites-12345"
settings.SUPABASE_JWT_SECRET = TEST_JWT_SECRET


def create_test_jwt(
    user_id: str = "test-user-1",
    expired: bool = False,
    bad_signature: bool = False
) -> str:
    """Generate a signed HS256 JWT for testing authentication."""
    secret = "wrong-key-signature-mismatch" if bad_signature else TEST_JWT_SECRET
    exp_time = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=2))
    payload = {
        "sub": user_id,
        "exp": int(exp_time.timestamp()),
        "role": "authenticated",
        "aud": "authenticated",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_headers(user_id: str = "test-user-1") -> dict:
    """Return Authorization Bearer header with signed test JWT."""
    token = create_test_jwt(user_id=user_id)
    return {"Authorization": f"Bearer {token}"}
