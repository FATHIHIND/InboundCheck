"""Security API regressions for the reviewed dependency upgrade (offline only)."""
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI, HTTPException, Request
from app.core.config import settings
from app.core.security import verify_supabase_jwt, AUTH_ERROR_DETAIL
from app.main import app
from app.services.billing.stripe_service import StripeService
from app.services.shopify.shopify_service import shopify_service
from tests.conftest import TEST_JWT_SECRET


def claims():
    return {"sub": "upgrade-tenant", "aud": "authenticated", "role": "authenticated",
            "exp": int(time.time()) + 300}


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_asymmetric_jwks_api_still_verifies_and_binds_algorithm(algorithm):
    private = (rsa.generate_private_key(public_exponent=65537, key_size=2048)
               if algorithm == "RS256" else ec.generate_private_key(ec.SECP256R1()))
    token = jwt.encode(claims(), private, algorithm=algorithm, headers={"kid": "offline-key"})
    client = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key()))
    with patch("app.core.security._get_jwks_client", return_value=client):
        assert verify_supabase_jwt(token)["sub"] == "upgrade-tenant"
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        client.get_signing_key_from_jwt = lambda _: SimpleNamespace(key=wrong_key)
        with pytest.raises(HTTPException) as exc:
            verify_supabase_jwt(token)
        assert exc.value.status_code == 401
        assert exc.value.detail == AUTH_ERROR_DETAIL


def test_unsupported_critical_header_is_rejected_by_application():
    token = jwt.encode(claims(), TEST_JWT_SECRET, algorithm="HS256",
                       headers={"crit": ["unsupported-extension"], "unsupported-extension": True})
    with pytest.raises(HTTPException) as exc:
        verify_supabase_jwt(token)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("payload", [b'{"sub":', b'[1,2]', b'{"exp":1e1000000}'])
def test_signed_malformed_payload_returns_opaque_auth_error(payload):
    def enc(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    signed = enc(b'{"alg":"HS256","typ":"JWT"}') + b'.' + enc(payload)
    signature = hmac.new(TEST_JWT_SECRET.encode(), signed, hashlib.sha256).digest()
    token = (signed + b'.' + enc(signature)).decode()
    with pytest.raises(HTTPException) as exc:
        verify_supabase_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == AUTH_ERROR_DETAIL


@pytest.mark.parametrize("path", ["/api/v1/domains", "/api/v1/billing/subscription", "/api/v1/settings/profile"])
async def test_fastapi_dependency_auth_remains_fail_closed(path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers={"Authorization": "Bearer malformed.token.value"})
    assert response.status_code == 401


def test_stripe_signature_still_binds_exact_raw_bytes():
    body = b'{"type":"invoice.paid", "data":{"object":{}}}'
    secret = "whsec_offline_dependency_regression"
    stamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    service = StripeService()
    service.webhook_secret = secret
    signature = f"t={stamp},v1={digest}"
    with patch.object(settings, "ENVIRONMENT", "production"):
        assert service.verify_webhook_signature(body, signature)
        assert not service.verify_webhook_signature(json.dumps(json.loads(body)).encode(), signature)
        assert not service.verify_webhook_signature(body, signature.replace(digest, "0" * 64))


def test_shopify_fernet_ciphertext_remains_readable_and_authenticated():
    token = "shpat_offline_dependency_regression"
    encrypted = shopify_service.encrypt_token(token)
    assert encrypted != token
    assert shopify_service.decrypt_token(encrypted) == token
    # An authenticated envelope cannot be transplanted to another master key.
    with patch.object(shopify_service, "api_secret", "different-offline-shopify-master-key"):
        try:
            result = shopify_service.decrypt_token(encrypted)
        except Exception:
            pass
        else:
            assert result != token


@pytest.mark.parametrize("body", [b'a=1&b=2', b'a=' + b'x' * 32])
async def test_starlette_urlencoded_limits_are_enforced(body):
    probe = FastAPI()
    @probe.post("/")
    async def form(request: Request):
        async with request.form(max_fields=1, max_part_size=8) as parsed:
            return dict(parsed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=probe), base_url="http://test") as client:
        response = await client.post("/", content=body, headers={"content-type": "application/x-www-form-urlencoded"})
    assert response.status_code == 400
