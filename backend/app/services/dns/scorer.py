"""
InboundCheck - Deliverability Health Scoring & Rule Engine
==========================================================
Calculates weighted domain deliverability score (0-100%), extracts actionable issues,
and categorizes compliance with modern 2024+ sender requirements (Google, Yahoo, Microsoft).
"""

from typing import Tuple, List, Dict, Any
from app.schemas.dns import (
    DiagnosticSummary,
    DiagnosticIssue,
    CategoryScoreBreakdown,
    DNSRecordFix
)


class DeliverabilityScorer:
    """
    Computes domain deliverability health scores and diagnoses configuration anomalies.
    """

    @staticmethod
    def calculate_health_score(
        domain: str,
        summary: DiagnosticSummary
    ) -> Tuple[int, str, CategoryScoreBreakdown, List[DiagnosticIssue], List[DNSRecordFix]]:
        """
        Evaluate diagnostic summary and return total score, status grade, breakdown, issues, and fix suggestions.
        """
        issues: List[DiagnosticIssue] = []
        fixes: List[DNSRecordFix] = []

        dmarc_score = 0
        spf_score = 0
        dkim_score = 0
        mx_score = 0
        bimi_score = 0

        # 1. DMARC Evaluation (Max 35 pts)
        dmarc = summary.dmarc
        if not dmarc.raw or dmarc.status == "critical" or not dmarc.policy:
            issues.append(DiagnosticIssue(
                id="dmarc-missing",
                severity="critical",
                category="DMARC",
                title="DMARC Policy Record Missing",
                description="Your domain lacks a valid DMARC record. Both Google and Yahoo reject unauthenticated emails from domains without DMARC.",
                impact="High risk of rejection and inability to protect domain from email spoofing and phishing.",
                recommendation="Publish a TXT record at `_dmarc." + domain + "` with at least `p=none` and an `rua` report destination."
            ))
            fixes.append(DNSRecordFix(
                record_type="TXT",
                host=f"_dmarc.{domain}",
                value=f"v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@{domain}; aspf=r; adkim=r;",
                ttl=3600,
                category="DMARC",
                rationale="Enforces quarantine policy while delivering aggregate XML telemetry."
            ))
        else:
            if dmarc.policy == "reject":
                dmarc_score = 35 if dmarc.rua_emails else 32
            elif dmarc.policy == "quarantine":
                dmarc_score = 33 if dmarc.rua_emails else 28
            elif dmarc.policy == "none":
                dmarc_score = 18 if dmarc.rua_emails else 10
                issues.append(DiagnosticIssue(
                    id="dmarc-policy-none",
                    severity="warning",
                    category="DMARC",
                    title="DMARC Policy is Monitoring Only (p=none)",
                    description="Your DMARC policy is set to `none`. While this satisfies baseline monitoring, unauthorized senders can still spoof your domain.",
                    impact="Protective enforcement is inactive. Phishing emails mimicking your brand will not be quarantined.",
                    recommendation="Transition to `p=quarantine` or `p=reject` after verifying all legitimate sender DKIM/SPF alignment."
                ))
                fixes.append(DNSRecordFix(
                    record_type="TXT",
                    host=f"_dmarc.{domain}",
                    value=f"v=DMARC1; p=quarantine; pct=100; rua={dmarc.raw.split('rua=')[1].split(';')[0] if 'rua=' in dmarc.raw else f'mailto:dmarc-reports@{domain}'}; aspf=r; adkim=r;",
                    ttl=3600,
                    category="DMARC",
                    rationale="Upgrade DMARC policy from none to quarantine for active inbox protection."
                ))

            if not dmarc.rua_emails:
                issues.append(DiagnosticIssue(
                    id="dmarc-no-rua",
                    severity="warning",
                    category="DMARC",
                    title="No DMARC Aggregate Reporting Address (rua) Configured",
                    description="Without an `rua` tag, mailbox providers cannot send you daily aggregate reports of authentication failures.",
                    impact="Blindness to unauthorized sending IPs and failing transactional flows.",
                    recommendation="Add `rua=mailto:dmarc-reports@" + domain + "` to your DMARC record."
                ))

            if dmarc.percentage < 100:
                pct_penalty = max(1, int((100 - dmarc.percentage) * 0.1))
                dmarc_score = max(0, dmarc_score - pct_penalty)
                issues.append(DiagnosticIssue(
                    id="dmarc-pct-suboptimal",
                    severity="warning",
                    category="DMARC",
                    title=f"DMARC Percentage is Reduced ({dmarc.percentage}%)",
                    description=f"Policy is applied to only {dmarc.percentage}% of outgoing messages.",
                    impact="Portion of spoofed messages will evade policy enforcement.",
                    recommendation="Increase `pct=100` for full enforcement."
                ))

        # 2. SPF Evaluation (Max 25 pts)
        spf = summary.spf
        if not spf.raw or spf.status == "missing":
            issues.append(DiagnosticIssue(
                id="spf-missing",
                severity="critical",
                category="SPF",
                title="SPF Authentication Record Missing",
                description="No `v=spf1` TXT record detected. Recipient mail servers cannot verify whether your Shopify or SMTP senders are authorized.",
                impact="Severe deliverability degradation; transactional order receipts frequently route to Spam/Junk.",
                recommendation="Publish an SPF TXT record containing all authorized sending mechanisms."
            ))
            fixes.append(DNSRecordFix(
                record_type="TXT",
                host=f"@",
                value="v=spf1 include:shops.shopify.com include:_spf.google.com ~all",
                ttl=3600,
                category="SPF",
                rationale="Authorizes Shopify and Google Workspace transactional senders."
            ))
        else:
            if spf.has_multiple_records:
                issues.append(DiagnosticIssue(
                    id="spf-multiple-records",
                    severity="critical",
                    category="SPF",
                    title="Multiple SPF TXT Records Detected (RFC PermError)",
                    description="RFC 7208 specifies that a domain MUST NOT have multiple SPF TXT records. Mail servers will treat this as a PermError and fail authentication.",
                    impact="Direct email delivery failures across major providers.",
                    recommendation="Merge all SPF mechanisms into a single TXT record."
                ))
            elif spf.exceeds_lookup_limit:
                issues.append(DiagnosticIssue(
                    id="spf-lookup-limit-exceeded",
                    severity="critical",
                    category="SPF",
                    title=f"SPF DNS Lookup Limit Exceeded ({spf.dns_lookup_count}/10 max)",
                    description=f"Your SPF record requires ~{spf.dns_lookup_count} DNS lookups, exceeding the RFC 7208 hard limit of 10 lookups.",
                    impact="Mail servers will throw `PermError` and drop or spam-filter emails when resolving mechanisms beyond the 10th lookup.",
                    recommendation="Flatten your SPF record or use dedicated subdomains for third-party marketing services."
                ))
            elif spf.all_mechanism == "+all":
                issues.append(DiagnosticIssue(
                    id="spf-dangerous-all",
                    severity="critical",
                    category="SPF",
                    title="SPF Record Uses Dangerous '+all' Mechanism",
                    description="Your SPF record explicitly authorizes the entire internet to send email on behalf of your domain.",
                    impact="Permits anyone to forge emails from your store without SPF rejection.",
                    recommendation="Change `+all` to `-all` or `~all` immediately."
                ))
            else:
                if spf.all_mechanism == "-all":
                    spf_score = 25
                elif spf.all_mechanism == "~all":
                    spf_score = 24
                    issues.append(DiagnosticIssue(
                        id="spf-softfail-notice",
                        severity="optimal",
                        category="SPF",
                        title="SPF Uses Softfail (~all) with DMARC Alignment",
                        description="Softfail (~all) is the recommended standard across modern eCommerce platforms (Shopify, Klaviyo, Google Workspace). When paired with DMARC, unauthorized senders are reliably quarantined/rejected.",
                        impact="Full deliverability compliance across Google and Yahoo 2024+ sender guidelines.",
                        recommendation="Your SPF posture is optimal for multi-vendor transactional email routing."
                    ))
                elif spf.all_mechanism == "?all":
                    spf_score = 10
                    issues.append(DiagnosticIssue(
                        id="spf-neutral-all",
                        severity="warning",
                        category="SPF",
                        title="SPF Uses Neutral (?all) Qualifier",
                        description="`?all` designates no policy statement on unauthorized senders.",
                        impact="Mail filters cannot distinguish legitimate servers from attackers.",
                        recommendation="Change qualifier to `~all` or `-all`."
                    ))

        # 3. DKIM Evaluation (Max 25 pts)
        dkim = summary.dkim
        if not dkim.found_selectors:
            issues.append(DiagnosticIssue(
                id="dkim-missing-selectors",
                severity="critical",
                category="DKIM",
                title="No Active DKIM Selectors Discovered",
                description="None of the probed common or custom DKIM selectors yielded valid cryptographic public keys.",
                impact="Outgoing transactional emails cannot be cryptographically verified against sender headers, causing DMARC alignment failures.",
                recommendation="Configure DKIM in your email service provider (Shopify, Klaviyo, Google Workspace) and publish the CNAME/TXT key."
            ))
        else:
            best_key = max([r.key_size_bits or 0 for r in dkim.records], default=0)
            if best_key >= 2048:
                dkim_score = 25
            elif best_key >= 1024:
                dkim_score = 18
                issues.append(DiagnosticIssue(
                    id="dkim-1024-bit-warning",
                    severity="warning",
                    category="DKIM",
                    title="1024-bit DKIM Key in Use (Upgrade Recommended)",
                    description="1024-bit RSA keys are increasingly flagged by high-security enterprise spam filters.",
                    impact="Lower cryptographic trust score.",
                    recommendation="Rotate DKIM key pair to 2048-bit RSA."
                ))
            else:
                dkim_score = 10

        # 4. MX Evaluation (Max 15 pts)
        mx = summary.mx
        if mx.record_count >= 2:
            mx_score = 15
        elif mx.record_count == 1:
            mx_score = 12
            issues.append(DiagnosticIssue(
                id="mx-no-redundancy",
                severity="warning",
                category="MX",
                title="Single MX Record (No Redundancy)",
                description="Only 1 Mail Exchanger host is configured. If this server experiences downtime, bounce-backs and delivery failure reports cannot be received.",
                impact="Incoming delivery failure during primary mail server outage.",
                recommendation="Configure a secondary backup MX record with a higher preference number."
            ))
        else:
            mx_score = 0
            issues.append(DiagnosticIssue(
                id="mx-missing",
                severity="critical",
                category="MX",
                title="No MX Records Found for Domain",
                description="Domain cannot receive inbound mail or return-path bounce notifications.",
                impact="Mail servers will distrust domain for outgoing emails due to lack of inbound response capability.",
                recommendation="Add authoritative MX records for your mail provider."
            ))

        # 5. BIMI Evaluation (Optional Deliverability Trust Bonus: +5 pts)
        # Note: BIMI requires a costly VMC certificate (~$1,500/yr) and is not an obligatory
        # requirement for reaching 100/100 or 'Optimal' inbox placement.
        bimi = summary.bimi
        if bimi.status == "optimal":
            bimi_score = 5
        else:
            bimi_score = 0
            issues.append(DiagnosticIssue(
                id="bimi-optional-bonus",
                severity="optimal",
                category="BIMI",
                title="BIMI Brand Indicator (Optional Bonus)",
                description="Brand Indicators for Message Identification (BIMI) displays your verified brand logo next to emails in Apple Mail and Gmail. It requires an active VMC certificate (~$1,500/yr).",
                impact="Optional trust and brand recognition boost; does not penalize primary inbox placement.",
                recommendation="Optional: Obtain a VMC certificate and publish a `default._bimi` record to earn bonus brand recognition."
            ))

        # Total Calculation: Base score (DMARC 35 + SPF 25 + DKIM 25 + MX 15 = 100) + Optional BIMI bonus (+5)
        # Clamped strictly between 0 and 100.
        total_score = min(100, max(0, dmarc_score + spf_score + dkim_score + mx_score + bimi_score))

        if total_score >= 90:
            overall_status = "optimal"
        elif total_score >= 60:
            overall_status = "warning"
        else:
            overall_status = "critical"

        breakdown = CategoryScoreBreakdown(
            dmarc_score=dmarc_score,
            spf_score=spf_score,
            dkim_score=dkim_score,
            mx_score=mx_score,
            bimi_score=bimi_score
        )

        return total_score, overall_status, breakdown, issues, fixes
