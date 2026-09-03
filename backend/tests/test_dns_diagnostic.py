"""
InboundCheck - DNS Diagnostic & Scoring Unit Tests
"""

import pytest
import asyncio
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer
from app.services.dns.record_generator import DNSRecordGenerator
from app.schemas.dns import GenerateRecordRequest


@pytest.mark.asyncio
async def test_dns_diagnostic_audit():
    engine = DNSDiagnosticEngine()
    # Test with a well-known public domain (e.g. google.com)
    summary, raw, exec_ms = await engine.audit_domain("google.com")

    assert summary.mx.status in ["optimal", "warning"]
    assert summary.spf.status in ["optimal", "warning"]
    assert exec_ms > 0

    score, status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
        "google.com",
        summary
    )

    assert 0 <= score <= 100
    assert status in ["optimal", "warning", "critical"]
    assert breakdown.spf_max == 25
    assert breakdown.dmarc_max == 35


def test_record_generator():
    req = GenerateRecordRequest(
        domain="myshop.com",
        include_shopify=True,
        include_google=True,
        include_klaviyo=True,
        dmarc_policy="quarantine",
        dmarc_report_email="reports@myshop.com"
    )

    fixes = DNSRecordGenerator.generate_full_stack_records(req)
    assert len(fixes) >= 4  # 1 SPF, 1 DMARC, 3 Shopify DKIM CNAMEs

    spf_fix = next(f for f in fixes if f.category == "SPF")
    assert "include:shops.shopify.com" in spf_fix.value
    assert "include:_spf.google.com" in spf_fix.value
    assert "include:klaviyomail.com" in spf_fix.value

    dmarc_fix = next(f for f in fixes if f.category == "DMARC")
    assert "p=quarantine" in dmarc_fix.value
    assert "rua=mailto:reports@myshop.com" in dmarc_fix.value


def test_deliverability_scorer_reweighting_and_remediation():
    """
    Verify re-weighted deliverability score logic:
    - Remediated domain (DMARC quarantine, SPF ~all, 2048-bit DKIM, MX) scores >= 92/100 ('optimal').
    - Fixes the defect where a fully compliant customer was capped at 83/100.
    - BIMI is an optional bonus (+5 pts) and not required for 100/100.
    """
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

    # 1. Fully remediated standard eCommerce domain (Quarantine, Softfail ~all, 2048 DKIM, 2 MX, no BIMI)
    summary_remediated = DiagnosticSummary(
        mx=MXSummary(
            status="optimal",
            record_count=2,
            records=[
                MXRecordItem(host="mail.brandshop.com", preference=10),
                MXRecordItem(host="backup.brandshop.com", preference=20)
            ],
            raw=["10 mail.brandshop.com", "20 backup.brandshop.com"]
        ),
        spf=SPFSummary(
            status="optimal",
            raw="v=spf1 include:shops.shopify.com include:_spf.google.com ~all",
            all_mechanism="~all",
            dns_lookup_count=3,
            syntax_valid=True
        ),
        dkim=DKIMSummary(
            status="optimal",
            found_selectors=["shopify", "google"],
            records=[
                DKIMSelectorResult(
                    selector="shopify",
                    status="optimal",
                    record_name="shopify._domainkey.brandshop.com",
                    key_size_bits=2048,
                    has_public_key=True
                )
            ]
        ),
        dmarc=DMARCSummary(
            status="optimal",
            raw="v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@brandshop.com;",
            policy="quarantine",
            percentage=100,
            rua_emails=["mailto:dmarc-reports@brandshop.com"],
            syntax_valid=True
        ),
        bimi=BIMISummary(
            status="missing",
            raw=None
        )
    )

    score, status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
        "brandshop.com",
        summary_remediated
    )

    # Must naturally score >= 92 and be Optimal without BIMI
    assert score >= 92, f"Expected score >= 92, got {score}"
    assert status == "optimal"
    assert breakdown.dmarc_score == 33
    assert breakdown.spf_score == 24
    assert breakdown.dkim_score == 25
    assert breakdown.mx_score == 15
    assert breakdown.bimi_score == 0
    assert score == 97  # 33 + 24 + 25 + 15 = 97

    # 2. Fully remediated with single MX record (still >= 92 Optimal)
    summary_single_mx = summary_remediated.model_copy(deep=True)
    summary_single_mx.mx.record_count = 1
    score_single_mx, status_single_mx, _, _, _ = DeliverabilityScorer.calculate_health_score(
        "brandshop.com",
        summary_single_mx
    )
    assert score_single_mx >= 92, f"Expected single MX score >= 92, got {score_single_mx}"
    assert status_single_mx == "optimal"
    assert score_single_mx == 94  # 33 + 24 + 25 + 12 = 94

    # 3. Maximum strict domain (Reject + Hardfail -all + 2048 DKIM + 2 MX) reaches 100/100 without BIMI
    summary_max = summary_remediated.model_copy(deep=True)
    summary_max.dmarc.policy = "reject"
    summary_max.spf.all_mechanism = "-all"
    score_max, status_max, breakdown_max, _, _ = DeliverabilityScorer.calculate_health_score(
        "brandshop.com",
        summary_max
    )
    assert score_max == 100
    assert status_max == "optimal"
    assert breakdown_max.dmarc_score == 35
    assert breakdown_max.spf_score == 25
    assert breakdown_max.dkim_score == 25
    assert breakdown_max.mx_score == 15
    assert breakdown_max.bimi_score == 0

    # 4. Optional BIMI bonus (+5 pts)
    summary_with_bimi = summary_remediated.model_copy(deep=True)
    summary_with_bimi.bimi.status = "optimal"
    score_bimi, _, breakdown_bimi, _, _ = DeliverabilityScorer.calculate_health_score(
        "brandshop.com",
        summary_with_bimi
    )
    assert breakdown_bimi.bimi_score == 5
    assert score_bimi == 100  # min(100, 97 + 5) = 100
