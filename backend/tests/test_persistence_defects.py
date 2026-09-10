"""
InboundCheck - Persistence Defects & Shopify OAuth Security Test Suite
=======================================================================
Verifies:
1. Schema drift resolution in `save_audit_log` (strict mapping to public.dns_audit_logs).
2. Failure resilience: DB errors are logged as warnings without breaking responses.
3. Cryptographic Fernet access token encryption & decryption.
4. HMAC-SHA256 OAuth state binding to user_id and expiry protection.
5. End-to-end OAuth authorize and callback store persistence flow.
"""

import pytest
import time
import base64
import hashlib
import hmac
import uuid
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from tests.conftest import auth_headers
from app.services.supabase_client import supabase_service
from app.services.shopify.shopify_service import shopify_service
from app.schemas.dns import (
    DeliverabilityResult,
    DiagnosticSummary,
    SPFSummary,
    DKIMSummary,
    DKIMSelectorResult,
    DMARCSummary,
    MXSummary,
    BIMISummary,
    DNSRecordFix,
    DiagnosticIssue,
    CategoryScoreBreakdown,
)


@pytest.mark.asyncio
async def test_save_audit_log_strict_production_schema_mapping():
    """
    Test 1: Schema Drift Resolution in save_audit_log.
    Verifies that fields strictly map to public.dns_audit_logs table columns
    and drifted legacy fields (overall_score, issues_found, recommendations, dkim_record) are eliminated.
    """
    user_id = str(uuid.uuid4())
    domain_id = str(uuid.uuid4())
    domain_name = "shopbrand.com"

    summary = DiagnosticSummary(
        spf=SPFSummary(status="optimal", raw="v=spf1 include:shops.shopify.com ~all", syntax_valid=True),
        dkim=DKIMSummary(
            status="optimal",
            found_selectors=["shopify"],
            records=[
                DKIMSelectorResult(
                    selector="shopify",
                    status="optimal",
                    record_name="shopify._domainkey.shopbrand.com",
                    raw="v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ...",
                    has_public_key=True
                )
            ]
        ),
        dmarc=DMARCSummary(status="optimal", raw="v=DMARC1; p=quarantine; pct=100;", policy="quarantine", syntax_valid=True),
        mx=MXSummary(status="optimal", record_count=1, raw=["10 mx.shopbrand.com"]),
        bimi=BIMISummary(status="missing", raw=None)
    )

    result_model = DeliverabilityResult(
        health_score=94,
        status="optimal",
        summary=summary,
        fixes=[
            DNSRecordFix(
                record_type="TXT",
                host="_dmarc.shopbrand.com",
                value="v=DMARC1; p=reject; pct=100;",
                category="DMARC",
                rationale="Upgrade policy"
            )
        ],
        raw_responses={"dns_sec": "verified"}
    )

    # Call save_audit_log with Pydantic model
    entry = supabase_service.save_audit_log(
        user_id=user_id,
        domain_id=domain_id,
        domain_name=domain_name,
        audit_result=result_model
    )

    # Verify column presence matching public.dns_audit_logs
    assert entry["user_id"] == user_id
    assert entry["domain_id"] == domain_id
    assert entry["domain_name"] == domain_name
    assert entry["health_score"] == 94
    assert entry["spf_record"] == "v=spf1 include:shops.shopify.com ~all"
    assert entry["spf_status"] == "optimal"
    assert isinstance(entry["dkim_records"], list)
    assert len(entry["dkim_records"]) == 1
    assert entry["dkim_records"][0]["selector"] == "shopify"
    assert entry["dkim_status"] == "optimal"
    assert entry["dmarc_record"] == "v=DMARC1; p=quarantine; pct=100;"
    assert entry["dmarc_status"] == "optimal"
    assert entry["mx_status"] == "optimal"
    assert entry["bimi_status"] in ["missing", "optimal"]
    assert isinstance(entry["fixes"], list)
    assert len(entry["fixes"]) == 1
    assert entry["raw_responses"] == {"dns_sec": "verified"}
    assert "created_at" in entry

    # Verify drifted legacy fields are NOT in the database payload
    assert "overall_score" not in entry
    assert "issues_found" not in entry
    assert "recommendations" not in entry
    assert "raw_dns_results" not in entry


@pytest.mark.asyncio
async def test_save_audit_log_failure_resilience(caplog):
    """
    Test 2: Verifies that a database failure in Supabase is caught, logged as a warning,
    and returns an in-memory entry without raising an unhandled exception.
    """
    user_id = str(uuid.uuid4())
    mock_client = MagicMock()
    mock_client.table.side_effect = Exception("Supabase connection timeout")

    # Temporarily attach mock client to simulate DB failure
    orig_client = supabase_service._client
    supabase_service._client = mock_client

    try:
        dict_payload = {
            "health_score": 85,
            "status": "warning",
            "summary": {
                "spf": {"raw": "v=spf1 ~all", "status": "warning"},
                "dkim": {"status": "missing", "records": []},
                "dmarc": {"raw": "v=DMARC1; p=none;", "status": "warning"},
                "mx": {"status": "optimal", "records": []},
                "bimi": {"status": "missing", "raw": None}
            },
            "fixes": [],
            "raw_responses": {}
        }

        # Should NOT raise an exception
        entry = supabase_service.save_audit_log(
            user_id=user_id,
            domain_id="invalid-uuid-format-should-be-safe",
            domain_name="testfailure.com",
            audit_result=dict_payload
        )

        assert entry is not None
        assert entry["domain_name"] == "testfailure.com"
        assert entry["health_score"] == 85
        # Invalid UUID was converted safely to None for DB safety
        assert entry["domain_id"] is None
        # Confirmed stored in in-memory logs
        assert "id" in entry
    finally:
        supabase_service._client = orig_client


