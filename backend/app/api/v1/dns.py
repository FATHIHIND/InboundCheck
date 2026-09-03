"""
InboundCheck - DNS API Routes (v1)
==================================
Endpoints for real-time DNS diagnostic audits, health scoring, record generation, and automated Telegram notification.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from typing import List
import logging

from app.core.config import settings
from app.core.security import get_current_user_id
from app.schemas.dns import (
    DNSAuditRequest,
    DNSAuditResponse,
    GenerateRecordRequest,
    DNSRecordFix
)
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine, DEFAULT_DKIM_SELECTORS
from app.services.dns.scorer import DeliverabilityScorer
from app.services.dns.record_generator import DNSRecordGenerator
from app.services.failover.omnichannel_service import telegram_alert_service

logger = logging.getLogger("DNSRoutes")

router = APIRouter(prefix="/dns", tags=["DNS Diagnostics"])
diagnostic_engine = DNSDiagnosticEngine()


@router.post("/audit", response_model=DNSAuditResponse)
async def audit_domain(
    request: DNSAuditRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Perform a comprehensive, asynchronous DNS deliverability audit for a domain.
    Audits MX, SPF (syntax & RFC 7208 lookup limits), DKIM selectors, DMARC policies, and BIMI.
    Calculates unified Domain Health Score (0-100%) and triggers Telegram alert if verification passes.
    """
    try:
        clean_domain = request.domain.strip().lower()
        if not clean_domain or len(clean_domain) < 3:
            raise HTTPException(status_code=400, detail="A valid domain name is required.")

        summary, raw_responses, exec_ms = await diagnostic_engine.audit_domain(
            domain=clean_domain,
            custom_selectors=request.selectors
        )

        health_score, overall_status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
            domain=clean_domain,
            summary=summary
        )

        # Closed-loop Telegram Alert: Notify when domain is verified and healthy (Optimal >= 90%)
        if health_score >= 90:
            try:
                alert_text = (
                    f"🎉 *INBOUNDCHECK DNS VERIFICATION CONFIRMED*\n\n"
                    f"🏬 *Domain:* `{clean_domain}`\n"
                    f"🛡️ *Health Score:* `{health_score}%` ({overall_status.upper()})\n"
                    f"⚡ *SPF:* {summary.spf.status.upper()} ({summary.spf.dns_lookup_count}/10 lookups)\n"
                    f"🔑 *DKIM:* {summary.dkim.status.upper()} ({len(summary.dkim.found_selectors)} selectors active)\n"
                    f"📜 *DMARC:* {summary.dmarc.status.upper()} (`p={summary.dmarc.policy or 'none'}`)\n\n"
                    f"✅ *Status:* Primary inbox delivery active. All transactional receipts protected."
                )
                await telegram_alert_service.send_telegram_alert(
                    bot_token=settings.TELEGRAM_BOT_TOKEN or "7198234891:AAH8Fj90qWz1x9_example",
                    chat_id=settings.TELEGRAM_CHAT_ID or "@inboundcheck_alerts",
                    text=alert_text
                )
            except Exception as tg_err:
                logger.warning(f"Telegram notification in DNS audit skipped: {tg_err}")

        return DNSAuditResponse(
            domain=clean_domain,
            health_score=health_score,
            status=overall_status,
            timestamp=datetime.utcnow(),
            execution_time_ms=exec_ms,
            category_scores=breakdown,
            summary=summary,
            issues=issues,
            fixes=fixes,
            raw_responses=raw_responses
        )
    except Exception as e:
        logger.error(f"Error executing DNS audit for {request.domain}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute DNS diagnostic audit"
        )


@router.post("/generate-records", response_model=List[DNSRecordFix])
async def generate_dns_records(
    request: GenerateRecordRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Generate customized, compliant SPF, DKIM, and DMARC DNS records
    tailored to the merchant's specific eCommerce stack (Shopify, Google Workspace, Klaviyo, etc.).
    """
    try:
        return DNSRecordGenerator.generate_full_stack_records(request)
    except Exception as e:
        logger.error(f"Error generating DNS records: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate DNS records"
        )


@router.get("/selectors")
async def get_recommended_selectors():
    """
    Return popular eCommerce and ESP DKIM selectors supported by InboundCheck.
    """
    return {
        "default_selectors": DEFAULT_DKIM_SELECTORS,
        "providers": {
            "shopify": ["shopify", "shopify2", "shopify3"],
            "google_workspace": ["google"],
            "klaviyo": ["k1", "s1", "kl"],
            "sendgrid": ["s1", "s2", "smtpapi"],
            "microsoft_365": ["selector1", "selector2"],
            "postmark": ["pm", "20230601"],
            "mailchimp": ["k1", "mandrill"]
        }
    }
