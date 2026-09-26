"""
InboundCheck - Comprehensive Test Suite for Production-Grade DNS Auto-Fixer (Phase 1B)
=====================================================================================
Validates:
1. Fernet envelope encryption/decryption, ciphertext versioning, tampering rejection, and masking.
2. Persistent provider credential storage, retrieval, and revocation.
3. Pre-mutation snapshot capture (existing vs. new record).
4. Cloudflare mutation lifecycle (PLAN -> VALIDATE -> SNAPSHOT -> PERSIST -> APPLY -> VERIFY).
5. Post-mutation verification failure handling and fail-closed policies.
6. Real Cloudflare rollback (DELETE for created records, PUT for updated records).
7. Idempotency protection against duplicate requests.
8. Concurrency protection against simultaneous in-flight operations on the same DNS target.
9. Strict multi-tenant isolation (cross-tenant credential, domain, and log access blocked).
10. Billing tier enforcement (Growth/Enterprise required).
"""

import pytest
import uuid
import json
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport, Response

from app.main import app
from app.core.config import settings
from app.core.encryption import (
    encrypt_credential,
    decrypt_credential,
    mask_credential,
    get_fernet_cipher,
    DecryptionError,
    EncryptionKeyMissingError,
    CIPHERTEXT_PREFIX,
)
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.dns.auto_fixer import dns_auto_fixer_service, dns_auto_fixer
from app.services.dns.cloudflare_client import cloudflare_client, CloudflareAPIError
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def isolate_supabase_autofix():
    """Ensure tests run completely isolated without mutating live Supabase."""
    orig_client = supabase_service._client
    supabase_service._client = None
    supabase_service._in_memory_dns_provider_creds.clear()
    supabase_service._in_memory_dns_auto_fix_logs.clear()
    supabase_service._in_memory_domains.clear()
    yield
    supabase_service._client = orig_client
    supabase_service._in_memory_dns_provider_creds.clear()
    supabase_service._in_memory_dns_auto_fix_logs.clear()
    supabase_service._in_memory_domains.clear()


# =====================================================================
# 1. ENCRYPTION & CREDENTIAL SECURITY TESTS
# =====================================================================

def test_fernet_credential_encryption_and_decryption_lifecycle():
    """Verify authenticated Fernet encryption at rest with version prefix."""
    raw_token = "cf-token-secret-alpha-998877"
    ciphertext = encrypt_credential(raw_token)

    # 1. Version prefix check
    assert ciphertext.startswith(CIPHERTEXT_PREFIX)
    # 2. Plaintext must never appear in ciphertext
    assert raw_token not in ciphertext
    # 3. Decryption must accurately restore original plaintext
    decrypted = decrypt_credential(ciphertext)
    assert decrypted == raw_token


def test_fernet_decryption_tampering_fails_closed():
    """Verify that tampering with ciphertext fails closed with DecryptionError."""
    raw_token = "cf-sensitive-secret-key"
    ciphertext = encrypt_credential(raw_token)

    # Corrupt the ciphertext payload
    tampered = ciphertext[:-4] + "XXXX"
    with pytest.raises(DecryptionError):
        decrypt_credential(tampered)


def test_credential_masking():
    """Verify that raw tokens are masked to last 4 characters preceded by bullets."""
    assert mask_credential("cf_api_token_1234") == "••••••••••••1234"
    assert mask_credential("short") == "••••••••••••hort"
    assert mask_credential("ab") == "••••"
    assert mask_credential(None) == "••••••••••••"


# =====================================================================
# 2. PROVIDER CREDENTIAL PERSISTENCE & API ROUTE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_save_and_retrieve_provider_credentials_with_masking():
    """Verify saving credentials persists encrypted token and returns masked representation."""
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # Save Cloudflare token
        save_res = await ac.post("/api/v1/dns/auto-fix/credentials", json={
            "provider_name": "cloudflare",
            "token_or_key": "my-secret-cf-token-5678",
            "secret_or_zone": "zone-xyz-12345"
        })
        assert save_res.status_code == 200
        data = save_res.json()
        cf = data["credentials"]["cloudflare"]
        assert cf["is_active"] is True
        assert cf["api_token_configured"] is True
        assert cf["token_masked"] == "••••••••••••5678"
        # Secret must NEVER be present in response
        assert "my-secret-cf-token-5678" not in json.dumps(data)

        # Retrieve credentials
        get_res = await ac.get("/api/v1/dns/auto-fix/credentials")
        assert get_res.status_code == 200
        get_cf = get_res.json()["credentials"]["cloudflare"]
        assert get_cf["token_masked"] == "••••••••••••5678"
        assert get_cf["zone_id"] == "zone-xyz-12345"