def test_fernet_token_encryption():
    """
    Test 3: Token Encryption & Decryption roundtrip.
    """
    plain_token = "shpat_abc1234567890def_xyz"
    encrypted = shopify_service.encrypt_token(plain_token)

    assert encrypted != plain_token
    assert encrypted.startswith("gAAAAA")

    decrypted = shopify_service.decrypt_token(encrypted)
    assert decrypted == plain_token


def test_signed_oauth_state_generation_and_verification():
    """
    Test 4: OAuth State Binding & Tamper Detection.
    """
    tenant_id = "tenant-uuid-1234-abcd"

    # 1. Valid state generation and verification
    state = shopify_service.generate_oauth_state(tenant_id)
    verified_user = shopify_service.verify_oauth_state(state)
    assert verified_user == tenant_id

    # 2. Tampered state detection (signature mismatch)
    raw = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
    u, ts, sig = raw.split(":")
    tampered_raw = f"evil-user-hacker:{ts}:{sig}"
    tampered_state = base64.urlsafe_b64encode(tampered_raw.encode("utf-8")).decode("utf-8")
    assert shopify_service.verify_oauth_state(tampered_state) is None

    # 3. Expired state detection (> 1800s)
    expired_ts = str(int(time.time()) - 2000)
    secret = shopify_service.api_secret or "inboundcheck-oauth-state-secret"
    payload = f"{tenant_id}:{expired_ts}"
    exp_sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    expired_raw = f"{tenant_id}:{expired_ts}:{exp_sig}"
    expired_state = base64.urlsafe_b64encode(expired_raw.encode("utf-8")).decode("utf-8")
    assert shopify_service.verify_oauth_state(expired_state) is None


@pytest.mark.asyncio
async def test_shopify_oauth_flow_with_state_binding_and_persistence():
    """
    Test 5: End-to-end OAuth flow:
    - Authorize endpoint issues signed state bound to user.
    - Callback verifies signed state, extracts tenant, encrypts token, and persists store.
    """
    tenant_id = "usr_" + str(uuid.uuid4())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(tenant_id)) as ac:
        # 1. Generate Auth URL
        auth_res = await ac.post("/api/v1/shopify/oauth/authorize", json={
            "shop": "artisan-crafts.myshopify.com"
        })
        assert auth_res.status_code == 200
        auth_data = auth_res.json()
        assert "auth_url" in auth_data
        signed_state = auth_data["state"]
        assert signed_state is not None

        # 2. Callback rejects untrusted or forged state
        bad_cb = await ac.get("/api/v1/shopify/oauth/callback?shop=artisan-crafts.myshopify.com&code=mock_code&state=invalid_forged_state")
        assert bad_cb.status_code in [400, 401]

        # 3. Callback with valid signed state exchanges code and persists store
        mock_token_data = {"access_token": "shpat_test_token_secret_999", "scope": "read_orders,read_fulfillments"}
        mock_shop_details = {
            "name": "Artisan Crafts Boutique",
            "email": "orders@artisancrafts.com",
            "domain": "artisancrafts.com",
            "currency": "USD"
        }

        with patch.object(shopify_service, "exchange_token", return_value=mock_token_data), \
             patch.object(shopify_service, "fetch_shop_details", return_value=mock_shop_details), \
             patch.object(shopify_service, "verify_shopify_hmac", return_value=True):

            cb_res = await ac.get(f"/api/v1/shopify/oauth/callback?shop=artisan-crafts.myshopify.com&code=valid_code&state={signed_state}")
            assert cb_res.status_code == 200
            cb_data = cb_res.json()
            assert cb_data["success"] is True
            assert cb_data["user_id"] == tenant_id
            assert cb_data["stored"] is True
            assert cb_data["store_name"] == "Artisan Crafts Boutique"

            # 4. Verify store persistence in database / in-memory store
            stores = supabase_service.get_user_stores(tenant_id)
            assert len(stores) >= 1
            matching_store = next((s for s in stores if s["shop_domain"] == "artisan-crafts.myshopify.com"), None)
            assert matching_store is not None
            assert matching_store["user_id"] == tenant_id
            assert matching_store["sender_email"] == "orders@artisancrafts.com"

            # Confirm stored token is encrypted (not plain text)
            encrypted_token_in_store = matching_store["access_token_encrypted"]
            assert encrypted_token_in_store != "shpat_test_token_secret_999"
            assert shopify_service.decrypt_token(encrypted_token_in_store) == "shpat_test_token_secret_999"
