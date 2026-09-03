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
