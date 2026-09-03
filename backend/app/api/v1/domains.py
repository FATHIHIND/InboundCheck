"""
InboundCheck - Monitored Domains API Routes (v1)
================================================
Endpoints for managing monitored sending domains, live database persistence,
and triggering on-demand DNS deliverability re-audits with authenticated tenant isolation.
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging

from app.core.security import get_current_user_id
from app.services.supabase_client import supabase_service
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer
from app.schemas.dns import DNSAuditResponse

logger = logging.getLogger("DomainRoutes")

router = APIRouter(prefix="/domains", tags=["Monitored Domains"])
diagnostic_engine = DNSDiagnosticEngine()


class CreateDomainRequest(BaseModel):
    domain: str = Field(..., description="Apex or subdomain to monitor, e.g. brandshop.com", min_length=3)
    custom_selectors: Optional[List[str]] = None


@router.get("", response_model=List[Dict[str, Any]])
async def list_user_domains(
    limit: int = Query(20, ge=1, le=100, description="Number of domains to return (1-100)"),
    offset: int = Query(0, ge=0, description="Number of domains to skip for pagination"),
    user_id: str = Depends(get_current_user_id)
):
    """
    List all monitored domains for the authenticated user ordered by creation date with pagination.
    Enforces Row Level Security (RLS) tenant isolation.
    """
    try:
        domains = supabase_service.get_user_domains(user_id=user_id, limit=limit, offset=offset)
        return domains
    except Exception as e:
        logger.error(f"Error listing domains for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve monitored domains")


@router.post("", response_model=Dict[str, Any])
async def add_monitored_domain(
    request: CreateDomainRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Add a new sending domain to continuous monitoring.
    Immediately executes initial DNS diagnostic audit and stores record in Supabase.
    """
    try:
        clean_domain = request.domain.strip().lower()
        if not clean_domain or len(clean_domain) < 3:
            raise HTTPException(status_code=400, detail="Valid domain name is required.")

        # Run live DNS diagnostic
        summary, raw_responses, exec_ms = await diagnostic_engine.audit_domain(
            domain=clean_domain,
            custom_selectors=request.custom_selectors
        )

        health_score, overall_status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
            domain=clean_domain,
            summary=summary
        )

        audit_payload = {
            "health_score": health_score,
            "status": overall_status,
            "summary": summary.model_dump(),
            "issues": [i.model_dump() for i in issues],
            "fixes": [f.model_dump() for f in fixes],
            "raw_responses": raw_responses
        }

        # Persist in Supabase monitored_domains
        saved_domain = supabase_service.create_or_update_domain(
            user_id=user_id,
            domain_name=clean_domain,
            audit_result=audit_payload
        )

        # Log audit entry in dns_audit_logs
        supabase_service.save_audit_log(
            user_id=user_id,
            domain_id=saved_domain.get("id", "dom_1"),
            domain_name=clean_domain,
            audit_result=audit_payload
        )

        return {
            "success": True,
            "domain": saved_domain,
            "audit": audit_payload
        }
    except Exception as e:
        logger.error(f"Error adding domain {request.domain}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add monitored domain")


@router.post("/{domain_id}/audit", response_model=Dict[str, Any])
async def re_audit_domain(
    domain_id: str,
    domain_name: str = Query(...),
    user_id: str = Depends(get_current_user_id)
):
    """
    Trigger on-demand live DNS re-audit for a specific monitored domain.
    Updates the health score, status pill badges, and appends a new audit log.
    """
    try:
        clean_domain = domain_name.strip().lower()
        summary, raw_responses, exec_ms = await diagnostic_engine.audit_domain(domain=clean_domain)

        health_score, overall_status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
            domain=clean_domain,
            summary=summary
        )

        audit_payload = {
            "health_score": health_score,
            "status": overall_status,
            "summary": summary.model_dump(),
            "issues": [i.model_dump() for i in issues],
            "fixes": [f.model_dump() for f in fixes],
            "raw_responses": raw_responses
        }

        # Update domain in database
        updated_domain = supabase_service.create_or_update_domain(
            user_id=user_id,
            domain_name=clean_domain,
            audit_result=audit_payload
        )

        # Append audit log
        supabase_service.save_audit_log(
            user_id=user_id,
            domain_id=domain_id,
            domain_name=clean_domain,
            audit_result=audit_payload
        )

        return {
            "success": True,
            "domain": updated_domain,
            "audit": audit_payload
        }
    except Exception as e:
        logger.error(f"Error re-auditing domain {domain_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to re-audit monitored domain")


@router.delete("/{domain_id}")
async def delete_monitored_domain(
    domain_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    Delete a monitored domain and stop recurring checks.
    """
    try:
        success = supabase_service.delete_domain(user_id=user_id, domain_id=domain_id)
        return {"success": success, "domain_id": domain_id}
    except Exception as e:
        logger.error(f"Error deleting domain {domain_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete monitored domain")
