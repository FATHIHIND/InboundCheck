"""
InboundCheck - Predictive Dispute & Revenue Analytics REST Router (v1)
========================================================================
Endpoints for protected revenue calculations, ROI metrics, and reputation risk event correlation logs.
"""

from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.services.analytics.dispute_analytics import dispute_analytics_service

logger = logging.getLogger("AnalyticsRoutes")

router = APIRouter(prefix="/analytics", tags=["Predictive Revenue & ROI Analytics"])


class ProtectedRevenueRequest(BaseModel):
    monthly_gmv: Optional[float] = Field(default=125000.00, ge=1000.00)


@router.get("/protected-revenue")
async def get_protected_revenue(
    monthly_gmv: float = Query(default=125000.00),
    user_id: str = Depends(get_current_user_id)
):
    """
    Get weekly protected store revenue metrics and ROI multiplier calculations.
    """
    data = dispute_analytics_service.calculate_protected_revenue(user_id=user_id, monthly_gmv=monthly_gmv)
    return {"success": True, "analytics": data}


@router.post("/protected-revenue")
async def calculate_protected_revenue(
    payload: ProtectedRevenueRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Re-calculate protected store GMV metrics based on custom store revenue.
    """
    data = dispute_analytics_service.calculate_protected_revenue(
        user_id=user_id,
        monthly_gmv=payload.monthly_gmv or 125000.00
    )
    return {"success": True, "analytics": data}


@router.get("/reputation-events")
@router.get("/history")
async def get_reputation_events(
    limit: int = Query(20, ge=1, le=100, description="Max records to return (1-100)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Get reputation event telemetry linking DNS fixes to revenue protected with pagination.
    """
    events = dispute_analytics_service.get_reputation_events(user_id=user_id, limit=limit, offset=offset)
    return {"success": True, "events": events, "limit": limit, "offset": offset}


@router.get("/reputation-trend")
async def get_reputation_trend(
    domain: Optional[str] = Query(None, description="Optional domain filter"),
    limit: int = Query(30, ge=5, le=100),
    user_id: str = Depends(get_current_user_id)
):
    """
    Get historical reputation trajectory data points from public.reputation_checks
    to feed the interactive ReputationTrendChart.
    """
    from app.services.supabase_client import supabase_service
    points = []
    if supabase_service.is_connected:
        try:
            query = supabase_service._client.table("reputation_checks").select("*").eq("user_id", user_id)
            if domain:
                query = query.eq("domain_name", domain.strip().lower())
            res = query.order("created_at", desc=False).limit(limit).execute()
            if res.data:
                for row in res.data:
                    points.append({
                        "id": str(row.get("id")),
                        "checked_at": str(row.get("created_at"))[:10],
                        "unified_score": row.get("score", 90),
                        "dns_health_score": row.get("dns_score", 90),
                        "spam_risk_pct": max(0, 100 - row.get("score", 90)),
                        "risk_level": row.get("predicted_risk_48h", "low"),
                        "blacklist_count": max(0, row.get("rbl_total_count", 10) - row.get("rbl_clean_count", 10)),
                        "rbl_status": "Clean" if row.get("rbl_clean_count", 10) == row.get("rbl_total_count", 10) else "Listed"
                    })
        except Exception as e:
            logger.warning(f"Failed to query reputation_checks: {e}")

    # If Supabase not connected or returned no data in test/in-memory mode, check in-memory store
    if not points:
        user_checks = supabase_service._in_memory_reputation.get(user_id, [])
        for row in user_checks:
            if domain and row.get("domain_name") != domain.strip().lower():
                continue
            points.append({
                "id": str(row.get("id", "chk_mem")),
                "checked_at": str(row.get("created_at"))[:10],
                "unified_score": row.get("score", 90),
                "dns_health_score": row.get("dns_score", 90),
                "spam_risk_pct": max(0, 100 - row.get("score", 90)),
                "risk_level": row.get("predicted_risk_48h", "low"),
                "blacklist_count": max(0, row.get("rbl_total_count", 10) - row.get("rbl_clean_count", 10)),
                "rbl_status": "Clean" if row.get("rbl_clean_count", 10) == row.get("rbl_total_count", 10) else "Listed"
            })

    # Never manufacture fake reputation trend points. Return empty list if no historical checks exist.
    return {"success": True, "points": points}


@router.get("/revenue-at-risk")
async def get_revenue_at_risk(
    domain: Optional[str] = Query(None, description="Optional domain to evaluate"),
    order_count: Optional[int] = Query(None, ge=0, description="Monthly order volume"),
    aov_cents: Optional[int] = Query(None, ge=0, description="Average order value in cents"),
    impact_factor: float = Query(1.0, ge=0.1, le=5.0, description="Customer impact multiplier"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Calculate Expected Revenue-at-Risk based on store email deliverability posture:
    Expected Risk = (Order Count * AOV) * Impairment Probability * Customer Impact Factor
    """
    from app.services.analytics.revenue_risk_service import revenue_risk_service
    return revenue_risk_service.calculate_and_record_risk(
        user_id=user_id,
        domain=domain,
        order_count=order_count,
        average_order_value_cents=aov_cents,
        customer_impact_factor=impact_factor
    )


@router.post("/revenue-at-risk")
async def post_revenue_at_risk(
    payload: Optional[Dict[str, Any]] = None,
    user_id: str = Depends(get_current_user_id)
):
    """
    Recalculate Expected Revenue-at-Risk with custom parameters.
    """
    from app.services.analytics.revenue_risk_service import revenue_risk_service
    p = payload or {}
    return revenue_risk_service.calculate_and_record_risk(
        user_id=user_id,
        domain=p.get("domain"),
        order_count=p.get("order_count"),
        average_order_value_cents=p.get("average_order_value_cents"),
        customer_impact_factor=p.get("customer_impact_factor", 1.0)
    )

