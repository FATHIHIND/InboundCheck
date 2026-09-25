"""
InboundCheck - Deliverability Health Scoring & Rule Engine
==========================================================
Calculates weighted domain deliverability score (0-100%), extracts actionable issues,
and categorizes compliance with modern 2024+ sender requirements (Google, Yahoo, Microsoft).
"""

from typing import Tuple, List, Dict, Any, Optional
from app.schemas.dns import (
    DiagnosticSummary,
    DiagnosticIssue,
    CategoryScoreBreakdown,
    DNSRecordFix,
    ChecksSummary,
    ReputationSummary,
)


class DeliverabilityScorer:
    """
    Computes domain deliverability health scores and diagnoses configuration anomalies.
    """

    @staticmethod
    def calculate_health_score(
        domain: str,
        summary: DiagnosticSummary,
        seed_result: Optional[Any] = None
    ) -> Tuple[int, str, CategoryScoreBreakdown, List[DiagnosticIssue], List[DNSRecordFix]]:
        """
        Evaluate diagnostic summary and return total score, status grade, breakdown, issues, and fix suggestions.
        Optionally incorporates seed inbox placement telemetry when available.
        """
        issues: List[DiagnosticIssue] = []
        fixes: List[DNSRecordFix] = []

        dmarc_score = 0
        spf_score = 0
        dkim_score = 0
        mx_score = 0
        bimi_score = 0
        seed_penalty = 0
        security_penalty = 0

        # 1. DMARC Evaluation (Max 35 pts)
        dmarc = summary.dmarc
        if not dmarc.raw or dmarc.status == "critical" or not dmarc.policy:
            dmarc_fix = DNSRecordFix(
                record_type="TXT",
                host=f"_dmarc.{domain}",
                value=f"v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@{domain}; aspf=r; adkim=r;",
                ttl=3600,
                category="DMARC",
                rationale="Enforces quarantine policy while delivering aggregate XML telemetry."
            )
            issues.append(DiagnosticIssue(
                id="dmarc-missing",
                severity="critical",
                category="DMARC",
                title="DMARC Policy Record Missing",
                description="Your domain lacks a valid DMARC record. Both Google and Yahoo reject unauthenticated emails from domains without DMARC.",
                impact="High risk of rejection and inability to protect domain from email spoofing and phishing.",
                recommendation="Publish a TXT record at `_dmarc." + domain + "` with at least `p=none` and an `rua` report destination.",
                evidence=f"No DMARC TXT record detected at `_dmarc.{domain}`",
                remediation_record=dmarc_fix
            ))
            fixes.append(dmarc_fix)
        else:
            if dmarc.policy == "reject":
                dmarc_score = 35 if dmarc.rua_emails else 32
            elif dmarc.policy == "quarantine":
                dmarc_score = 33 if dmarc.rua_emails else 28
            elif dmarc.policy == "none":
                dmarc_score = 18 if dmarc.rua_emails else 10
                rua_part = dmarc.raw.split('rua=')[1].split(';')[0] if 'rua=' in dmarc.raw else f'mailto:dmarc-reports@{domain}'
                dmarc_upgrade_fix = DNSRecordFix(
                    record_type="TXT",
                    host=f"_dmarc.{domain}",
                    value=f"v=DMARC1; p=quarantine; pct=100; rua={rua_part}; aspf=r; adkim=r;",
                    ttl=3600,
                    category="DMARC",
                    rationale="Upgrade DMARC policy from none to quarantine for active inbox protection."
                )
                issues.append(DiagnosticIssue(
                    id="dmarc-policy-none",
                    severity="warning",
                    category="DMARC",
                    title="DMARC Policy is Monitoring Only (p=none)",
                    description="Your DMARC policy is set to `none`. While this satisfies baseline monitoring, unauthorized senders can still spoof your domain.",
                    impact="Protective enforcement is inactive. Phishing emails mimicking your brand will not be quarantined.",
                    recommendation="Transition to `p=quarantine` or `p=reject` after verifying all legitimate sender DKIM/SPF alignment.",
                    evidence=f"Current record: `{dmarc.raw}` (p=none)",
                    remediation_record=dmarc_upgrade_fix
                ))
                fixes.append(dmarc_upgrade_fix)

            if not dmarc.rua_emails:
                issues.append(DiagnosticIssue(
                    id="dmarc-no-rua",
                    severity="warning",
                    category="DMARC",
                    title="No DMARC Aggregate Reporting Address (rua) Configured",
                    description="Without an `rua` tag, mailbox providers cannot send you daily aggregate reports of authentication failures.",
                    impact="Blindness to unauthorized sending IPs and failing transactional flows.",
                    recommendation="Add `rua=mailto:dmarc-reports@" + domain + "` to your DMARC record.",
                    evidence=f"Record `{dmarc.raw}` lacks 'rua=' mailto destination."
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
                    recommendation="Increase `pct=100` for full enforcement.",
                    evidence=f"DMARC 'pct={dmarc.percentage}'"
                ))

        # 2. SPF Evaluation (Max 25 pts)
        spf = summary.spf
        if not spf.raw or spf.status == "missing":
            spf_fix = DNSRecordFix(
                record_type="TXT",
                host=f"@",
                value="v=spf1 include:shops.shopify.com include:_spf.google.com ~all",
                ttl=3600,
                category="SPF",
                rationale="Authorizes Shopify and Google Workspace transactional senders."
            )
            issues.append(DiagnosticIssue(
                id="spf-missing",
                severity="critical",
                category="SPF",
                title="SPF Authentication Record Missing",
                description="No `v=spf1` TXT record detected. Recipient mail servers cannot verify whether your Shopify or SMTP senders are authorized.",
                impact="Severe deliverability degradation; transactional order receipts frequently route to Spam/Junk.",
                recommendation="Publish an SPF TXT record containing all authorized sending mechanisms.",
                evidence=f"No SPF TXT record found on apex @{domain}",
                remediation_record=spf_fix
            ))
            fixes.append(spf_fix)
        else:
            if spf.has_multiple_records:
                issues.append(DiagnosticIssue(
                    id="spf-multiple-records",
                    severity="critical",
                    category="SPF",
                    title="Multiple SPF TXT Records Detected (RFC PermError)",
                    description="RFC 7208 specifies that a domain MUST NOT have multiple SPF TXT records. Mail servers will treat this as a PermError and fail authentication.",
                    impact="Direct email delivery failures across major providers.",
                    recommendation="Merge all SPF mechanisms into a single TXT record.",
                    evidence=f"Detected multiple SPF records on {domain}"
                ))
            elif spf.exceeds_lookup_limit:
                issues.append(DiagnosticIssue(
                    id="spf-lookup-limit-exceeded",
                    severity="critical",
                    category="SPF",
                    title=f"SPF DNS Lookup Limit Exceeded ({spf.dns_lookup_count}/10 max)",
                    description=f"Your SPF record requires ~{spf.dns_lookup_count} DNS lookups, exceeding the RFC 7208 hard limit of 10 lookups.",
                    impact="Mail servers will throw `PermError` and drop or spam-filter emails when resolving mechanisms beyond the 10th lookup.",
                    recommendation="Flatten your SPF record or use dedicated subdomains for third-party marketing services.",
                    evidence=f"Computed DNS lookup count: {spf.dns_lookup_count} (Limit: 10)"
                ))
            elif spf.all_mechanism == "+all":
                spf_all_fix = DNSRecordFix(
                    record_type="TXT",
                    host="@",
                    value=spf.raw.replace("+all", "~all"),
                    ttl=3600,
                    category="SPF",
                    rationale="Replaces insecure +all with standard ~all softfail."
                )
                issues.append(DiagnosticIssue(
                    id="spf-dangerous-all",
                    severity="critical",
                    category="SPF",
                    title="SPF Record Uses Dangerous '+all' Mechanism",
                    description="Your SPF record explicitly authorizes the entire internet to send email on behalf of your domain.",
                    impact="Permits anyone to forge emails from your store without SPF rejection.",
                    recommendation="Change `+all` to `-all` or `~all` immediately.",
                    evidence=f"SPF record `{spf.raw}` terminates with '+all'",
                    remediation_record=spf_all_fix
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
                        recommendation="Your SPF posture is optimal for multi-vendor transactional email routing.",
                        evidence=f"Published record: `{spf.raw}`"
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
                        recommendation="Change qualifier to `~all` or `-all`.",
                        evidence=f"Published record: `{spf.raw}`"
                    ))

        # 3. DKIM Evaluation (Max 25 pts)
        dkim = summary.dkim
        if not dkim.found_selectors:
            dkim_fix = DNSRecordFix(
                record_type="CNAME",
                host=f"shopify._domainkey.{domain}",
                value="dkim1.custom.shopify.com.",
                ttl=3600,
                category="DKIM",
                rationale="Shopify primary DKIM signing key."
            )
            issues.append(DiagnosticIssue(
                id="dkim-missing-selectors",
                severity="critical",
                category="DKIM",
                title="No Active DKIM Selectors Discovered",
                description="None of the probed common or custom DKIM selectors yielded valid cryptographic public keys.",
                impact="Outgoing transactional emails cannot be cryptographically verified against sender headers, causing DMARC alignment failures.",
                recommendation="Configure DKIM in your email service provider (Shopify, Klaviyo, Google Workspace) and publish the CNAME/TXT key.",
                evidence=f"Tested selectors: {', '.join(dkim.tested_selectors)}",
                remediation_record=dkim_fix
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
                    recommendation="Rotate DKIM key pair to 2048-bit RSA.",
                    evidence=f"Discovered key size: {best_key} bits"
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
                recommendation="Configure a secondary backup MX record with a higher preference number.",
                evidence=f"Found 1 MX host: {mx.records[0].host if mx.records else 'none'}"
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
                recommendation="Add authoritative MX records for your mail provider.",
                evidence=f"0 MX records resolved for {domain}"
            ))

        # 5. BIMI Evaluation (Optional Bonus: +5 pts)
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
                recommendation="Optional: Obtain a VMC certificate and publish a `default._bimi` record to earn bonus brand recognition.",
                evidence=f"BIMI status: {bimi.status}"
            ))

        # 6. Core DNS Infrastructure Evaluation (DNS Records)
        dns_rec = summary.dns_records
        if dns_rec:
            if dns_rec.has_apex_cname:
                security_penalty += 15
                issues.append(DiagnosticIssue(
                    id="dns-apex-cname",
                    severity="critical",
                    category="DNS",
                    title="Apex Domain CNAME Record Detected (RFC 1912 / RFC 2181 Error)",
                    description="Your zone apex has a CNAME record. RFC 1912 §2.4 specifies that if a CNAME record is present, no other records (NS, SOA, MX, TXT) can exist for that name.",
                    impact="Severe DNS instability. Mail servers may fail to resolve MX or TXT records intermittently.",
                    recommendation="Replace the apex CNAME with standard A/AAAA address records, or use DNS provider CNAME flattening / ANAME.",
                    evidence=f"Apex CNAME targets: {', '.join(dns_rec.cname_records)}"
                ))

            if dns_rec.ns_count < 2 and dns_rec.ns_count > 0:
                security_penalty += 5
                issues.append(DiagnosticIssue(
                    id="dns-single-ns",
                    severity="warning",
                    category="DNS",
                    title="Insufficient Authoritative Nameserver Redundancy",
                    description=f"Found only {dns_rec.ns_count} authoritative nameserver. RFC 2182 requires at least two independent nameservers on diverse network links.",
                    impact="Single point of failure for all domain lookups during provider outages.",
                    recommendation="Configure at least two independent authoritative nameservers.",
                    evidence=f"Configured nameservers: {', '.join(dns_rec.ns_records)}"
                ))

            if not dns_rec.has_caa:
                caa_fix = DNSRecordFix(
                    record_type="CAA",
                    host="@",
                    value='0 issue "letsencrypt.org"',
                    ttl=3600,
                    category="DNS",
                    rationale="Authorizes Let's Encrypt to issue SSL/TLS certificates for your domain."
                )
                issues.append(DiagnosticIssue(
                    id="dns-missing-caa",
                    severity="warning",
                    category="DNS",
                    title="No Certificate Authority Authorization (CAA) Records Published",
                    description="CAA records specify which Certificate Authorities are authorized to issue SSL/TLS certificates for your domain (RFC 6844).",
                    impact="Domain is exposed to rogue or mis-issued SSL/TLS certificates.",
                    recommendation="Publish CAA records authorizing your chosen certificate authorities (e.g. Let's Encrypt, Cloudflare).",
                    evidence="0 CAA records resolved on apex",
                    remediation_record=caa_fix
                ))
                fixes.append(caa_fix)

            if not dns_rec.a_records and not dns_rec.aaaa_records and dns_rec.ns_records:
                security_penalty += 5
                issues.append(DiagnosticIssue(
                    id="dns-no-ip",
                    severity="warning",
                    category="DNS",
                    title="Domain Lacks A or AAAA Host Address Records",
                    description="No IPv4 (A) or IPv6 (AAAA) address records resolved for this apex domain.",
                    impact="Domain cannot serve web traffic or resolve mail routing when MX falls back to address records.",
                    recommendation="Add A/AAAA address records pointing to your web hosting server.",
                    evidence="0 A/AAAA address records found"
                ))

        # 7. Mail Infrastructure Evaluation (MX host resolution, private IP, PTR reverse DNS)
        mail_infra = summary.mail_infrastructure
        if mail_infra:
            if mail_infra.has_private_ip:
                security_penalty += 25
                issues.append(DiagnosticIssue(
                    id="mx-private-ip",
                    severity="critical",
                    category="INFRASTRUCTURE",
                    title="Mail Server Resolves to Private / Restricted IP Address",
                    description="One or more MX hosts resolve to internal or non-routable private IP addresses.",
                    impact="Inbound email from the public internet will fail completely.",
                    recommendation="Point your MX records to public, internet-routable mail servers.",
                    evidence=f"Resolved mail IPs: {mail_infra.resolved_mail_ips}"
                ))

            if mail_infra.has_cname_mx:
                security_penalty += 5
                issues.append(DiagnosticIssue(
                    id="mx-points-to-cname",
                    severity="warning",
                    category="INFRASTRUCTURE",
                    title="MX Target Points to CNAME Alias (RFC 2181 §10.3 Violation)",
                    description="RFC 2181 §10.3 requires MX records to point to a canonical domain name with address records (A/AAAA), not a CNAME alias.",
                    impact="Strict mail servers (Postfix, Exim) will log warnings or delay mail delivery.",
                    recommendation="Update your MX record to point directly to the mail server's canonical hostname.",
                    evidence="MX record targets a CNAME alias"
                ))

            missing_ptrs = [ip for ip, ptrs in mail_infra.ptr_records.items() if not ptrs]
            if missing_ptrs:
                security_penalty += 5
                issues.append(DiagnosticIssue(
                    id="mail-missing-ptr",
                    severity="warning",
                    category="INFRASTRUCTURE",
                    title="Reverse DNS (PTR) Record Missing for Mail Server",
                    description="One or more resolved mail server IPs lack a valid reverse DNS (PTR) record.",
                    impact="Major mailbox providers (Gmail, Yahoo, Outlook) penalize or reject mail originating from IPs without forward-confirmed reverse DNS (FCrDNS).",
                    recommendation="Configure reverse DNS PTR records with your mail hosting provider or ISP.",
                    evidence=f"Mail server IPs lacking PTR: {', '.join(missing_ptrs)}"
                ))

        # 8. Reputation & DNSBL Blacklist Evaluation
        rep = summary.reputation
        if rep:
            if rep.listed_count > 0:
                rep_penalty = min(40, rep.listed_count * 20)
                security_penalty += rep_penalty
                listed_names = [l.get("provider_name", "DNSBL") for l in rep.listings if l.get("status") == "listed"]
                issues.append(DiagnosticIssue(
                    id="rbl-listed",
                    severity="critical",
                    category="REPUTATION",
                    title=f"Domain or Mail Server Listed on {rep.listed_count} RBL Blacklist(s)",
                    description=f"Active listings detected on: {', '.join(listed_names)}. Blacklists cause immediate spam classification or bounce rejections.",
                    impact="Primary inbox placement drops to 0% across recipient mailbox networks using listed providers.",
                    recommendation="Request delisting immediately using the provider delisting links and investigate sending volume/complaints.",
                    evidence=f"Listed on: {', '.join(listed_names)}"
                ))
            elif rep.overall_status in ["partial", "unavailable"] and rep.listed_count == 0:
                issues.append(DiagnosticIssue(
                    id="rbl-partial-notice",
                    severity="optimal",
                    category="REPUTATION",
                    title="Blacklist Reputation Probed (Provider Volume Notice)",
                    description=f"Reputation check verified {rep.clean_count} clean providers. Some commercial zones returned volume limitation notices on shared resolvers.",
                    impact="No active blacklists detected on responsive authoritative providers.",
                    recommendation="Your domain is clean on all answering authoritative reputation providers.",
                    evidence=f"Clean: {rep.clean_count}/{rep.total_providers}, Volume notices: {rep.unknown_count + rep.error_count}"
                ))

        # 9. Seed Placement Telemetry Integration (Optional)
        if seed_result is not None:
            spam_rate = getattr(seed_result, "spam_rate_pct", 0.0)
            inbox_rate = getattr(seed_result, "inbox_rate_pct", 0.0)
            promotions_rate = getattr(seed_result, "promotions_rate_pct", 0.0)

            if spam_rate > 0:
                seed_penalty = min(25, int((spam_rate / 100.0) * 20))
                issues.append(DiagnosticIssue(
                    id="seed-spam-detected",
                    severity="critical",
                    category="Inbox Placement",
                    title=f"Seed Inbox Placement: Filtered to Spam ({spam_rate:.0f}% spam rate)",
                    description="Real-world transactional order receipts routed to Spam/Junk at major mailbox providers.",
                    impact="Customers miss critical order receipts and tracking updates, generating chargebacks and customer support friction.",
                    recommendation="Review content spam signals, ensure full DKIM selector alignment, and verify sender IP reputation.",
                    evidence=f"Spam placement rate: {spam_rate:.1f}%"
                ))
            elif inbox_rate == 100.0:
                issues.append(DiagnosticIssue(
                    id="seed-inbox-verified",
                    severity="optimal",
                    category="Inbox Placement",
                    title="100% Primary Inbox Delivery Verified",
                    description="Test order receipts landed directly in the primary inbox across Gmail, Yahoo, and Outlook seed mailboxes.",
                    impact="Order confirmation and shipping update receipts reach customer primary inboxes reliably.",
                    recommendation="Maintain verified authentication records.",
                    evidence="100% primary inbox delivery across test seed mailboxes"
                ))
            elif promotions_rate > 0:
                issues.append(DiagnosticIssue(
                    id="seed-promotions-tab",
                    severity="warning",
                    category="Inbox Placement",
                    title=f"Receipt Filtered to Promotions Tab ({promotions_rate:.0f}%)",
                    description="Mailbox provider categorized transactional order email as promotional marketing.",
                    impact="Customers may overlook time-sensitive tracking numbers and order details.",
                    recommendation="Remove marketing discount codes and promotional language from transactional email templates.",
                    evidence=f"Promotions tab rate: {promotions_rate:.1f}%"
                ))

        # Total Calculation: Base score (DMARC 35 + SPF 25 + DKIM 25 + MX 15 = 100) + Optional BIMI bonus (+5) - Seed Penalty - Security Penalty
        base_score = min(100, max(0, dmarc_score + spf_score + dkim_score + mx_score + bimi_score))
        total_score = min(100, max(0, base_score - seed_penalty - security_penalty))

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

    @staticmethod
    def calculate_checks_summary(
        issues: List[DiagnosticIssue],
        reputation: Optional[ReputationSummary] = None
    ) -> ChecksSummary:
        """Aggregate total checks, passed, warning, failure, and unavailable counts."""
        passed = sum(1 for i in issues if i.severity == "optimal")
        warnings = sum(1 for i in issues if i.severity == "warning")
        failures = sum(1 for i in issues if i.severity == "critical")
        unavailable = reputation.error_count if (reputation and reputation.overall_status == "unavailable") else 0
        total = passed + warnings + failures + unavailable
        return ChecksSummary(
            total_checks=total,
            passed=passed,
            passed_count=passed,
            warnings=warnings,
            warning_count=warnings,
            failures=failures,
            failure_count=failures,
            unavailable=unavailable,
            unavailable_count=unavailable,
        )

    @staticmethod
    def calculate_risk_level(health_score: int) -> str:
        """Convert 0-100 deliverability health score to enterprise risk tier."""
        if health_score >= 90:
            return "Low Risk"
        elif health_score >= 70:
            return "Medium Risk"
        elif health_score >= 50:
            return "High Risk"
        else:
            return "Critical Risk"
