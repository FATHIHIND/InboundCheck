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


def test_anti_ssrf_and_cidr_filtering():
    """
    Verify strict SSRF defense:
    Blocks 127.0.0.0/8, 169.254.0.0/16, 10.0.0.0/8, 172.16.0.0/12,
    192.168.0.0/16, 100.64.0.0/10, ::ffff:0:0/96, and cloud metadata targets.
    """
    engine = DNSDiagnosticEngine()

    blocked_targets = [
        # Loopback (127.0.0.0/8)
        "127.0.0.1",
        "127.1.2.3",
        "localhost",
        # Cloud Metadata / Link-Local (169.254.0.0/16)
        "169.254.169.254",
        "169.254.1.1",
        "metadata.google.internal",
        # Private RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        "10.0.0.1",
        "10.255.255.254",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.1.1",
        "192.168.0.100",
        # Carrier-Grade NAT RFC 6598 (100.64.0.0/10)
        "100.64.0.1",
        "100.127.255.254",
        # IPv4-mapped IPv6 (::ffff:0:0/96)
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "::1",
        # Internal non-routable TLDs
        "server.local",
        "db.internal",
        "cluster.lan",
        "admin.corp"
    ]

    for target in blocked_targets:
        with pytest.raises(ValueError) as excinfo:
            engine._clean_domain(target)
        err_msg = str(excinfo.value).lower()
        assert "restricted" in err_msg or "not allowed" in err_msg or "invalid" in err_msg

    # Valid apex domains must cleanly pass
    assert engine._clean_domain("shopify.com") == "shopify.com"
    assert engine._clean_domain("https://brandshop.com/") == "brandshop.com"
    assert engine._clean_domain("sub.orders.example.co.uk") == "sub.orders.example.co.uk"


def test_domain_normalization_comprehensive():
    """Verify robust normalization across real-world user inputs."""
    # Standard apex domain
    assert DNSDiagnosticEngine.normalize_domain("example.com") == "example.com"
    # Domain with www prefix normalized to apex for email deliverability
    assert DNSDiagnosticEngine.normalize_domain("www.example.com") == "example.com"
    # Specific subdomain preserved
    assert DNSDiagnosticEngine.normalize_domain("mail.example.com") == "mail.example.com"
    assert DNSDiagnosticEngine.normalize_domain("store.myshopify.com") == "store.myshopify.com"
    # Full URL with scheme, path, and port
    assert DNSDiagnosticEngine.normalize_domain("https://brandshop.com:443/products/receipt?id=123#ref") == "brandshop.com"
    assert DNSDiagnosticEngine.normalize_domain("http://www.megastore.com/checkout/") == "megastore.com"
    # Leading/trailing whitespace and trailing dot
    assert DNSDiagnosticEngine.normalize_domain("   acme-corp.org.  ") == "acme-corp.org"

    # Invalid inputs must raise ValueError
    with pytest.raises(ValueError):
        DNSDiagnosticEngine.normalize_domain("")
    with pytest.raises(ValueError):
        DNSDiagnosticEngine.normalize_domain("not-a-domain")
    with pytest.raises(ValueError):
        DNSDiagnosticEngine.normalize_domain("http://localhost:3000")
    with pytest.raises(ValueError):
        DNSDiagnosticEngine.normalize_domain("127.0.0.1")


def test_scorer_evidence_and_checks_summary():
    """Verify DeliverabilityScorer generates evidence, remediation records, and checks summary."""
    from app.schemas.dns import (
        DiagnosticSummary,
        MXSummary,
        MXRecordItem,
        SPFSummary,
        DKIMSummary,
        DMARCSummary,
        BIMISummary,
        DNSRecordsSummary,
        MailInfrastructureSummary,
        ReputationSummary,
    )

    summary = DiagnosticSummary(
        mx=MXSummary(
            status="optimal",
            record_count=2,
            records=[
                MXRecordItem(host="aspmx.l.google.com", preference=1, ipv4=["142.250.185.26"]),
                MXRecordItem(host="alt1.aspmx.l.google.com", preference=5, ipv4=["142.250.185.27"])
            ],
            raw=["1 aspmx.l.google.com", "5 alt1.aspmx.l.google.com"]
        ),
        spf=SPFSummary(
            status="missing",
            raw=None,
            all_mechanism=None,
            syntax_valid=False
        ),
        dkim=DKIMSummary(
            status="missing",
            tested_selectors=["shopify", "google"],
            found_selectors=[],
            records=[]
        ),
        dmarc=DMARCSummary(
            status="critical",
            raw=None,
            policy=None,
            syntax_valid=False
        ),
        bimi=BIMISummary(status="missing"),
        dns_records=DNSRecordsSummary(
            status="warning",
            a_records=["93.184.216.34"],
            ns_records=["ns1.example.com", "ns2.example.com"],
            ns_count=2,
            has_caa=False
        ),
        mail_infrastructure=MailInfrastructureSummary(
            status="optimal",
            mx_hosts_count=2,
            resolved_mail_ips=["142.250.185.26"],
            ptr_records={"142.250.185.26": ["mail.google.com"]},
            all_mx_valid=True,
            has_redundancy=True
        ),
        reputation=ReputationSummary(
            clean_count=10,
            listed_count=0,
            unknown_count=0,
            error_count=0,
            total_providers=10,
            overall_status="clean"
        )
    )

    score, status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
        "mybrand.com",
        summary
    )

    # Health score must reflect missing SPF, DKIM, DMARC
    assert score < 50
    assert status == "critical"

    # Checks summary must be populated
    checks_summary = DeliverabilityScorer.calculate_checks_summary(issues, summary.reputation)
    assert checks_summary.total_checks > 0
    assert checks_summary.failure_count > 0

    risk_level = DeliverabilityScorer.calculate_risk_level(score)
    assert risk_level == "Critical Risk"

    # Every critical issue must contain evidence and remediation record where applicable
    dmarc_issue = next(i for i in issues if i.id == "dmarc-missing")
    assert dmarc_issue.evidence is not None
    assert dmarc_issue.remediation_record is not None
    assert dmarc_issue.remediation_record.record_type == "TXT"
    assert "_dmarc" in dmarc_issue.remediation_record.host

    spf_issue = next(i for i in issues if i.id == "spf-missing")
    assert spf_issue.evidence is not None
    assert spf_issue.remediation_record is not None
    assert "v=spf1" in spf_issue.remediation_record.value