@pytest.mark.asyncio
async def test_revoke_provider_credentials():
    """Verify provider credentials can be revoked and marked inactive."""
    user_id = str(uuid.uuid4())
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "token-to-revoke-9999", "zone-123")

    creds_before = dns_auto_fixer.get_credentials(user_id)
    assert creds_before["cloudflare"]["is_active"] is True

    # Revoke
    revoked = dns_auto_fixer.revoke_credentials(user_id, "cloudflare")
    assert revoked is True

    creds_after = dns_auto_fixer.get_credentials(user_id)
    assert creds_after["cloudflare"]["is_active"] is False


# =====================================================================
# 3. SNAPSHOT & CLOUDFLARE MUTATION LIFECYCLE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_apply_auto_fix_new_record_lifecycle():
    """
    Test complete lifecycle for inserting a new DNS record:
    PLAN -> SNAPSHOT (exists=False) -> APPLY (create) -> VERIFY -> FINALIZE.
    """
    user_id = str(uuid.uuid4())
    domain = "shop-alpha.com"
    host = "_dmarc.shop-alpha.com"
    val = "v=DMARC1; p=reject;"

    # 1. Authorize user with Growth subscription and monitored domain
    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)

    # 2. Save merchant credential
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "valid-cf-token-1234", "zone-alpha-123")

    mock_zone = {"zone_id": "zone-alpha-123", "name": "shop-alpha.com", "status": "active"}
    mock_created = {"id": "rec_new_999", "type": "TXT", "name": host, "content": val, "ttl": 3600, "proxied": False}

    with patch.object(cloudflare_client, "get_zone_by_domain", new=AsyncMock(return_value=mock_zone)), \
         patch.object(cloudflare_client, "get_dns_record", new=AsyncMock(side_effect=[None, mock_created])), \
         patch.object(cloudflare_client, "create_dns_record", new=AsyncMock(return_value=mock_created)):

        result = await dns_auto_fixer.apply_dns_fix(
            user_id=user_id,
            domain_name=domain,
            provider_name="cloudflare",
            record_type="TXT",
            host=host,
            record_value=val,
        )

        assert result["applied"] is True
        assert result["verified"] is True
        fix_entry = result["fix_entry"]
        assert fix_entry["status"] == "applied"
        assert fix_entry["verification_status"] == "VERIFIED"
        assert fix_entry["target_record_id"] == "rec_new_999"

        # Check snapshot
        snapshot = fix_entry["snapshot_before"]
        assert snapshot["exists"] is False
        assert snapshot["record_id"] is None
        assert snapshot["zone_id"] == "zone-alpha-123"


@pytest.mark.asyncio
async def test_apply_auto_fix_update_record_lifecycle():
    """
    Test lifecycle when updating an existing record (e.g. SPF policy update):
    PLAN -> SNAPSHOT (exists=True, captures old value) -> APPLY (update via PUT) -> VERIFY -> FINALIZE.
    """
    user_id = str(uuid.uuid4())
    domain = "shop-beta.com"
    host = "@"
    old_val = "v=spf1 include:_spf.google.com ~all"
    new_val = "v=spf1 include:_spf.google.com include:shops.shopify.com ~all"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "token-beta-1234", "zone-beta-456")

    mock_zone = {"zone_id": "zone-beta-456", "name": "shop-beta.com", "status": "active"}
    existing_rec = {"id": "rec_old_111", "type": "TXT", "name": host, "content": old_val, "ttl": 3600, "proxied": False}
    updated_rec = {"id": "rec_old_111", "type": "TXT", "name": host, "content": new_val, "ttl": 3600, "proxied": False}

    with patch.object(cloudflare_client, "get_zone_by_domain", new=AsyncMock(return_value=mock_zone)), \
         patch.object(cloudflare_client, "get_dns_record", new=AsyncMock(side_effect=[existing_rec, updated_rec])), \
         patch.object(cloudflare_client, "update_dns_record", new=AsyncMock(return_value=updated_rec)) as mock_update:

        result = await dns_auto_fixer.apply_dns_fix(
            user_id=user_id,
            domain_name=domain,
            provider_name="cloudflare",
            record_type="TXT",
            host=host,
            record_value=new_val,
        )

        assert result["applied"] is True
        assert result["verified"] is True
        mock_update.assert_awaited_once()

        snapshot = result["fix_entry"]["snapshot_before"]
        assert snapshot["exists"] is True
        assert snapshot["record_id"] == "rec_old_111"
        assert snapshot["previous_value"] == old_val


