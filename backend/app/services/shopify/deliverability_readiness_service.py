"""
InboundCheck - Shopify Zero-Spam Deliverability Readiness Service
================================================================
Evaluates 6 core deliverability checks for Shopify stores:
1. custom_sending_domain
2. shopify_dkim
3. spf_alignment
4. dmarc_policy
5. spf_conflict
6. shared_pool_exposure
"""

from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

from app.schemas.shopify_readiness import ReadinessCheckItem, ShopifyReadinessResponse
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.supabase_client import supabase_service

logger = logging.getLogger("DeliverabilityReadinessService")

WEIGHTS = {
    "custom_sending_domain": 15,
    "shopify_dkim": 25,
    "spf_alignment": 20,
    "dmarc_policy": 20,
    "spf_conflict": 10,
    "shared_pool_exposure": 10,
}


class DeliverabilityReadinessService:
    """
    Asynchronously assesses a Shopify store domain against the 6 Zero-Spam compliance checks.
    """

    def __init__(self):
        self.diagnostic_engine = DNSDiagnosticEngine()

    async def evaluate_readiness(
        self,
        domain: str,
        user_id: Optional[str] = None,
        store_id: Optional[str] = None
    ) -> ShopifyReadinessResponse:
        clean_domain = domain.strip().lower()
        if clean_domain.startswith("http://") or clean_domain.startswith("https://"):
            clean_domain = clean_domain.split("://", 1)[1].split("/", 1)[0]
        clean_domain = clean_domain.split(":")[0].strip("/")

        # Run DNS audit across all records including Shopify CNAME selectors
        custom_selectors = ["shopify", "shopify2", "shopify3"]
        summary, raw_responses, _ = await self.diagnostic_engine.audit_domain(
            clean_domain,
            custom_selectors=custom_selectors
        )

        checks: List[ReadinessCheckItem] = []

        # -------------------------------------------------------------
        # 1. Custom Sending Domain Check
        # -------------------------------------------------------------
        if clean_domain.endswith(".myshopify.com"):
            checks.append(ReadinessCheckItem(
                check_id="custom_sending_domain",
                title="Custom Sending Domain",
                status="fail",
                impact="critical",
                finding=f"Store is configured with default '{clean_domain}'. Free/default myshopify.com domains trigger bulk spam filtering by Google & Yahoo.",
                remediation="Add and authenticate a custom apex or subdomain (e.g. mail.yourbrand.com) in Shopify Admin -> Settings -> Notifications.",
                dns_record_snippet=None
            ))
        elif clean_domain in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"]:
            checks.append(ReadinessCheckItem(
                check_id="custom_sending_domain",
                title="Custom Sending Domain",
                status="fail",
                impact="critical",
                finding=f"Sending from public webmail '{clean_domain}' fails DMARC p=reject at destination mailboxes.",
                remediation="Switch to an authentic store-owned custom domain.",
                dns_record_snippet=None
            ))
        else:
            checks.append(ReadinessCheckItem(
                check_id="custom_sending_domain",
                title="Custom Sending Domain",
                status="pass",
                impact="high",
                finding=f"Store uses dedicated custom domain '{clean_domain}'. Complies with 2024 mailbox sender identity mandates.",
                remediation="Maintain domain registration and continue monitoring.",
                dns_record_snippet=None
            ))

        # -------------------------------------------------------------
        # 2. Shopify DKIM CNAME Selectors
        # -------------------------------------------------------------
        found_selectors = summary.dkim.found_selectors if summary.dkim else []
        shopify_selectors = [s for s in found_selectors if s.startswith("shopify")]

        if len(shopify_selectors) >= 2 or summary.dkim.status == "optimal":
            checks.append(ReadinessCheckItem(
                check_id="shopify_dkim",
                title="Shopify DKIM Selectors",
                status="pass",
                impact="critical",
                finding=f"Shopify DKIM keys verified ({len(shopify_selectors)}/3 selectors discovered). Cryptographic signing active.",
                remediation="DKIM keys are verified and authenticating transactional messages.",
                dns_record_snippet=None
            ))
        elif len(shopify_selectors) == 1:
            checks.append(ReadinessCheckItem(
                check_id="shopify_dkim",
                title="Shopify DKIM Selectors",
                status="warning",
                impact="high",
                finding="Only 1 of 3 Shopify DKIM CNAME selectors found in DNS. Shopify requires 3 CNAMEs for dual-key rotation.",
                remediation="Add the remaining 2 CNAME records in your DNS provider zone editor.",
                dns_record_snippet=f"shopify2._domainkey.{clean_domain} CNAME dkim2.shops.shopify.com\nshopify3._domainkey.{clean_domain} CNAME dkim3.shops.shopify.com"
            ))
        else:
            checks.append(ReadinessCheckItem(
                check_id="shopify_dkim",
                title="Shopify DKIM Selectors",
                status="fail",
                impact="critical",
                finding="Missing Shopify DKIM CNAME records. Emails sent by Shopify lack valid DKIM signatures for your brand.",
                remediation="Add the 3 Shopify DKIM CNAME records in your DNS management portal.",
                dns_record_snippet=f"shopify._domainkey.{clean_domain} CNAME dkim1.shops.shopify.com\nshopify2._domainkey.{clean_domain} CNAME dkim2.shops.shopify.com\nshopify3._domainkey.{clean_domain} CNAME dkim3.shops.shopify.com"
            ))

        # -------------------------------------------------------------
        # 3. SPF Alignment Check
        # -------------------------------------------------------------
        spf_raw = (summary.spf.raw or "").lower() if summary.spf else ""
        if summary.spf.status == "missing" or not spf_raw:
            checks.append(ReadinessCheckItem(
                check_id="spf_alignment",
                title="SPF Alignment",
                status="fail",
                impact="critical",
                finding="No SPF record found on domain. All outgoing transactional receipts will fail SPF authentication.",
                remediation="Publish an SPF TXT record including Shopify's sending mechanism.",
                dns_record_snippet=f"v=spf1 include:shops.shopify.com ~all"
            ))
        elif "shops.shopify.com" in spf_raw:
            checks.append(ReadinessCheckItem(
                check_id="spf_alignment",
                title="SPF Alignment",
                status="pass",
                impact="high",
                finding="Shopify SPF include (include:shops.shopify.com) is correctly published and aligned.",
                remediation="SPF record correctly delegates sending authorization to Shopify.",
                dns_record_snippet=None
            ))
        else:
            checks.append(ReadinessCheckItem(
                check_id="spf_alignment",
                title="SPF Alignment",
                status="fail",
                impact="critical",
                finding="SPF record exists but is missing 'include:shops.shopify.com'. Receipts will fail SPF validation.",
                remediation="Update your SPF TXT record to include Shopify before the '~all' or '-all' mechanism.",
                dns_record_snippet=f"v=spf1 include:shops.shopify.com ~all"
            ))

        # -------------------------------------------------------------
        # 4. DMARC Policy Check
        # -------------------------------------------------------------
        dmarc_policy = getattr(summary.dmarc, "policy", None)
        dmarc_status = getattr(summary.dmarc, "status", "missing")

        if dmarc_status in ["critical", "missing"] or not dmarc_policy:
            checks.append(ReadinessCheckItem(
                check_id="dmarc_policy",
                title="DMARC Policy Enforcement",
                status="fail",
                impact="critical",
                finding="No DMARC record found at _dmarc." + clean_domain + ". Fails Google/Yahoo 2024 compliance.",
                remediation="Create a TXT record for '_dmarc' with policy p=quarantine or p=reject.",
                dns_record_snippet=f"v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@{clean_domain}; aspf=r; adkim=r;"
            ))
        elif dmarc_policy in ["quarantine", "reject"]:
            checks.append(ReadinessCheckItem(
                check_id="dmarc_policy",
                title="DMARC Policy Enforcement",
                status="pass",
                impact="critical",
                finding=f"Strict DMARC enforcement active (p={dmarc_policy}). Fully compliant with 2024 mailbox provider requirements.",
                remediation="DMARC is properly enforced. Continue monitoring RUA aggregate reports.",
                dns_record_snippet=None
            ))
        else:  # p=none
            checks.append(ReadinessCheckItem(
                check_id="dmarc_policy",
                title="DMARC Policy Enforcement",
                status="warning",
                impact="high",
                finding="DMARC policy is set to 'p=none'. Does not reject or quarantine spoofed emails, risking domain reputation.",
                remediation="Upgrade DMARC policy from 'p=none' to 'p=quarantine' or 'p=reject'.",
                dns_record_snippet=f"v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@{clean_domain}; aspf=r; adkim=r;"
            ))

        # -------------------------------------------------------------
        # 5. SPF Conflict & Lookup Limit
        # -------------------------------------------------------------
        has_multiple_spf = getattr(summary.spf, "has_multiple_records", False)
        lookup_count = getattr(summary.spf, "dns_lookup_count", 0)
        exceeds_lookups = getattr(summary.spf, "exceeds_lookup_limit", False) or lookup_count > 10

        if has_multiple_spf:
            checks.append(ReadinessCheckItem(
                check_id="spf_conflict",
                title="SPF Conflict & Limits",
                status="fail",
                impact="critical",
                finding="Multiple SPF TXT records detected. RFC 7208 strictly forbids more than one SPF record (PermError).",
                remediation="Merge all SPF records into a single TXT entry.",
                dns_record_snippet=None
            ))
        elif exceeds_lookups:
            checks.append(ReadinessCheckItem(
                check_id="spf_conflict",
                title="SPF Conflict & Limits",
                status="fail",
                impact="high",
                finding=f"SPF record exceeds RFC 7208 10-lookup limit ({lookup_count}/10 lookups). Results in SPF PermError.",
                remediation="Flatten your SPF record or remove deprecated ESP includes.",
                dns_record_snippet=None
            ))
        else:
            checks.append(ReadinessCheckItem(
                check_id="spf_conflict",
                title="SPF Conflict & Limits",
                status="pass",
                impact="medium",
                finding=f"Single valid SPF record with {lookup_count}/10 DNS lookups. Zero syntax collisions.",
                remediation="No syntax or lookup ceiling issues.",
                dns_record_snippet=None
            ))

        # -------------------------------------------------------------
        # 6. Shared Pool Exposure Check
        # -------------------------------------------------------------
        dkim_item = next((c for c in checks if c.check_id == "shopify_dkim"), None)
        spf_item = next((c for c in checks if c.check_id == "spf_alignment"), None)
        dmarc_item = next((c for c in checks if c.check_id == "dmarc_policy"), None)

        if dkim_item and dkim_item.status == "pass" and spf_item and spf_item.status == "pass" and dmarc_item and dmarc_item.status == "pass":
            checks.append(ReadinessCheckItem(
                check_id="shared_pool_exposure",
                title="Shared Pool Exposure",
                status="pass",
                impact="medium",
                finding="Store has dedicated DKIM signing and strict DMARC alignment, shielding deliverability from shared IP neighbor noise.",
                remediation="Reputation is securely decoupled from the shared sending pool.",
                dns_record_snippet=None
            ))
        elif dkim_item and dkim_item.status != "pass":
            checks.append(ReadinessCheckItem(
                check_id="shared_pool_exposure",
                title="Shared Pool Exposure",
                status="fail",
                impact="high",
                finding="High shared pool exposure: Without custom DKIM alignment, store receipts route via Shopify's shared sender IP pool.",
                remediation="Authenticate your 3 Shopify DKIM CNAMEs to isolate your store reputation.",
                dns_record_snippet=None
            ))
        else:
            checks.append(ReadinessCheckItem(
                check_id="shared_pool_exposure",
                title="Shared Pool Exposure",
                status="warning",
                impact="medium",
                finding="Partial shared pool insulation: DNS alignment is incomplete, leaving store exposed to shared IP dips.",
                remediation="Enforce DMARC quarantine/reject and verify SPF includes.",
                dns_record_snippet=None
            ))

        # -------------------------------------------------------------
        # Calculate Weighted Readiness Score
        # -------------------------------------------------------------
        total_score = 0
        for item in checks:
            max_weight = WEIGHTS.get(item.check_id, 15)
            if item.status == "pass":
                total_score += max_weight
            elif item.status == "warning":
                total_score += max_weight // 2

        readiness_score = min(100, max(0, total_score))
        passed_count = sum(1 for c in checks if c.status == "pass")

        if readiness_score >= 90:
            status = "ready"
            can_activate = True
            summary_text = "Domain is 100% compliant with 2024 mailbox provider requirements. Zero-Spam delivery is ready to activate."
        elif readiness_score >= 60:
            status = "needs_attention"
            can_activate = False
            summary_text = f"Domain scored {readiness_score}%. Fix remaining warnings before activating Zero-Spam delivery to prevent inbox drops."
        else:
            status = "critical"
            can_activate = False
            summary_text = f"Domain scored {readiness_score}%. Critical DNS authentications are missing; transactional receipts are at high risk of spam folder placement."

        now_iso = datetime.utcnow().isoformat()

        # Update monitored_domains in persistence layer
        if user_id:
            try:
                if supabase_service.is_connected and supabase_service._client:
                    supabase_service._client.table("monitored_domains").update({
                        "deliverability_readiness_score": readiness_score,
                        "deliverability_readiness_updated_at": now_iso
                    }).eq("user_id", user_id).eq("domain_name", clean_domain).execute()
                # Also update in-memory cache
                if user_id in supabase_service._in_memory_domains:
                    for d in supabase_service._in_memory_domains[user_id]:
                        if d.get("domain_name") == clean_domain:
                            d["deliverability_readiness_score"] = readiness_score
                            d["deliverability_readiness_updated_at"] = now_iso
            except Exception as persist_err:
                logger.warning(f"Could not update deliverability_readiness_score in database: {persist_err}")

        return ShopifyReadinessResponse(
            domain=clean_domain,
            readiness_score=readiness_score,
            status=status,
            passed_checks=passed_count,
            total_checks=len(checks),
            checks=checks,
            evaluated_at=now_iso,
            can_activate_zero_spam=can_activate,
            summary=summary_text
        )


deliverability_readiness_service = DeliverabilityReadinessService()
