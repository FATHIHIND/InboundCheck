"""
InboundCheck - Revenue-at-Risk Analytical Schemas
=================================================
Contracts for assessing expected financial impairment on email deliverability failures:
Expected Risk = (Order Count * AOV) * Impairment Probability * Customer Impact Factor
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class RevenueRiskRequest(BaseModel):
    domain: Optional[str] = Field(None, description="Apex domain to assess")
    order_count: Optional[int] = Field(None, ge=0, description="Monthly order volume")
    average_order_value_cents: Optional[int] = Field(None, ge=0, description="AOV in integer cents")
    customer_impact_factor: Optional[float] = Field(1.0, ge=0.1, le=5.0, description="Multiplier for churn/support friction (default 1.0)")


class ConfidenceBandDetails(BaseModel):
    band: str  # "high", "medium", "low"
    margin_error_pct: float
    lower_bound_cents: int
    upper_bound_cents: int
    lower_bound_formatted: str
    upper_bound_formatted: str
    explanation: str


class RevenueRiskBreakdown(BaseModel):
    order_count: int
    average_order_value_cents: int
    monthly_gmv_cents: int
    impairment_probability: float
    customer_impact_factor: float
    deliverability_score: int
    dmarc_penalty: float
    spf_penalty: float
    dkim_penalty: float
    rbl_penalty: float


class RevenueRiskResponse(BaseModel):
    domain: str
    expected_risk_cents: int
    expected_risk_formatted: str
    monthly_gmv_cents: int
    monthly_gmv_formatted: str
    impairment_probability: float
    customer_impact_factor: float
    confidence_band: str  # "high", "medium", "low"
    band_details: ConfidenceBandDetails
    breakdown: RevenueRiskBreakdown
    calculated_at: str
    recommendation: str