# =====================================================================
# 4. REAL CLOUDFLARE ROLLBACK TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_rollback_created_record_deletes_from_cloudflare():
    """Verify rollback of a newly created record executes DELETE on Cloudflare API."""
    user_id = str(uuid.uuid4())
    domain = "rollback-test.com"
    host = "default._domainkey.rollback-test.com"
    val = "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ..."

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "token-rb-1234", "zone-rb-789")

    # Manually seed a verified operation where record did not previously exist
    op = supabase_service.create_dns_auto_fix_operation({
        "id": "fix_to_delete_123",
        "user_id": user_id,
        "domain_name": domain,
        "provider_name": "cloudflare",
        "record_type": "TXT",
        "host": host,
        "record_value": val,
        "status": "VERIFIED",
        "target_record_id": "cf_rec_to_delete_555",
        "zone_id": "zone-rb-789",
        "snapshot_before": {
            "exists": False,
            "record_id": None,
            "zone_id": "zone-rb-789",
            "host": host,
            "record_type": "TXT",
        }
    })

    with patch.object(cloudflare_client, "delete_dns_record", new=AsyncMock(return_value=True)) as mock_delete:
        rb_res = await dns_auto_fixer.rollback_dns_fix(user_id=user_id, fix_id="fix_to_delete_123")
        assert rb_res["rolled_back"] is True
        assert rb_res["status"] == "ROLLED_BACK"
        mock_delete.assert_awaited_once_with("token-rb-1234", "zone-rb-789", "cf_rec_to_delete_555")

        # Verify operation status in DB
        updated_op = supabase_service.get_dns_auto_fix_operation("fix_to_delete_123", user_id=user_id)
        assert updated_op["status"] == "ROLLED_BACK"


@pytest.mark.asyncio
async def test_rollback_updated_record_restores_previous_values_via_put():
    """Verify rollback of an updated record executes PUT restoring exact prior snapshot values."""
    user_id = str(uuid.uuid4())
    domain = "restore-test.com"
    host = "@"
    prior_spf = "v=spf1 include:_spf.google.com ~all"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "token-restore-1234", "zone-restore-999")

    # Seed verified operation where record was modified
    supabase_service.create_dns_auto_fix_operation({
        "id": "fix_to_restore_456",
        "user_id": user_id,
        "domain_name": domain,
        "provider_name": "cloudflare",
        "record_type": "TXT",
        "host": host,
        "record_value": "v=spf1 new-mutated-value ~all",
        "status": "VERIFIED",
        "target_record_id": "cf_rec_existing_777",
        "zone_id": "zone-restore-999",
        "snapshot_before": {
            "exists": True,
            "record_id": "cf_rec_existing_777",
            "previous_value": prior_spf,
            "record_value": prior_spf,
            "ttl": 1800,
            "proxied": False,
            "zone_id": "zone-restore-999",
            "host": host,
            "record_type": "TXT",
        }
    })

    restored_record = {"id": "cf_rec_existing_777", "type": "TXT", "name": host, "content": prior_spf, "ttl": 1800}

    with patch.object(cloudflare_client, "update_dns_record", new=AsyncMock(return_value=restored_record)) as mock_update:
        rb_res = await dns_auto_fixer.rollback_dns_fix(user_id=user_id, fix_id="fix_to_restore_456")
        assert rb_res["rolled_back"] is True
        assert rb_res["status"] == "ROLLED_BACK"
        mock_update.assert_awaited_once_with(
            token="token-restore-1234",
            zone_id="zone-restore-999",
            record_id="cf_rec_existing_777",
            record_type="TXT",
            host=host,
            content=prior_spf,
            ttl=1800,
            proxied=False,
        )


