"""
InboundCheck - Domain Audit End-to-End Lifecycle Integration Tests (Phase 19.1)
================================================================================
Proves the complete domain audit lifecycle across:
1. Atomically claiming eligible domains via lease mechanism.
2. Audit orchestrator invoking concurrent DNS and RBL diagnostics.
3. Passing scan results through persistence layer (audit log, reputation checks, RBL snapshot, alert evaluator).
4. Lease release & completion verification (idempotent, no duplicate completion).
5. Separate failure handling with bounded exponential retry backoff preventing rapid retry loops.
6. Recovery from prior failure state resetting failure counters.
7. Supabase RPC client contract verification.
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.supabase_client import supabase_service
from app.workers.audit_worker import audit_claimed_domain
from app.schemas.dns import (
    DiagnosticSummary,
    MXSummary,
    MXRecordItem,
    SPFSummary,
    DKIMSummary,
    DKIMSelectorResult,
    DMARCSummary,
    BIMISummary,
)
from app.services.dns.rbl_scanner import RBLScanResult, RBLListingResult


@pytest.fixture(autouse=True)
def isolate_supabase_for_lifecycle():
    """Ensure tests are strictly isolated from any live Supabase instance."""
    orig_client = supabase_service._client
    orig_domains = dict(supabase_service._in_memory_domains)
    orig_audit_logs = dict(getattr(supabase_service, "_in_memory_audit_logs", {}))
    orig_reputation = dict(getattr(supabase_service, "_in_memory_reputation", {}))
    orig_rbl = dict(getattr(supabase_service, "_in_memory_rbl_scans", {}))

    supabase_service._client = None
    supabase_service._in_memory_domains.clear()
    if hasattr(supabase_service, "_in_memory_audit_logs"):
        supabase_service._in_memory_audit_logs.clear()
    if hasattr(supabase_service, "_in_memory_reputation"):
        supabase_service._in_memory_reputation.clear()
    if hasattr(supabase_service, "_in_memory_rbl_scans"):
        supabase_service._in_memory_rbl_scans.clear()

    yield

    supabase_service._client = orig_client
    supabase_service._in_memory_domains = orig_domains
    if hasattr(supabase_service, "_in_memory_audit_logs"):
        supabase_service._in_memory_audit_logs = orig_audit_logs
    if hasattr(supabase_service, "_in_memory_reputation"):
        supabase_service._in_memory_reputation = orig_reputation
    if hasattr(supabase_service, "_in_memory_rbl_scans"):
        supabase_service._in_memory_rbl_scans = orig_rbl


def build_mock_dns_summary(domain: str) -> DiagnosticSummary:
    """Build a deterministic, valid DiagnosticSummary fixture."""
    return DiagnosticSummary(
        mx=MXSummary(
            status="optimal",
            record_count=1,
            records=[
                MXRecordItem(
                    host=f"mail.{domain}",
                    preference=10,
                    ipv4=["198.51.100.1"],
                    provider_detected="Google Workspace",
                )
            ],
            raw=[f"10 mail.{domain}"],
            primary_provider="Google Workspace",
        ),
        spf=SPFSummary(
            status="optimal",
            raw="v=spf1 include:_spf.google.com ~all",
            all_mechanism="~all",
            dns_lookup_count=2,
            includes=["_spf.google.com"],
            ip4=[],
            ip6=[],
            has_multiple_records=False,
            exceeds_lookup_limit=False,
            syntax_valid=True,
        ),
        dkim=DKIMSummary(
            status="optimal",
            tested_selectors=["google"],
            found_selectors=["google"],
            records=[
                DKIMSelectorResult(
                    selector="google",
                    status="optimal",
                    record_name=f"google._domainkey.{domain}",
                    raw="v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0...",
                    key_type="rsa",
                    key_size_bits=2048,
                    has_public_key=True,
                )
            ],
        ),
        dmarc=DMARCSummary(
            status="optimal",
            raw=f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}",
            policy="quarantine",
            subdomain_policy=None,
            percentage=100,
            rua_emails=[f"dmarc@{domain}"],
            ruf_emails=[],
            adkim_alignment="r",
            aspf_alignment="r",
            syntax_valid=True,
        ),
        bimi=BIMISummary(status="missing", raw=None, logo_url=None, vmc_url=None),
    )


def build_mock_rbl_result(domain: str) -> RBLScanResult:
    """Build a deterministic, clean RBLScanResult fixture."""
    now_dt = datetime.now(timezone.utc)
    return RBLScanResult(
        domain=domain,
        resolved_ips=["198.51.100.1"],
        results=[
            RBLListingResult(
                provider_id="spamhaus_zen",
                provider_name="Spamhaus ZEN",
                zone="zen.spamhaus.org",
                target_type="ip",
                status="clean",
                severity="none",
                queried_target="198.51.100.1",
                response_codes=[],
                latency_ms=35,
                delisting_url="https://www.spamhaus.org",
                checked_at=now_dt,
            ),
            RBLListingResult(
                provider_id="barracuda",
                provider_name="Barracuda BRBL",
                zone="b.barracudacentral.org",
                target_type="ip",
                status="clean",
                severity="none",
                queried_target="198.51.100.1",
                response_codes=[],
                latency_ms=42,
                delisting_url="https://www.barracudacentral.org",
                checked_at=now_dt,
            ),
        ],
        rbl_clean_count=2,
        rbl_total_count=2,
        rbl_listed_count=0,
        rbl_unknown_count=0,
        rbl_error_count=0,
        overall_status="clean",
        highest_severity="none",
        execution_time_ms=77.0,
        scanned_at=now_dt,
    )


@pytest.mark.asyncio
async def test_domain_audit_end_to_end_success_lifecycle():
    """
    Step 1 -> 4 Success Path:
    1. Eligible domain claimed through lease mechanism.
    2. Audit orchestrator invokes mocked DNS and RBL checks concurrently.
    3. Results are saved to domain record, audit logs, reputation checks, and RBL snapshots.
    4. Lease is completed and released cleanly.
    5. Duplicate completion attempts are rejected (idempotency).
    6. Domain is no longer eligible for claiming in the immediate next cycle.
    """
    user_id = f"user-{uuid.uuid4()}"
    dom_id = str(uuid.uuid4())
    domain_name = "brand-lifecycle-success.com"
    worker_id = str(uuid.uuid4())

    # 1. Seed domain due for audit (audited 3 hours ago)
    three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": domain_name,
        "is_active": True,
        "last_audited_at": three_hours_ago,
        "audit_lease_owner": None,
        "audit_lease_until": None,
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
    }
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    # Verify domain is claimed by worker
    claimed = supabase_service.claim_due_domain_audits(
        worker_id=worker_id,
        limit=10,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed) == 1
    assert claimed[0]["id"] == dom_id
    assert seeded_domain["audit_lease_owner"] == worker_id
    assert seeded_domain["audit_lease_until"] is not None

    # 2. Mock external DNS and RBL checks with deterministic results
    mock_summary = build_mock_dns_summary(domain_name)
    mock_rbl = build_mock_rbl_result(domain_name)
    raw_responses = {"dns": {"a": ["198.51.100.1"]}}

    with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", new_callable=AsyncMock) as mock_dns, \
         patch("app.workers.audit_worker.rbl_scanner.scan_domain", new_callable=AsyncMock) as mock_scan, \
         patch("app.workers.audit_worker.alert_dispatcher.evaluate_and_dispatch", new_callable=AsyncMock) as mock_alert:

        mock_dns.return_value = (mock_summary, raw_responses, 120.0)
        mock_scan.return_value = mock_rbl

        # 3. Execute audit orchestrator
        await audit_claimed_domain(seeded_domain, worker_id)

        # Assert external checks were called with exact cleaned domain
        mock_dns.assert_called_once_with(domain_name)
        mock_scan.assert_called_once_with(domain_name)
        mock_alert.assert_called_once()

    # 4. Verify persistence and telemetry
    # Domain record updated with high compliance score
    assert seeded_domain.get("health_score") is not None
    assert seeded_domain["health_score"] >= 80
    assert seeded_domain.get("spf_status") in ["optimal", "warning"]
    assert seeded_domain.get("dmarc_status") in ["optimal", "warning"]
    assert seeded_domain.get("dkim_status") in ["optimal", "warning"]
    assert seeded_domain.get("mx_status") in ["optimal", "warning"]

    # Audit history recorded
    history = supabase_service.get_audit_history(user_id=user_id, domain_name=domain_name)
    assert len(history) == 1
    assert history[0]["domain_name"] == domain_name
    assert history[0]["health_score"] == seeded_domain["health_score"]
    assert history[0]["spf_status"] in ["optimal", "warning"]
    assert history[0]["dmarc_status"] in ["optimal", "warning"]

    # Reputation checks snapshot recorded
    rep_snapshots = supabase_service._in_memory_reputation.get(user_id, [])
    assert len(rep_snapshots) >= 1
    snap = next((s for s in rep_snapshots if s.get("domain_name") == domain_name and s.get("rbl_clean_count") == 2), None)
    assert snap is not None
    assert snap["predicted_risk_48h"] == "low"

    # RBL scan snapshot recorded
    latest_rbl = supabase_service.get_latest_rbl_scan(user_id=user_id, domain_name=domain_name)
    assert latest_rbl is not None
    assert latest_rbl["overall_status"] == "clean"

    # 5. Verify lease completion and idempotency
    assert seeded_domain["audit_lease_owner"] is None
    assert seeded_domain["audit_lease_until"] is None
    assert seeded_domain["audit_failure_count"] == 0
    assert seeded_domain["next_audit_retry_at"] is None
    assert seeded_domain["last_audited_at"] is not None

    # Idempotent: Subsequent completion attempt must fail (no active lease)
    dup_complete = supabase_service.complete_domain_audit(domain_id=dom_id, worker_id=worker_id)
    assert dup_complete is False

    # Intruder completion attempt must fail
    intruder_complete = supabase_service.complete_domain_audit(domain_id=dom_id, worker_id="intruder-worker")
    assert intruder_complete is False

    # 6. Verify domain is not claimed again in immediate next cycle
    next_claim = supabase_service.claim_due_domain_audits(
        worker_id="another-worker",
        limit=10,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(next_claim) == 0


@pytest.mark.asyncio
async def test_domain_audit_failure_retry_backoff_lifecycle():
    """
    Step 5 Failure & Backoff Path:
    1. Claimed domain fails during DNS audit.
    2. Lease is immediately released (not held locked for remaining lease duration).
    3. Failure count is incremented and next_audit_retry_at is set into the future.
    4. Rapid retry loop is prevented: immediate claim cycle skips this domain.
    5. Consecutive failure yields bounded exponential backoff.
    6. Eventual successful audit resets failure count and clears next_audit_retry_at.
    """
    user_id = f"user-{uuid.uuid4()}"
    dom_id = str(uuid.uuid4())
    domain_name = "brand-lifecycle-fail.com"
    worker_1 = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": domain_name,
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": None,
        "audit_lease_until": None,
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
    }
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    # Worker 1 claims domain
    claimed = supabase_service.claim_due_domain_audits(
        worker_id=worker_1,
        limit=1,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed) == 1
    assert seeded_domain["audit_lease_owner"] == worker_1

    # 1. Simulate authoritative DNS timeout failure
    with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", side_effect=ConnectionResetError("DNS socket timeout token=supersecret")):
        await audit_claimed_domain(seeded_domain, worker_1)

    # 2. Verify lease is released and failure recorded
    assert seeded_domain["audit_lease_owner"] is None
    assert seeded_domain["audit_lease_until"] is None
    assert seeded_domain["audit_failure_count"] == 1
    assert "DNS socket timeout" in seeded_domain["last_audit_error"]
    assert "supersecret" not in seeded_domain["last_audit_error"]  # Sanitization check

    # 3. Verify next_audit_retry_at is in the future (base delay 120s)
    first_retry_iso = seeded_domain.get("next_audit_retry_at")
    assert first_retry_iso is not None
    first_retry_dt = datetime.fromisoformat(first_retry_iso.replace("Z", "+00:00"))
    assert first_retry_dt > now + timedelta(seconds=100)

    # 4. Rapid Retry Loop Prevention: Immediate claim attempt MUST NOT claim this domain
    rapid_claim = supabase_service.claim_due_domain_audits(
        worker_id="worker-fast-retry",
        limit=10,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(rapid_claim) == 0, "Domain under active retry backoff must not be claimed immediately"

    # 5. Simulate time advance past first retry window -> Second failure introduces larger backoff
    worker_2 = str(uuid.uuid4())
    seeded_domain["next_audit_retry_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    claimed_second = supabase_service.claim_due_domain_audits(
        worker_id=worker_2,
        limit=1,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed_second) == 1

    # Second failure
    with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", side_effect=TimeoutError("DNS query expired")):
        await audit_claimed_domain(seeded_domain, worker_2)

    assert seeded_domain["audit_failure_count"] == 2
    second_retry_iso = seeded_domain.get("next_audit_retry_at")
    second_retry_dt = datetime.fromisoformat(second_retry_iso.replace("Z", "+00:00"))

    # Failures = 1 before second failure -> multiplier is 2^1 = 2 (240s base backoff)
    assert second_retry_dt > now + timedelta(seconds=200)

    # 6. Recovery: simulate third attempt succeeding -> resets failure count and retry schedule
    worker_3 = str(uuid.uuid4())
    seeded_domain["next_audit_retry_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    claimed_third = supabase_service.claim_due_domain_audits(
        worker_id=worker_3,
        limit=1,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed_third) == 1

    mock_summary = build_mock_dns_summary(domain_name)
    mock_rbl = build_mock_rbl_result(domain_name)
    with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", new_callable=AsyncMock) as mock_dns, \
         patch("app.workers.audit_worker.rbl_scanner.scan_domain", new_callable=AsyncMock) as mock_scan, \
         patch("app.workers.audit_worker.alert_dispatcher.evaluate_and_dispatch", new_callable=AsyncMock):

        mock_dns.return_value = (mock_summary, {}, 85.0)
        mock_scan.return_value = mock_rbl

        await audit_claimed_domain(seeded_domain, worker_3)

    # Failure metrics fully reset upon successful audit
    assert seeded_domain["audit_lease_owner"] is None
    assert seeded_domain["audit_failure_count"] == 0
    assert seeded_domain["next_audit_retry_at"] is None
    assert seeded_domain["last_audit_error"] is None
    assert seeded_domain["last_audited_at"] is not None


def test_supabase_rpc_boundary_contracts():
    """
    Verify RPC parameter contract:
    Ensure Supabase client method calls to Postgres RPC use exact argument names
    and parameter types matching database migrations.
    """
    mock_client = MagicMock()
    mock_rpc = MagicMock()
    mock_client.rpc.return_value = mock_rpc
    mock_rpc.execute.return_value = MagicMock(data=[{"id": "dom_1", "domain_name": "rpc-test.com"}])

    worker_id = str(uuid.uuid4())
    domain_id = str(uuid.uuid4())

    with patch.object(supabase_service, "_client", mock_client):
        # 1. claim_due_domain_audits RPC call
        claimed = supabase_service.claim_due_domain_audits(
            worker_id=worker_id,
            limit=5,
            interval_seconds=1800,
            lease_seconds=600,
        )
        assert len(claimed) == 1
        mock_client.rpc.assert_called_with(
            "claim_due_domain_audits",
            {
                "p_worker_id": worker_id,
                "p_limit": 5,
                "p_interval": "1800 seconds",
                "p_lease_duration": "600 seconds",
            },
        )

        # 2. complete_domain_audit RPC call
        mock_rpc.execute.return_value = MagicMock(data=True)
        completed = supabase_service.complete_domain_audit(domain_id=domain_id, worker_id=worker_id)
        assert completed is True
        mock_client.rpc.assert_called_with(
            "complete_domain_audit",
            {
                "p_domain_id": domain_id,
                "p_worker_id": worker_id,
            },
        )

        # 3. fail_domain_audit RPC call
        mock_rpc.execute.return_value = MagicMock(data=True)
        failed = supabase_service.fail_domain_audit(
            domain_id=domain_id,
            worker_id=worker_id,
            error="Connection reset by peer",
            base_delay_seconds=120,
            max_delay_seconds=3600,
        )
        assert failed is True
        mock_client.rpc.assert_called_with(
            "fail_domain_audit",
            {
                "p_domain_id": domain_id,
                "p_worker_id": worker_id,
                "p_error": "Connection reset by peer",
                "p_base_delay_seconds": 120,
                "p_max_delay_seconds": 3600,
            },
        )


def test_diagnostic_update_preserves_active_lease_and_blocks_concurrent_claim():
    """
    Phase 19.4.21 Regression Test:
    Proves that update_domain_diagnostic_results:
    1. Updates scores and protocol statuses cleanly.
    2. Strictly preserves audit_lease_owner and audit_lease_until.
    3. Prevents a concurrent second worker from claiming the domain.
    4. Allows the original worker to complete the audit successfully.
    """
    user_id = f"test-user-{uuid.uuid4()}"
    dom_id = str(uuid.uuid4())
    domain_name = "lease-preserve-test.com"
    worker_1 = str(uuid.uuid4())
    worker_2 = str(uuid.uuid4())

    future_lease = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": domain_name,
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": worker_1,
        "audit_lease_until": future_lease,
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
        "health_score": 0,
    }
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    mock_audit = {
        "health_score": 92,
        "summary": {
            "spf": {"status": "optimal"},
            "dkim": {"status": "optimal"},
            "dmarc": {"status": "optimal"},
            "mx": {"status": "optimal"},
            "bimi": {"status": "missing"},
        }
    }

    # Step 1: Update diagnostic results during active audit
    updated = supabase_service.update_domain_diagnostic_results(
        domain_id=dom_id,
        audit_result=mock_audit,
        worker_id=worker_1,
    )
    assert updated is not None
    assert updated["health_score"] == 92
    assert updated["spf_status"] == "optimal"

    # Step 2: ASSERT LEASE IS PRESERVED
    assert seeded_domain["audit_lease_owner"] == worker_1
    assert seeded_domain["audit_lease_until"] == future_lease, "CRITICAL REGRESSION: Lease expiration was cleared!"

    # Step 3: ASSERT WORKER 2 CANNOT STEAL THE LEASE
    claimed_by_worker_2 = supabase_service.claim_due_domain_audits(
        worker_id=worker_2,
        limit=10,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed_by_worker_2) == 0, "CRITICAL RACE: Worker 2 claimed domain while Worker 1 was in-flight!"

    # Step 4: ASSERT WORKER 1 CAN STILL COMPLETE
    completed = supabase_service.complete_domain_audit(domain_id=dom_id, worker_id=worker_1)
    assert completed is True, "Worker 1 completion failed unexpectedly!"
    assert seeded_domain["audit_lease_owner"] is None
    assert seeded_domain["audit_lease_until"] is None
    assert seeded_domain["last_audited_at"] is not None


def test_diagnostic_update_rejects_wrong_worker_lease_owner():
    """Verify that a worker with mismatched worker_id cannot update domain diagnostics."""
    user_id = f"test-user-{uuid.uuid4()}"
    dom_id = str(uuid.uuid4())
    domain_name = "wrong-worker-test.com"
    legit_worker = str(uuid.uuid4())
    intruder_worker = str(uuid.uuid4())

    future_lease = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": domain_name,
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": legit_worker,
        "audit_lease_until": future_lease,
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
        "health_score": 50,
    }
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    mock_audit = {
        "health_score": 99,
        "summary": {"spf": {"status": "optimal"}}
    }

    # Intruder worker attempts update
    result = supabase_service.update_domain_diagnostic_results(
        domain_id=dom_id,
        audit_result=mock_audit,
        worker_id=intruder_worker,
    )
    assert result is None
    # Verify original score and lease owner untouched
    assert seeded_domain["health_score"] == 50
    assert seeded_domain["audit_lease_owner"] == legit_worker


@pytest.mark.asyncio
async def test_audit_worker_aborts_without_alerts_if_lease_lost():
    """
    Verify that if update_domain_diagnostic_results returns None (lease lost during scan),
    the worker immediately aborts and does NOT execute any post-lease-loss operations:
    1. Does NOT write audit history via save_audit_log().
    2. Does NOT persist reputation snapshot to reputation_checks.
    3. Does NOT dispatch merchant alerts via evaluate_and_dispatch().
    4. Does NOT invoke complete_domain_audit() RPC.
    """
    user_id = f"test-user-{uuid.uuid4()}"
    dom_id = str(uuid.uuid4())
    domain_name = "abort-on-lease-loss.com"
    worker_id = str(uuid.uuid4())

    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": domain_name,
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": worker_id,
        "audit_lease_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "next_audit_retry_at": None,
        "audit_failure_count": 0,
        "health_score": 0,
    }
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    mock_summary = build_mock_dns_summary(domain_name)
    mock_rbl = build_mock_rbl_result(domain_name)
    raw_responses = {"dns": {"a": ["198.51.100.1"]}}

    mock_client = MagicMock()
    mock_rep_table = MagicMock()
    mock_rbl_table = MagicMock()

    def table_router(name: str):
        if name == "reputation_checks":
            return mock_rep_table
        if name == "rbl_scans":
            return mock_rbl_table
        return MagicMock()

    mock_client.table.side_effect = table_router

    with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", new_callable=AsyncMock) as mock_dns, \
         patch("app.workers.audit_worker.rbl_scanner.scan_domain", new_callable=AsyncMock) as mock_scan, \
         patch("app.workers.audit_worker.alert_dispatcher.evaluate_and_dispatch", new_callable=AsyncMock) as mock_alert, \
         patch.object(supabase_service, "save_audit_log") as mock_save_log, \
         patch.object(supabase_service, "update_domain_diagnostic_results", return_value=None) as mock_update, \
         patch.object(supabase_service, "complete_domain_audit") as mock_complete, \
         patch.object(supabase_service, "_client", mock_client):

        mock_dns.return_value = (mock_summary, raw_responses, 100.0)
        mock_scan.return_value = mock_rbl

        await audit_claimed_domain(seeded_domain, worker_id)

        # 1. Diagnostic update was attempted with exact worker_id
        mock_update.assert_called_once_with(
            domain_id=dom_id,
            audit_result=mock_update.call_args.kwargs["audit_result"],
            worker_id=worker_id,
        )

        # 2. Audit log persistence MUST NOT have been called
        mock_save_log.assert_not_called()

        # 3. Reputation checks snapshot MUST NOT have been inserted
        mock_rep_table.insert.assert_not_called()

        # 4. Alert dispatch MUST NOT have been called
        mock_alert.assert_not_called()

        # 5. complete_domain_audit MUST NOT have been called
        mock_complete.assert_not_called()


def test_update_domain_diagnostic_results_fails_closed_in_production():
    """Verify that update_domain_diagnostic_results raises DatabaseUnavailableError on DB failure in production and staging."""
    from app.services.supabase_client import DatabaseUnavailableError
    from app.core.config import settings

    for env_name in ["production", "staging"]:
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(f"Connection timeout in {env_name}")

        with patch.object(settings, "ENVIRONMENT", env_name), \
             patch.object(supabase_service, "_client", mock_client):
            with pytest.raises(DatabaseUnavailableError, match="Database diagnostic update failed"):
                supabase_service.update_domain_diagnostic_results(
                    domain_id=str(uuid.uuid4()),
                    audit_result={"health_score": 80},
                    worker_id="test-worker",
                )


def test_update_domain_diagnostic_results_postgrest_contract_success_and_filters():
    """
    Phase 19.4.23 PostgREST Contract Test:
    Verify that:
    1. table("monitored_domains").update(payload) is called with strictly diagnostic fields.
    2. Prohibited lease/audit columns (audit_lease_until, audit_lease_owner, last_audited_at) are absent.
    3. Filter by id = domain_id is applied.
    4. Filter by audit_lease_owner = worker_id is applied when worker_id is provided.
    5. Filter by audit_lease_owner is omitted when worker_id is None.
    6. Returns the updated row dict on successful 1-row update.
    """
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_update = MagicMock()
    mock_eq_id = MagicMock()
    mock_eq_worker = MagicMock()

    mock_client.table.return_value = mock_table
    mock_table.update.return_value = mock_update
    mock_update.eq.return_value = mock_eq_id
    mock_eq_id.eq.return_value = mock_eq_worker

    dom_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    expected_row = {"id": dom_id, "health_score": 95, "spf_status": "optimal"}
    mock_eq_worker.execute.return_value = MagicMock(data=[expected_row])

    mock_audit = {
        "health_score": 95,
        "summary": {
            "spf": {"status": "optimal"},
            "dkim": {"status": "optimal"},
            "dmarc": {"status": "optimal"},
            "mx": {"status": "optimal"},
            "bimi": {"status": "missing"},
        }
    }

    with patch.object(supabase_service, "_client", mock_client):
        result = supabase_service.update_domain_diagnostic_results(
            domain_id=dom_id,
            audit_result=mock_audit,
            worker_id=worker_id,
        )

        assert result == expected_row
        mock_client.table.assert_called_with("monitored_domains")
        mock_table.update.assert_called_once()
        payload = mock_table.update.call_args[0][0]

        # Verify prohibited lease/audit fields are ABSENT
        assert "audit_lease_until" not in payload, "CRITICAL: audit_lease_until must NOT be in update payload"
        assert "audit_lease_owner" not in payload, "CRITICAL: audit_lease_owner must NOT be in update payload"
        assert "last_audited_at" not in payload, "CRITICAL: last_audited_at must NOT be in update payload"

        # Verify diagnostic fields are present and typed correctly
        assert payload["health_score"] == 95
        assert payload["spf_status"] == "optimal"
        assert payload["dkim_status"] == "optimal"
        assert payload["dmarc_status"] == "optimal"
        assert payload["mx_status"] == "optimal"
        assert payload["bimi_status"] == "missing"
        assert payload["audit_failure_count"] == 0
        assert payload["last_audit_error"] is None
        assert payload["next_audit_retry_at"] is None
        assert "last_checked_at" in payload
        assert "updated_at" in payload

        # Verify query filters
        mock_update.eq.assert_called_once_with("id", dom_id)
        mock_eq_id.eq.assert_called_once_with("audit_lease_owner", worker_id)

    # Verify query without worker_id (does not filter on audit_lease_owner)
    mock_table.reset_mock()
    mock_update.reset_mock()
    mock_eq_id.reset_mock()
    mock_eq_id.execute.return_value = MagicMock(data=[expected_row])

    with patch.object(supabase_service, "_client", mock_client):
        result_no_worker = supabase_service.update_domain_diagnostic_results(
            domain_id=dom_id,
            audit_result=mock_audit,
            worker_id=None,
        )
        assert result_no_worker == expected_row
        mock_update.eq.assert_called_once_with("id", dom_id)
        # Second eq (audit_lease_owner) must NOT have been called
        mock_eq_id.eq.assert_not_called()


def test_update_domain_diagnostic_results_postgrest_zero_rows_returns_none():
    """Verify that if PostgREST update matches 0 rows (e.g. lease lost), returns None."""
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_update = MagicMock()
    mock_eq_id = MagicMock()
    mock_eq_worker = MagicMock()

    mock_client.table.return_value = mock_table
    mock_table.update.return_value = mock_update
    mock_update.eq.return_value = mock_eq_id
    mock_eq_id.eq.return_value = mock_eq_worker
    mock_eq_worker.execute.return_value = MagicMock(data=[])  # 0 rows matched

    with patch.object(supabase_service, "_client", mock_client):
        res = supabase_service.update_domain_diagnostic_results(
            domain_id=str(uuid.uuid4()),
            audit_result={"health_score": 80},
            worker_id="test-worker",
        )
        assert res is None


def test_update_domain_diagnostic_results_summary_normalization_types():
    """
    Phase 19.4.23 Summary Normalization Test:
    Verify that update_domain_diagnostic_results supports:
    1. Dict with dict summary.
    2. Dict with Pydantic DiagnosticSummary model.
    3. Top-level Pydantic model with summary.
    """
    from pydantic import BaseModel

    dom_id = str(uuid.uuid4())
    user_id = f"test-user-{uuid.uuid4()}"
    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "normalize-test.com",
        "is_active": True,
        "health_score": 0,
        "spf_status": "missing",
        "dkim_status": "missing",
        "dmarc_status": "missing",
        "mx_status": "missing",
        "bimi_status": "missing",
        "audit_lease_owner": "worker-1",
    }
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    # Type 1: Dict with dict summary
    dict_payload = {
        "health_score": 85,
        "summary": {
            "spf": {"status": "optimal"},
            "dkim": {"status": "warning"},
            "dmarc": {"status": "critical"},
            "mx": {"status": "optimal"},
            "bimi": {"status": "missing"},
        }
    }
    res_dict = supabase_service.update_domain_diagnostic_results(
        domain_id=dom_id,
        audit_result=dict_payload,
        worker_id="worker-1",
    )
    assert res_dict is not None
    assert res_dict["health_score"] == 85
    assert res_dict["spf_status"] == "optimal"
    assert res_dict["dkim_status"] == "warning"
    assert res_dict["dmarc_status"] == "critical"

    # Type 2: Dict with Pydantic DiagnosticSummary model
    pydantic_summary = build_mock_dns_summary("normalize-test.com")
    mixed_payload = {
        "health_score": 93,
        "summary": pydantic_summary,
    }
    res_mixed = supabase_service.update_domain_diagnostic_results(
        domain_id=dom_id,
        audit_result=mixed_payload,
        worker_id="worker-1",
    )
    assert res_mixed is not None
    assert res_mixed["health_score"] == 93
    assert res_mixed["spf_status"] == "optimal"
    assert res_mixed["dkim_status"] == "optimal"
    assert res_mixed["dmarc_status"] == "optimal"
    assert res_mixed["mx_status"] == "optimal"
    assert res_mixed["bimi_status"] == "missing"

    # Type 3: Top-level Pydantic model with summary
    class MockAuditContainer(BaseModel):
        health_score: int
        summary: DiagnosticSummary

    top_level_pydantic = MockAuditContainer(
        health_score=97,
        summary=pydantic_summary,
    )
    res_top = supabase_service.update_domain_diagnostic_results(
        domain_id=dom_id,
        audit_result=top_level_pydantic,
        worker_id="worker-1",
    )
    assert res_top is not None
    assert res_top["health_score"] == 97
    assert res_top["spf_status"] == "optimal"
    assert res_top["dkim_status"] == "optimal"
    assert res_top["dmarc_status"] == "optimal"
