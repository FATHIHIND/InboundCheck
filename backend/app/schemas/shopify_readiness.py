"""
InboundCheck - Shopify Deliverability Readiness Schemas
======================================================
Contracts for evaluating the 6 core checks required for Shopify Zero-Spam delivery:
1. custom_sending_domain
2. shopify_dkim
3. spf_alignment
4. dmarc_policy
5. spf_conflict
6. shared_pool_exposure
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ReadinessCheckItem(BaseModel):
    check_id: str
    title: str
    status: str  # "pass", "warning", "fail"
    impact: str  # "critical", "high", "medium"
    finding: str
    remediation: str
    dns_record_snippet: Optional[str] = None


class ShopifyReadinessRequest(BaseModel):
    domain: Optional[str] = Field(None, description="Apex domain to inspect (defaults to connected Shopify store domain)")
    store_id: Optional[str] = Field(None, description="Shopify store ID if already connected")


class ShopifyReadinessResponse(BaseModel):
    domain: str
    readiness_score: int = Field(ge=0, le=100, description="Readiness score from 0 to 100")
    status: str = Field(description="'ready', 'needs_attention', or 'critical'")
    passed_checks: int
    total_checks: int
    checks: List[ReadinessCheckItem]
    evaluated_at: str
    can_activate_zero_spam: bool
    summary: str
