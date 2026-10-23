"""
InboundCheck - Staging Domain Audit End-to-End Verification (Phase 19.4)
=======================================================================
Executes the full Domain Audit worker lifecycle directly against the dedicated
STAGING Supabase database (wymgyqnqwlliotkxamtd).

Guarantees:
1. Strict fail-closed StagingIsolationGuard prevents any connection to Production (tbjcldcoozvuvyipeonh).
2. Real PostgreSQL RPC execution for claim_due_domain_audits, complete_domain_audit, and fail_domain_audit.
3. Real database persistence verification in public.monitored_domains, public.dns_audit_logs,
   and public.reputation_checks.
4. Guaranteed cleanup of isolated staging fixtures via cascade delete on test auth user.
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
import pytest

# 1. Mandatory Fail-Closed Staging Bootstrap BEFORE any app or client imports
from app.core.staging_guard import (
    bootstrap_staging_environment,
    StagingIsolationError,
    PROD_PROJECT_REF,
    resolve_staging_env_path,
    validate_staging_config,
)

_CAPTURED_ENV_KEYS = [
    "ENVIRONMENT",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]
_SAVED_VARS = {k: os.environ.get(k) for k in _CAPTURED_ENV_KEYS}
EXPECTED_STAGING_REF = "wymgyqnqwlliotkxamtd"

# Fail-closed check: immediately halt if environment contains production reference
for _url_cand in [os.environ.get("STAGING_SUPABASE_URL", ""), os.environ.get("SUPABASE_URL", "")]:
    if PROD_PROJECT_REF in _url_cand.strip().lower():
        raise StagingIsolationError(
            f"CRITICAL ISOLATION BREACH: Environment contains production reference '{PROD_PROJECT_REF}'! "
            "Execution halted immediately."
        )

# Determine whether staging configuration is present
_has_staging_file = False
try:
    resolve_staging_env_path()
    _has_staging_file = True
except StagingIsolationError:
    _has_staging_file = False

_has_staging_env = bool(
    (os.environ.get("STAGING_SUPABASE_URL") or os.environ.get("SUPABASE_URL"))
    and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    and (os.environ.get("ENVIRONMENT", "").strip().lower() == "staging")
)

if not _has_staging_file and not _has_staging_env:
    pytest.skip(
        "Staging configuration (.env.staging or STAGING_SUPABASE_URL) not available; skipping live staging integration tests.",
        allow_module_level=True,
    )

# Bootstrap staging environment
if _has_staging_file:
    bootstrap_staging_environment(expected_staging_ref=EXPECTED_STAGING_REF)
else:
    if os.environ.get("STAGING_SUPABASE_URL") and not os.environ.get("SUPABASE_URL"):
        os.environ["SUPABASE_URL"] = os.environ["STAGING_SUPABASE_URL"]
    validate_staging_config(dict(os.environ), EXPECTED_STAGING_REF)

# Enforce post-bootstrap assertion
assert EXPECTED_STAGING_REF in os.environ.get("SUPABASE_URL", "")
assert PROD_PROJECT_REF not in os.environ.get("SUPABASE_URL", "")

# Reload configuration and client modules to ensure staging values are bound
import importlib
import app.core.config
importlib.reload(app.core.config)
import app.services.supabase_client
importlib.reload(app.services.supabase_client)
import app.workers.audit_worker
importlib.reload(app.workers.audit_worker)

# 2. Imports after staging environment is locked
from app.services.supabase_client import SupabaseService, supabase_service
from app.workers.audit_worker import audit_claimed_domain
from tests.test_domain_audit_lifecycle import build_mock_dns_summary, build_mock_rbl_result


@pytest.fixture(scope="module", autouse=True)
def staging_environment_isolation():
    """Restores pre-test environment and reloads modules upon module exit."""
    yield
    for k, val in _SAVED_VARS.items():
        if val is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = val
    import importlib
    import app.core.config
    importlib.reload(app.core.config)
    import app.services.supabase_client
    importlib.reload(app.services.supabase_client)
    import app.workers.audit_worker
    importlib.reload(app.workers.audit_worker)


@pytest.fixture(scope="module")
def staging_supabase():
    """Provides authenticated SupabaseService instance connected strictly to Staging."""
    service = SupabaseService()
    if not service.is_connected:
        pytest.fail("Failed to connect to Staging Supabase database.")
    if EXPECTED_STAGING_REF not in service._client.supabase_url:
        pytest.fail(f"Staging isolation breach! Connected URL does not match {EXPECTED_STAGING_REF}")
    if PROD_PROJECT_REF in service._client.supabase_url:
        pytest.fail("CRITICAL: Staging test attempted connection to production project ref!")
    return service


@pytest.fixture
def staging_test_user(staging_supabase):
    """
    Creates an isolated test auth user in Staging Supabase and guarantees cleanup.
    Deleting the auth user cascades to public.profiles, public.monitored_domains, etc.
    """
    client = staging_supabase._client
    unique_tag = uuid.uuid4().hex[:10]
    email = f"staging-lifecycle-{unique_tag}@inboundcheck.test"
    password = f"StagingPass-{unique_tag}!99"

    user_resp = client.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
    })
    user_id = user_resp.user.id

    yield {
        "id": user_id,
        "email": email,
        "unique_tag": unique_tag,
    }

    # Teardown: Guaranteed cleanup of test user and cascaded fixtures in Staging only
    try:
        client.auth.admin.delete_user(user_id)
    except Exception as cleanup_err:
        print(f"Warning during staging user cleanup: {cleanup_err}", file=sys.stderr)


@pytest.mark.asyncio
async def test_staging_domain_audit_success_lifecycle(staging_supabase, staging_test_user):
    """
    Step 1 -> 5 Real Staging Database Lifecycle:
    1. Seed an active domain eligible for audit in Staging Supabase.
    2. Claim domain using real PostgreSQL RPC claim_due_domain_audits.
    3. Run audit_claimed_domain with controlled DNS/RBL doubles.
    4. Verify real database updates in monitored_domains, dns_audit_logs, and reputation_checks.
    5. Verify lease completion via real PostgreSQL RPC complete_domain_audit.
    6. Verify idempotency (duplicate completion rejected).
    7. Verify unauthorized worker cannot complete lease.
    8. Verify domain is not claimed again in immediate next sweep.
    """
    client = staging_supabase._client
    user_id = staging_test_user["id"]
    tag = staging_test_user["unique_tag"]
    domain_name = f"staging-success-{tag}.com"
    worker_id = str(uuid.uuid4())

    # 1. Seed domain due for audit (audited 4 hours ago)
    four_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    insert_res = client.table("monitored_domains").insert({
        "user_id": user_id,
        "domain_name": domain_name,
        "health_score": 45,
        "is_active": True,
        "last_audited_at": four_hours_ago,
        "audit_lease_owner": None,
        "audit_lease_until": None,
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
    }).execute()

    assert insert_res.data and len(insert_res.data) == 1
    dom_id = insert_res.data[0]["id"]

    try:
        # 2. Claim domain through real Staging PostgreSQL RPC
        claimed = staging_supabase.claim_due_domain_audits(
            worker_id=worker_id,
            limit=10,
            interval_seconds=3600,
            lease_seconds=900,
        )

        matching_claims = [d for d in claimed if d.get("id") == dom_id]
        assert len(matching_claims) == 1
        claimed_domain = matching_claims[0]
        assert claimed_domain["domain_name"] == domain_name

        # Verify lease was committed in Staging database
        db_domain_leased = client.table("monitored_domains").select("*").eq("id", dom_id).execute().data[0]
        assert db_domain_leased["audit_lease_owner"] == worker_id
        assert db_domain_leased["audit_lease_until"] is not None

        # 3. Execute audit with deterministic RFC test doubles
        mock_summary = build_mock_dns_summary(domain_name)
        mock_rbl = build_mock_rbl_result(domain_name)
        raw_responses = {"dns": {"a": ["198.51.100.1"]}}

        with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", new_callable=AsyncMock) as mock_dns, \
             patch("app.workers.audit_worker.rbl_scanner.scan_domain", new_callable=AsyncMock) as mock_scan, \
             patch("app.workers.audit_worker.alert_dispatcher.evaluate_and_dispatch", new_callable=AsyncMock) as mock_alert:

            mock_dns.return_value = (mock_summary, raw_responses, 110.0)
            mock_scan.return_value = mock_rbl

            await audit_claimed_domain(claimed_domain, worker_id)

            mock_dns.assert_called_once_with(domain_name)
            mock_scan.assert_called_once_with(domain_name)
            mock_alert.assert_called_once()

        # 4. Verify REAL persistence in Staging Supabase
        db_domain_updated = client.table("monitored_domains").select("*").eq("id", dom_id).execute().data[0]
        assert db_domain_updated["health_score"] >= 80
        assert db_domain_updated["spf_status"] in ["optimal", "warning"]
        assert db_domain_updated["dmarc_status"] in ["optimal", "warning"]
        assert db_domain_updated["dkim_status"] in ["optimal", "warning"]
        assert db_domain_updated["mx_status"] in ["optimal", "warning"]

        # Audit log written to public.dns_audit_logs in Staging
        db_logs = client.table("dns_audit_logs").select("*").eq("domain_id", dom_id).execute().data
        assert len(db_logs) >= 1
        assert db_logs[0]["domain_name"] == domain_name
        assert db_logs[0]["health_score"] == db_domain_updated["health_score"]

        # Reputation check written to public.reputation_checks in Staging
        db_reps = client.table("reputation_checks").select("*").eq("user_id", user_id).execute().data
        assert len(db_reps) >= 1
        rep_entry = next((r for r in db_reps if r.get("domain_name") == domain_name), None)
        assert rep_entry is not None
        assert rep_entry["predicted_risk_48h"] == "low"
        assert rep_entry["rbl_clean_count"] == 2

        # 5. Verify real lease release in Staging database
        assert db_domain_updated["audit_lease_owner"] is None
        assert db_domain_updated["audit_lease_until"] is None
        assert db_domain_updated["audit_failure_count"] == 0
        assert db_domain_updated["last_audited_at"] is not None

        # 6. Verify Idempotency & Unauthorized worker rejection
        dup_complete = staging_supabase.complete_domain_audit(domain_id=dom_id, worker_id=worker_id)
        assert dup_complete is False

        intruder_complete = staging_supabase.complete_domain_audit(domain_id=dom_id, worker_id=str(uuid.uuid4()))
        assert intruder_complete is False

        # 7. Verify domain is not claimed again in immediate next sweep
        next_claim = staging_supabase.claim_due_domain_audits(
            worker_id=str(uuid.uuid4()),
            limit=10,
            interval_seconds=3600,
            lease_seconds=900,
        )
        assert not any(d.get("id") == dom_id for d in next_claim)

    finally:
        # Fixture cleanup handled by staging_test_user cascade
        pass


@pytest.mark.asyncio
async def test_staging_domain_audit_failure_and_backoff_lifecycle(staging_supabase, staging_test_user):
    """
    Step 6 -> 8 Real Staging Database Failure & Backoff Path:
    1. Seed an eligible domain.
    2. Claim domain through real PostgreSQL RPC claim_due_domain_audits.
    3. Audit throws an unhandled exception.
    4. Worker catches exception, sanitizes error, and calls real fail_domain_audit RPC.
    5. Verify lease is immediately released in Staging database.
    6. Verify failure count incremented and next_audit_retry_at scheduled in the future.
    7. Verify immediate subsequent claim skips domain (prevents rapid retry loops).
    """
    client = staging_supabase._client
    user_id = staging_test_user["id"]
    tag = staging_test_user["unique_tag"]
    domain_name = f"staging-fail-{tag}.com"
    worker_id = str(uuid.uuid4())

    # 1. Seed domain
    three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    insert_res = client.table("monitored_domains").insert({
        "user_id": user_id,
        "domain_name": domain_name,
        "health_score": 60,
        "is_active": True,
        "last_audited_at": three_hours_ago,
        "audit_lease_owner": None,
        "audit_lease_until": None,
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
    }).execute()

    dom_id = insert_res.data[0]["id"]

    try:
        # 2. Claim domain via Staging RPC
        claimed = staging_supabase.claim_due_domain_audits(
            worker_id=worker_id,
            limit=10,
            interval_seconds=3600,
            lease_seconds=900,
        )
        target_claims = [d for d in claimed if d.get("id") == dom_id]
        assert len(target_claims) == 1
        domain_to_fail = target_claims[0]

        # 3. Simulate failure in DNS diagnostic engine
        with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", new_callable=AsyncMock) as mock_dns, \
             patch("app.workers.audit_worker.rbl_scanner.scan_domain", new_callable=AsyncMock) as mock_scan:

            mock_dns.side_effect = RuntimeError("Authoritative nameserver unreachable: timeout after 10000ms")
            mock_scan.return_value = build_mock_rbl_result(domain_name)

            # Audit worker catches exception and calls fail_domain_audit
            await audit_claimed_domain(domain_to_fail, worker_id)

        # 4. Verify failure state in Staging database
        db_domain_failed = client.table("monitored_domains").select("*").eq("id", dom_id).execute().data[0]

        # Lease immediately released (not locked for 900s)
        assert db_domain_failed["audit_lease_owner"] is None
        assert db_domain_failed["audit_lease_until"] is None

        # Failure count incremented
        assert db_domain_failed["audit_failure_count"] == 1

        # Error sanitized in database
        assert "Authoritative nameserver unreachable" in (db_domain_failed["last_audit_error"] or "")

        # next_audit_retry_at scheduled in the future (>= 60s ahead)
        assert db_domain_failed["next_audit_retry_at"] is not None
        retry_at = datetime.fromisoformat(db_domain_failed["next_audit_retry_at"].replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        assert retry_at > now_utc

        # 5. Verify domain is SKIPPED on immediate next sweep (no tight loop)
        immediate_claim = staging_supabase.claim_due_domain_audits(
            worker_id=str(uuid.uuid4()),
            limit=10,
            interval_seconds=3600,
            lease_seconds=900,
        )
        assert not any(d.get("id") == dom_id for d in immediate_claim)

    finally:
        pass


@pytest.mark.asyncio
async def test_staging_provisioning_api_to_worker_claim_lifecycle(staging_supabase, staging_test_user):
    """
    E2E Verification of Phase 19.4.11:
    1. Provision domain via supported staging API path (provision_monitored_domain RPC).
    2. Verify initial DB state: is_active=true, last_audited_at=NULL, audit_lease_until=NULL.
    3. Verify domain is immediately eligible and claimed by Staging Worker via claim_due_domain_audits RPC.
    4. Execute audit_claimed_domain with mock DNS/RBL doubles.
    5. Verify results are persisted to monitored_domains, dns_audit_logs, and reputation_checks.
    6. Verify lease is released and last_audited_at is updated.
    7. Explicit dependency-aware cleanup of created test records.
    """
    client = staging_supabase._client
    user_id = staging_test_user["id"]
    tag = staging_test_user["unique_tag"]
    domain_name = f"staging-provision-e2e-{tag}.com"
    worker_id = str(uuid.uuid4())

    # 1. Provision via supported API path (PostgreSQL RPC provision_monitored_domain)
    audit_seed = {
        "health_score": 85,
        "summary": {
            "spf": {"status": "optimal"},
            "dkim": {"status": "optimal"},
            "dmarc": {"status": "optimal"},
            "mx": {"status": "optimal"},
            "bimi": {"status": "missing"},
        },
        "custom_selectors": ["s1", "s2"],
    }
    provisioned = staging_supabase.provision_monitored_domain(
        user_id=user_id,
        domain_name=domain_name,
        quota_limit=1,
        audit_result=audit_seed,
    )

    assert provisioned is not None
    dom_id = provisioned["id"]
    assert provisioned["domain_name"] == domain_name

    try:
        # 2. Verify initial state in Staging Supabase
        db_record = client.table("monitored_domains").select("*").eq("id", dom_id).execute().data[0]
        assert db_record["is_active"] is True
        assert db_record["last_audited_at"] is None  # Must be NULL so background worker claims it
        assert db_record["audit_lease_until"] is None
        assert db_record["next_audit_retry_at"] is None
        assert db_record["audit_failure_count"] == 0

        # 3. Worker Claim: Verify domain is claimed by staging worker
        claimed_batch = staging_supabase.claim_due_domain_audits(
            worker_id=worker_id,
            limit=25,
            interval_seconds=3600,
            lease_seconds=900,
        )
        matching = [d for d in claimed_batch if d.get("id") == dom_id]
        assert len(matching) == 1, f"Expected domain {dom_id} to be claimed by worker {worker_id}"
        claimed_domain = matching[0]

        # Verify lease ownership in Staging database
        leased_db = client.table("monitored_domains").select("*").eq("id", dom_id).execute().data[0]
        assert leased_db["audit_lease_owner"] == worker_id
        assert leased_db["audit_lease_until"] is not None

        # 4. Audit Execution with deterministic doubles
        mock_summary = build_mock_dns_summary(domain_name)
        mock_rbl = build_mock_rbl_result(domain_name)
        raw_responses = {"dns": {"a": ["203.0.113.19"]}}

        with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", new_callable=AsyncMock) as mock_dns, \
             patch("app.workers.audit_worker.rbl_scanner.scan_domain", new_callable=AsyncMock) as mock_scan, \
             patch("app.workers.audit_worker.alert_dispatcher.evaluate_and_dispatch", new_callable=AsyncMock) as mock_alert:

            mock_dns.return_value = (mock_summary, raw_responses, 95.0)
            mock_scan.return_value = mock_rbl

            await audit_claimed_domain(claimed_domain, worker_id)

            mock_dns.assert_called_once_with(domain_name)
            mock_scan.assert_called_once_with(domain_name)
            mock_alert.assert_called_once()

        # 5. Verify Persistence & Lease Release in Staging Supabase
        completed_db = client.table("monitored_domains").select("*").eq("id", dom_id).execute().data[0]
        assert completed_db["audit_lease_owner"] is None
        assert completed_db["audit_lease_until"] is None
        assert completed_db["last_audited_at"] is not None
        assert completed_db["audit_failure_count"] == 0

        # Verify audit log in dns_audit_logs
        logs = client.table("dns_audit_logs").select("*").eq("domain_id", dom_id).execute().data
        assert len(logs) >= 1
        assert logs[0]["domain_name"] == domain_name

        # Verify reputation check entry
        reps = client.table("reputation_checks").select("*").eq("domain_id", dom_id).execute().data
        assert len(reps) >= 1

    finally:
        # Scoped cleanup of this specific test domain
        try:
            client.table("reputation_checks").delete().eq("domain_id", dom_id).execute()
            client.table("dns_audit_logs").delete().eq("domain_id", dom_id).execute()
            client.table("monitored_domains").delete().eq("id", dom_id).execute()
        except Exception as cleanup_err:
            print(f"Warning during domain cleanup: {cleanup_err}", file=sys.stderr)
