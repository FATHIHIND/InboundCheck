"""
InboundCheck - Automated Seed Inbox Testing Schemas
==================================================
Contracts for seed inbox message placement verification across major providers
(Gmail, Yahoo, Outlook) and deliverability tracking token generation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class PlacementStatus(str, Enum):
    INBOX = "inbox"
    SPAM = "spam"
    PROMOTIONS = "promotions"
    MISSING = "missing"
    ERROR = "error"


class TargetProvider(str, Enum):
    GMAIL = "gmail"
    YAHOO = "yahoo"
    OUTLOOK = "outlook"


class SeedEmailHeaderInfo(BaseModel):
    message_id: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    subject: Optional[str] = None
    spf_result: Optional[str] = "unknown"  # pass, fail, softfail, neutral, none
    dkim_result: Optional[str] = "unknown"  # pass, fail, none
    dmarc_result: Optional[str] = "unknown"  # pass, fail, none
    received_date: Optional[str] = None
    auth_results_raw: Optional[str] = None


class ProviderPlacement(BaseModel):
    provider: TargetProvider
    placement: PlacementStatus
    folder_name: str = "INBOX"
    latency_ms: float = 0.0
    headers: Optional[SeedEmailHeaderInfo] = None
    error_detail: Optional[str] = None


class SeedPlacementResult(BaseModel):
    tracking_token: str
    test_email_address: str
    store_domain: str
    overall_placement: str  # "inbox", "spam", "promotions", "partial", "missing", "error"
    providers: List[ProviderPlacement]
    inbox_rate_pct: float
    spam_rate_pct: float
    promotions_rate_pct: float
    missing_count: int
    executed_at: str
    execution_time_ms: float
    recommendations: List[str] = Field(default_factory=list)


class GenerateSeedRequest(BaseModel):
    store_domain: str = Field(..., description="Store domain being evaluated, e.g. brandshop.com")
    provider: Optional[str] = Field("seed", description="Provider seed mailbox routing tag")


class GenerateSeedResponse(BaseModel):
    tracking_token: str
    seed_email_address: str
    store_domain: str
    subject_tag: str
    instructions: str
    expires_in_seconds: int = 3600


class VerifySeedRequest(BaseModel):
    tracking_token: str = Field(..., description="Unique tracking token returned during seed generation")
    store_domain: str = Field(..., description="Store domain being evaluated")
    timeout_seconds: float = Field(10.0, ge=1.0, le=15.0, description="Max lookup timeout per provider")
