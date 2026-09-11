"""
InboundCheck - DNS API Routes (v1)
==================================
Endpoints for real-time DNS diagnostic audits, health scoring, record generation, and automated Telegram notification.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime, timezone
import uuid
from typing import List
import logging

from app.core.config import settings
from app.core.security import get_current_user_id
from app.schemas.dns import (
    DNSAuditRequest,
    DNSAuditResponse,
    GenerateRecordRequest,
    DNSRecordFix,
    RBLScanRequest,
    RBLScanResponse,
    SpfMergePlanRequest,
    SpfMergePlanResponse,
    VerifyRemoteAssetRequest,
    VerifyRemoteAssetResponse,
)
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine, DEFAULT_DKIM_SELECTORS
from app.services.dns.scorer import DeliverabilityScorer
from app.services.dns.record_generator import DNSRecordGenerator
from app.services.dns.rbl_scanner import rbl_scanner
from app.services.dns.spf_merge_engine import spf_merge_engine
from app.services.security.safe_http_fetcher import safe_http_fetcher
from app.services.supabase_client import supabase_service
from app.services.alert_dispatcher import alert_dispatcher

logger = logging.getLogger("DNSRoutes")

router = APIRouter(prefix="/dns", tags=["DNS Diagnostics"])
diagnostic_engine = DNSDiagnosticEngine()


@router.post("/audit", response_model=DNSAuditResponse)
async def execute_dns_audit(
    request: DNSAuditRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Execute real-time multi-resolver DNS audit for the specified domain.
    Enforces SSRF domain sanitization, deliverability health scoring,
    and automatic degradation alerts on threshold dips.
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

        # Real-time Degradation Alert Dispatcher: Alert on score dip below threshold or protocol failure
        try:
            await alert_dispatcher.evaluate_and_dispatch(
                user_id=user_id,
                domain_name=clean_domain,
                health_score=health_score,
                overall_status=overall_status,
                summary=summary,
                issues=issues
            )
        except Exception as alert_err:
            logger.warning(f"Degradation alert evaluation skipped for {clean_domain}: {alert_err}")

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


from app.services.dns.rbl_scanner import rbl_scanner, RBLScanResult
from app.services.supabase_client import supabase_service


@router.post("/rbl-scan", response_model=RBLScanResult)
async def scan_domain_rbl(
    request: RBLScanRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Execute on-demand asynchronous DNSBL reputation scan across 10 authoritative RBL databases.
    Enforces SSRF domain sanitization, reverse-IP query formatting, and 1.5s per-zone timeout protection.
    Persists granular evidence for auditability.
    """
    try:
        clean_domain = request.domain.strip().lower()
        if not clean_domain or len(clean_domain) < 3:
            raise HTTPException(status_code=400, detail="A valid domain name or IP is required.")

        # Anti-SSRF check
        if DNSDiagnosticEngine.is_ssrf_restricted(clean_domain):
            raise HTTPException(status_code=400, detail="Restricted IP or domain target is not permitted for scanning.")

        result = await rbl_scanner.scan_domain(clean_domain)

        # Persist audit evidence
        supabase_service.persist_rbl_scan(
            user_id=user_id,
            domain_name=clean_domain,
            scan=result,
        )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scanning RBL for domain {request.domain}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute asynchronous RBL blacklist scan: {str(e)}"
        )


@router.get("/rbl-status", response_model=RBLScanResult)
async def get_latest_rbl_status(
    domain: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Retrieve the latest recorded DNSBL scan evidence for the user domain.
    Returns HTTP 404 if no previous scan has been conducted.
    """
    clean_domain = domain.strip().lower()
    if not clean_domain:
        raise HTTPException(status_code=400, detail="Domain parameter is required.")

    scan = supabase_service.get_latest_rbl_scan(user_id=user_id, domain_name=clean_domain)
    if not scan:
        raise HTTPException(status_code=404, detail="No RBL scan recorded for this domain.")

    return scan


@router.post("/spf-merge-plan", response_model=SpfMergePlanResponse)
async def create_spf_merge_plan(
    request: SpfMergePlanRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate an RFC 7208 SPF conflict resolution and consolidation plan.
    Deduplicates mechanisms, validates recursive lookup budget against the 10-lookup cap,
    and safeguards against race conditions with deterministic plan hashing.
    """
    clean_domain = request.domain.strip().lower()
    if not clean_domain or len(clean_domain) < 3:
        raise HTTPException(status_code=400, detail="A valid domain name is required.")

    if DNSDiagnosticEngine.is_ssrf_restricted(clean_domain):
        raise HTTPException(status_code=400, detail="Restricted IP or domain target is not permitted.")

    # Match against monitored domain if registered
    domains = supabase_service.get_user_domains(user_id, limit=100)
    domain_match = next((d for d in domains if d.get("domain_name", "").lower() == clean_domain), None)
    domain_id = domain_match.get("id") if domain_match else None

    try:
        plan = await spf_merge_engine.create_plan(
            domain=clean_domain,
            user_id=user_id,
            preferred_qualifier=request.preferred_qualifier,
            provider_hints=request.provider_hints,
            domain_id=domain_id,
        )
        return plan
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create SPF merge plan for {clean_domain}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate SPF merge plan: {str(e)}",
        )