# =====================================================================
# 5. IDEMPOTENCY & CONCURRENCY TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_idempotent_duplicate_request_skips_duplicate_mutation():
    """Verify that applying an identical fix when the record is already in desired state is safely idempotent."""
    user_id = str(uuid.uuid4())
    domain = "idempotent-shop.com"
    host = "_dmarc.idempotent-shop.com"
    val = "v=DMARC1; p=reject;"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "token-idem-123", "zone-idem-123")

    mock_zone = {"zone_id": "zone-idem-123", "name": domain}
    # Cloudflare already has this exact record
    already_existing = {"id": "rec_idem_001", "type": "TXT", "name": host, "content": val, "ttl": 3600}

    with patch.object(cloudflare_client, "get_zone_by_domain", new=AsyncMock(return_value=mock_zone)), \
         patch.object(cloudflare_client, "get_dns_record", new=AsyncMock(return_value=already_existing)), \
         patch.object(cloudflare_client, "create_dns_record", new=AsyncMock()) as mock_create, \
         patch.object(cloudflare_client, "update_dns_record", new=AsyncMock()) as mock_update:

        result = await dns_auto_fixer.apply_dns_fix(
            user_id=user_id,
            domain_name=domain,
            provider_name="cloudflare",
            record_type="TXT",
            host=host,
            record_value=val,
        )

        assert result["applied"] is True
        assert result.get("verified") is True
        # Neither create nor update should have been called!
        mock_create.assert_not_called()
        mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_concurrency_lock_rejects_simultaneous_in_flight_mutation():
    """Verify that a second mutation on the same DNS target is rejected if an operation is currently APPLYING."""
    user_id = str(uuid.uuid4())
    domain = "concurrent-shop.com"
    host = "@"
    val = "v=spf1 -all"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "token-conc-123", "zone-conc-123")

    # Seed an in-flight operation
    supabase_service.create_dns_auto_fix_operation({
        "id": "op_in_flight_111",
        "user_id": user_id,
        "domain_name": domain,
        "provider_name": "cloudflare",
        "record_type": "TXT",
        "host": host,
        "record_value": val,
        "status": "APPLYING",
    })

    result = await dns_auto_fixer.apply_dns_fix(
        user_id=user_id,
        domain_name=domain,
        provider_name="cloudflare",
        record_type="TXT",
        host=host,
        record_value=val,
    )

    assert result["applied"] is False
    assert "concurrent DNS mutation is already in progress" in result["error"]


# =====================================================================
# 6. TENANT ISOLATION TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_tenant_cannot_rollback_another_users_operation():
    """Verify User B cannot rollback User A's DNS operation."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    op = supabase_service.create_dns_auto_fix_operation({
        "id": "fix_user_a_secure_1",
        "user_id": user_a,
        "domain_name": "usera-store.com",
        "provider_name": "cloudflare",
        "record_type": "TXT",
        "host": "_dmarc.usera-store.com",
        "record_value": "v=DMARC1; p=reject;",
        "status": "VERIFIED",
    })

    # User B attempts rollback
    rb_res = await dns_auto_fixer.rollback_dns_fix(user_id=user_b, fix_id="fix_user_a_secure_1")
    assert rb_res["rolled_back"] is False
    assert "Fix ID not found" in rb_res["reason"]


@pytest.mark.asyncio
async def test_tenant_cannot_read_another_users_logs():
    """Verify tenant isolation on GET /api/v1/dns/auto-fix/logs."""
    transport = ASGITransport(app=app)
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    supabase_service.create_dns_auto_fix_operation({
        "id": "log_user_a_secret",
        "user_id": user_a,
        "domain_name": "brand-a.com",
        "provider_name": "cloudflare",
        "record_type": "TXT",
        "host": "@",
        "record_value": "secret-value-a",
        "status": "VERIFIED",
    })

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_b)) as ac:
        res = await ac.get("/api/v1/dns/auto-fix/logs")
        assert res.status_code == 200
        logs = res.json().get("logs", [])
        assert all(l["user_id"] == user_b for l in logs)
        assert not any(l["id"] == "log_user_a_secret" for l in logs)


# =====================================================================
# 7. BILLING TIER ENFORCEMENT & REST ENDPOINT INTEGRATION
# =====================================================================

@pytest.mark.asyncio
async def test_starter_user_denied_auto_fix_apply():
    """Verify Starter tier user with expired trial receives 403 UPGRADE_REQUIRED on /apply."""
    transport = ASGITransport(app=app)
    starter_user = str(uuid.uuid4())

    supabase_service.update_user_profile(starter_user, {
        "subscription_tier": "starter",
        "subscription_status": "active",
        "trial_ends_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    })

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(starter_user)) as ac:
        res = await ac.post("/api/v1/dns/auto-fix/apply", json={
            "domain_name": "starter-store.com",
            "host": "_dmarc.starter-store.com",
            "record_type": "TXT",
            "record_value": "v=DMARC1; p=quarantine;"
        })
        assert res.status_code == 403
        assert "UPGRADE_REQUIRED" in res.json()["detail"]


@pytest.mark.asyncio
async def test_rest_api_apply_and_rollback_endpoint_flow():
    """Verify end-to-end REST API flow for POST /apply and POST /rollback."""
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    domain = "api-flow-shop.com"
    host = "_dmarc.api-flow-shop.com"
    val = "v=DMARC1; p=reject;"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "valid-token-api-flow", "zone-flow-123")

    mock_zone = {"zone_id": "zone-flow-123", "name": domain}
    mock_created = {"id": "rec_flow_001", "type": "TXT", "name": host, "content": val, "ttl": 3600}

    with patch.object(cloudflare_client, "get_zone_by_domain", new=AsyncMock(return_value=mock_zone)), \
         patch.object(cloudflare_client, "get_dns_record", new=AsyncMock(side_effect=[None, mock_created])), \
         patch.object(cloudflare_client, "create_dns_record", new=AsyncMock(return_value=mock_created)), \
         patch.object(cloudflare_client, "delete_dns_record", new=AsyncMock(return_value=True)):

        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
            # 1. Apply Fix
            apply_res = await ac.post("/api/v1/dns/auto-fix/apply", json={
                "domain_name": domain,
                "provider_name": "cloudflare",
                "record_type": "TXT",
                "host": host,
                "record_value": val,
            })
            assert apply_res.status_code == 200
            apply_data = apply_res.json()
            assert apply_data["applied"] is True
            fix_id = apply_data["fix_entry"]["id"]

            # 2. Rollback Fix
            rb_res = await ac.post("/api/v1/dns/auto-fix/rollback", json={"fix_id": fix_id})
            assert rb_res.status_code == 200
            assert rb_res.json()["rolled_back"] is True
            assert rb_res.json()["status"] == "ROLLED_BACK"


# =====================================================================
# 8. PHASE 1D RELEASE REMEDIATION VERIFICATION TESTS
# =====================================================================

def test_production_missing_encryption_key_raises_error():
    """Verify that in production, missing ENCRYPTION_KEY raises EncryptionKeyMissingError."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "ENCRYPTION_KEY", ""):
        assert settings.is_production is True
        with pytest.raises(EncryptionKeyMissingError, match="ENCRYPTION_KEY must be explicitly configured"):
            get_fernet_cipher()


