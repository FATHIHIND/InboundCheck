"""
InboundCheck - Automated Seed Inbox Testing Unit & Integration Tests
====================================================================
Verifies:
1. Cryptographic tracking token and seed address generation.
2. Multi-provider folder normalization (Gmail, Yahoo, Outlook).
3. Header authentication result parsing (SPF, DKIM, DMARC).
4. Edge-case timeout handling (10.0s max timeout) and graceful degradation.
5. Simulated multi-provider placement verification (Inbox, Spam, Promotions, Missing).
6. Integration with DeliverabilityScorer (spam penalty & inbox verification).
7. REST API Endpoints:
   - POST /api/v1/seed-testing/generate
   - POST /api/v1/seed-testing/verify
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.schemas.seed_testing import (
    PlacementStatus,
    TargetProvider,
    SeedPlacementResult,
    ProviderPlacement,
)
from app.schemas.dns import (
    DiagnosticSummary,
    DMARCSummary,
    SPFSummary,
    DKIMSummary,
    MXSummary,
    BIMISummary,
    DKIMSelectorResult,
)
from app.services.seed_testing.seed_verifier import SeedVerifier, seed_verifier
from app.services.dns.scorer import DeliverabilityScorer
from tests.conftest import auth_headers


def test_token_and_seed_address_generation():
    """Verify cryptographically random token format and seed recipient address formatting."""
    verifier = SeedVerifier()
    token = verifier.generate_tracking_token("luxurystore.com")
    assert token.startswith("ic_seed_")
    assert len(token) >= 20

    seed_address = verifier.generate_seed_address(token, provider="seed")
    assert f"seed+{token}@" in seed_address
    assert seed_address.endswith("seed.inboundcheck.net")

    session = verifier.create_seed_session("luxurystore.com")
    assert session.tracking_token.startswith("ic_seed_")
    assert session.store_domain == "luxurystore.com"
    assert f"[InboundCheck-{session.tracking_token}]" in session.subject_tag
    assert session.expires_in_seconds == 3600


def test_provider_folder_normalization():
    """Verify folder name and label normalization across Gmail, Yahoo, and Outlook."""
    verifier = SeedVerifier()

    # 1. Gmail normalization
    assert verifier.normalize_folder_placement(TargetProvider.GMAIL, "INBOX") == PlacementStatus.INBOX
    assert verifier.normalize_folder_placement(TargetProvider.GMAIL, "[Gmail]/Spam") == PlacementStatus.SPAM
    assert verifier.normalize_folder_placement(TargetProvider.GMAIL, "INBOX", labels=["CATEGORY_PROMOTIONS"]) == PlacementStatus.PROMOTIONS
    assert verifier.normalize_folder_placement(TargetProvider.GMAIL, "Trash") == PlacementStatus.SPAM

    # 2. Yahoo normalization
    assert verifier.normalize_folder_placement(TargetProvider.YAHOO, "Inbox") == PlacementStatus.INBOX
    assert verifier.normalize_folder_placement(TargetProvider.YAHOO, "Bulk") == PlacementStatus.SPAM
    assert verifier.normalize_folder_placement(TargetProvider.YAHOO, "Spam") == PlacementStatus.SPAM

    # 3. Outlook normalization
    assert verifier.normalize_folder_placement(TargetProvider.OUTLOOK, "Inbox") == PlacementStatus.INBOX
    assert verifier.normalize_folder_placement(TargetProvider.OUTLOOK, "Junk Email") == PlacementStatus.SPAM
    assert verifier.normalize_folder_placement(TargetProvider.OUTLOOK, "Deleted Items") == PlacementStatus.SPAM


def test_header_authentication_parsing():
    """Verify regex extraction of SPF, DKIM, and DMARC results from Authentication-Results headers."""
    verifier = SeedVerifier()

    # Clean passing header
    auth_header = (
        "mx.google.com; dkim=pass header.i=@luxurystore.com header.s=shopify header.b=abcdef; "
        "spf=pass (google.com: domain of orders@luxurystore.com designates 198.51.100.1 as permitted sender) "
        "smtp.mailfrom=orders@luxurystore.com; dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=luxurystore.com"
    )
    spf, dkim, dmarc = verifier.parse_authentication_results(auth_header)
    assert spf == "pass"
    assert dkim == "pass"
    assert dmarc == "pass"

    # Failing header
    failing_header = "spf=fail dkim=fail dmarc=fail"
    spf_f, dkim_f, dmarc_f = verifier.parse_authentication_results(failing_header)
    assert spf_f == "fail"
    assert dkim_f == "fail"
    assert dmarc_f == "fail"

    # Empty header
    spf_e, dkim_e, dmarc_e = verifier.parse_authentication_results("")
    assert spf_e == "unknown"
    assert dkim_e == "unknown"
    assert dmarc_e == "unknown"


@pytest.mark.asyncio
async def test_seed_verifier_100_percent_inbox_placement():
    """Verify placement verification when test email arrives in INBOX for all target providers."""
    verifier = SeedVerifier()
    token = verifier.generate_tracking_token("brandstore.com")

    # Simulate message arrival in primary inbox across Gmail, Yahoo, and Outlook
    for prov in [TargetProvider.GMAIL, TargetProvider.YAHOO, TargetProvider.OUTLOOK]:
        verifier.register_simulated_message(
            token=token,
            provider=prov,
            folder="INBOX",
            headers={
                "Subject": f"Order #1029 Receipt [InboundCheck-{token}]",
                "From": "orders@brandstore.com",
                "To": verifier.generate_seed_address(token),
                "Authentication-Results": "spf=pass dkim=pass dmarc=pass",
                "Message-ID": f"<{token}@{prov.value}.com>",
            }
        )

    result = await verifier.verify_seed_placement(token=token, store_domain="brandstore.com")

    assert result.tracking_token == token
    assert result.overall_placement == "inbox"
    assert result.inbox_rate_pct == 100.0
    assert result.spam_rate_pct == 0.0
    assert result.missing_count == 0
    assert len(result.providers) == 3
    assert any("100% Primary Inbox" in r for r in result.recommendations)


@pytest.mark.asyncio
async def test_seed_verifier_spam_placement_detection():
    """Verify placement detection when one or more providers routes to Spam/Junk."""
    verifier = SeedVerifier()
    token = verifier.generate_tracking_token("spammybrand.com")

    # Gmail: Inbox
    verifier.register_simulated_message(token=token, provider=TargetProvider.GMAIL, folder="INBOX")
    # Yahoo: Bulk (Spam)
    verifier.register_simulated_message(token=token, provider=TargetProvider.YAHOO, folder="Bulk")
    # Outlook: Junk Email
    verifier.register_simulated_message(token=token, provider=TargetProvider.OUTLOOK, folder="Junk Email")

    result = await verifier.verify_seed_placement(token=token, store_domain="spammybrand.com")

    assert result.overall_placement == "spam"
    assert result.spam_rate_pct == pytest.approx(66.7, rel=1e-1)
    assert result.inbox_rate_pct == pytest.approx(33.3, rel=1e-1)
    assert any("Spam/Junk" in r for r in result.recommendations)


@pytest.mark.asyncio
async def test_seed_verifier_timeout_edge_case():
    """Verify that a provider query exceeding the timeout window falls back to MISSING without throwing."""
    verifier = SeedVerifier()
    token = verifier.generate_tracking_token("slowbrand.com")

    # Gmail: Instant delivery
    verifier.register_simulated_message(token=token, provider=TargetProvider.GMAIL, folder="INBOX")
    # Yahoo: 15 second delay (exceeds 1.5s test timeout limit)
    verifier.register_simulated_message(token=token, provider=TargetProvider.YAHOO, folder="INBOX", delay_seconds=15.0)
    # Outlook: Not delivered

    # Verify with 1.0s timeout limit
    result = await verifier.verify_seed_placement(token=token, store_domain="slowbrand.com", timeout_seconds=1.0)

    assert result.tracking_token == token
    yahoo_placement = next(p for p in result.providers if p.provider == TargetProvider.YAHOO)
    assert yahoo_placement.placement == PlacementStatus.MISSING
    assert "timed out" in (yahoo_placement.error_detail or "").lower()

    outlook_placement = next(p for p in result.providers if p.provider == TargetProvider.OUTLOOK)
    assert outlook_placement.placement == PlacementStatus.MISSING


def test_deliverability_scorer_seed_telemetry_integration():
    """Verify that DeliverabilityScorer penalizes spam placement and credits verified inbox placement."""
    # Construct optimal mock DNS summary
    summary = DiagnosticSummary(
        dmarc=DMARCSummary(status="optimal", raw="v=DMARC1; p=reject; rua=mailto:d@luxurystore.com", policy="reject", percentage=100, rua_emails=["d@luxurystore.com"]),
        spf=SPFSummary(status="optimal", raw="v=spf1 include:shops.shopify.com -all", all_mechanism="-all", dns_lookup_count=2),
        dkim=DKIMSummary(status="optimal", records=[DKIMSelectorResult(selector="shopify", status="optimal", record_name="shopify._domainkey.luxurystore.com", key_size_bits=2048, has_public_key=True)], found_selectors=["shopify"]),
        mx=MXSummary(status="optimal", record_count=2),
        bimi=BIMISummary(status="optimal", raw="v=BIMI1;"),
    )

    # 1. Without seed result: DNS-only baseline score
    score_dns_only, status_dns, _, issues_dns, _ = DeliverabilityScorer.calculate_health_score(
        domain="luxurystore.com",
        summary=summary,
        seed_result=None
    )
    assert score_dns_only == 100
    assert status_dns == "optimal"
    assert not any(i.id.startswith("seed-") for i in issues_dns)

    # 2. With 100% verified inbox placement
    inbox_seed_result = SeedPlacementResult(
        tracking_token="token_pass",
        test_email_address="seed+token_pass@seed.inboundcheck.net",
        store_domain="luxurystore.com",
        overall_placement="inbox",
        providers=[],
        inbox_rate_pct=100.0,
        spam_rate_pct=0.0,
        promotions_rate_pct=0.0,
        missing_count=0,
        executed_at="2026-09-16T18:00:00Z",
        execution_time_ms=150.0,
    )
    score_inbox, status_inbox, _, issues_inbox, _ = DeliverabilityScorer.calculate_health_score(
        domain="luxurystore.com",
        summary=summary,
        seed_result=inbox_seed_result
    )
    assert score_inbox == 100
    assert any(i.id == "seed-inbox-verified" for i in issues_inbox)

    # 3. With 100% spam placement (must penalize score and register critical issue)
    spam_seed_result = SeedPlacementResult(
        tracking_token="token_spam",
        test_email_address="seed+token_spam@seed.inboundcheck.net",
        store_domain="luxurystore.com",
        overall_placement="spam",
        providers=[],
        inbox_rate_pct=0.0,
        spam_rate_pct=100.0,
        promotions_rate_pct=0.0,
        missing_count=0,
        executed_at="2026-09-16T18:00:00Z",
        execution_time_ms=180.0,
    )
    score_spam, status_spam, _, issues_spam, _ = DeliverabilityScorer.calculate_health_score(
        domain="luxurystore.com",
        summary=summary,
        seed_result=spam_seed_result
    )
    assert score_spam <= 80  # 100 - 20 pts penalty
    assert any(i.id == "seed-spam-detected" for i in issues_spam)


@pytest.mark.asyncio
async def test_seed_testing_api_endpoints():
    """Verify HTTP API contracts for seed generation and verification."""
    transport = ASGITransport(app=app)
    headers = auth_headers("test-seed-user-1")

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        # 1. POST /api/v1/seed-testing/generate
        gen_res = await ac.post("/api/v1/seed-testing/generate", json={
            "store_domain": "merchantbrand.com",
            "provider": "seed"
        })
        assert gen_res.status_code == 200
        gen_data = gen_res.json()
        assert "tracking_token" in gen_data
        assert "seed_email_address" in gen_data
        assert gen_data["store_domain"] == "merchantbrand.com"
        token = gen_data["tracking_token"]

        # Pre-seed a simulated message for this token
        seed_verifier.register_simulated_message(
            token=token,
            provider=TargetProvider.GMAIL,
            folder="INBOX"
        )

        # 2. POST /api/v1/seed-testing/verify
        verify_res = await ac.post("/api/v1/seed-testing/verify", json={
            "tracking_token": token,
            "store_domain": "merchantbrand.com",
            "timeout_seconds": 2.0
        })
        assert verify_res.status_code == 200
        verify_data = verify_res.json()
        assert verify_data["tracking_token"] == token
        assert "overall_placement" in verify_data
        assert "inbox_rate_pct" in verify_data
        assert len(verify_data["providers"]) == 3

        # 3. Authentication guard check (no headers -> HTTP 401)
        async with AsyncClient(transport=transport, base_url="http://test") as unauth_client:
            unauth_res = await unauth_client.post("/api/v1/seed-testing/generate", json={
                "store_domain": "merchantbrand.com"
            })
            assert unauth_res.status_code == 401