@router.post("/verify-remote-asset", response_model=VerifyRemoteAssetResponse)
async def verify_remote_asset(
    request: VerifyRemoteAssetRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Execute SSRF-immune, socket-level IP pinned verification of external BIMI assets (SVG or VMC).
    Strictly caps streaming payloads at 500 KB, manually enforces max 3 redirect hops,
    and prevents HTTPS-to-HTTP downgrade attacks.
    """
    clean_domain = request.domain.strip().lower()
    if not clean_domain or len(clean_domain) < 3:
        raise HTTPException(status_code=400, detail="A valid domain name is required.")

    if DNSDiagnosticEngine.is_ssrf_restricted(clean_domain):
        raise HTTPException(status_code=400, detail="Restricted IP or domain target is not permitted.")

    target_url = (request.url or "").strip()

    # If URL not directly supplied, attempt discovery from DNS BIMI record
    if not target_url:
        try:
            resolver = diagnostic_engine._get_resolver()
            bimi_records = await diagnostic_engine._resolve_txt(resolver, f"default._bimi.{clean_domain}")
            for r in bimi_records:
                if "v=bimi1" in r.lower():
                    for part in r.split(";"):
                        part_clean = part.strip()
                        if request.asset_type == "bimi_logo" and part_clean.lower().startswith("l="):
                            target_url = part_clean[2:].strip()
                            break
                        elif request.asset_type == "bimi_vmc" and part_clean.lower().startswith("a="):
                            target_url = part_clean[2:].strip()
                            break
                    if target_url:
                        break
        except Exception as e:
            logger.debug(f"Failed to discover BIMI records from DNS: {e}")

    if not target_url:
        raise HTTPException(
            status_code=400,
            detail=f"No asset URL provided and no valid '{request.asset_type}' URL discovered in default._bimi.{clean_domain}.",
        )

    # Match domain_id if present in monitored domains
    domains = supabase_service.get_user_domains(user_id, limit=100)
    domain_match = next((d for d in domains if d.get("domain_name", "").lower() == clean_domain), None)
    domain_id = domain_match.get("id") if domain_match else None

    # Allowed MIME types
    allowed_mime = ["image/svg+xml", "image/svg", "text/xml", "application/xml"] if request.asset_type == "bimi_logo" else None

    # Execute hardened fetch
    result = await safe_http_fetcher.fetch(
        url=target_url,
        asset_type=request.asset_type,
        allowed_mime_prefixes=allowed_mime,
    )

    audit_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    audit_record = {
        "id": audit_id,
        "user_id": user_id,
        "domain_id": domain_id,
        "asset_type": request.asset_type,
        "requested_url": result.requested_url,
        "final_url": result.final_url,
        "pinned_ip": result.pinned_ip,
        "fetch_status": result.fetch_status,
        "http_status": result.http_status,
        "content_type": result.content_type,
        "content_length_bytes": result.content_length_bytes,
        "content_sha256": result.content_sha256,
        "redirect_count": result.redirect_count,
        "failure_code": result.failure_code,
        "created_at": now_iso,
    }

    try:
        supabase_service.save_remote_asset_audit(audit_record)
    except Exception as e:
        logger.warning(f"Could not persist remote_asset_fetch_audit: {e}")

    return VerifyRemoteAssetResponse(
        audit_id=audit_id,
        domain=clean_domain,
        asset_type=request.asset_type,
        requested_url=result.requested_url,
        final_url=result.final_url,
        pinned_ip=result.pinned_ip,
        fetch_status=result.fetch_status,
        http_status=result.http_status,
        content_type=result.content_type,
        content_length_bytes=result.content_length_bytes,
        content_sha256=result.content_sha256,
        redirect_count=result.redirect_count,
        failure_code=result.failure_code,
        error_message=result.error_message,
        created_at=now_iso,
    )