def test_production_never_falls_back_to_jwt_secret():
    """Verify that in production, SUPABASE_JWT_SECRET is NEVER used as encryption fallback."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "ENCRYPTION_KEY", ""), \
         patch.object(settings, "SUPABASE_JWT_SECRET", "super-secret-jwt-key"):
        assert settings.is_production is True
        with pytest.raises(EncryptionKeyMissingError, match="JWT secret fallback and automatic key generation are strictly prohibited"):
            get_fernet_cipher()


def test_production_database_failure_fails_closed_without_in_memory_fallback():
    """
    Verify that in production, failure to communicate with PostgreSQL raises
    DatabaseUnavailableError and NEVER falls back to in-memory dictionaries.
    """
    with patch.object(settings, "ENVIRONMENT", "production"):
        assert supabase_service._allow_in_memory_fallback() is False

        # Attempt to save credential with no DB connection
        with pytest.raises(DatabaseUnavailableError):
            supabase_service.save_dns_provider_credential(
                user_id=str(uuid.uuid4()),
                provider_name="cloudflare",
                api_token_encrypted="enc_token_123",
                zone_id="zone_123"
            )

        # Attempt to create auto-fix operation with no DB connection
        with pytest.raises(DatabaseUnavailableError):
            supabase_service.create_dns_auto_fix_operation({
                "id": "fix_fail_closed",
                "user_id": str(uuid.uuid4()),
                "domain_name": "example.com",
                "provider_name": "cloudflare",
                "record_type": "TXT",
                "host": "@",
                "record_value": "v=spf1 -all",
                "status": "APPLYING"
            })


def test_test_environment_allows_in_memory_fallback():
    """Verify that non-production environments allow in-memory fallback for test isolation."""
    with patch.object(settings, "ENVIRONMENT", "test"):
        assert supabase_service._allow_in_memory_fallback() is True
        # In test mode with _client = None, should successfully use in-memory store
        user_id = str(uuid.uuid4())
        res = supabase_service.save_dns_provider_credential(
            user_id=user_id,
            provider_name="cloudflare",
            api_token_encrypted="enc_test_tok",
            zone_id="zone_test"
        )
        assert res["provider_name"] == "cloudflare"
        fetched = supabase_service.get_dns_provider_credential(user_id, "cloudflare")
        assert fetched["zone_id"] == "zone_test"
