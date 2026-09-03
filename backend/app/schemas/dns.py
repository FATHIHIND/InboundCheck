"""
InboundCheck - DNS Schemas
==========================
Pydantic v2 schemas for DNS diagnostic audit, scoring, and record generation.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class DNSAuditRequest(BaseModel):
    domain: str = Field(..., description="Target domain to inspect, e.g. brandshop.com", min_length=3)
    selectors: Optional[List[str]] = Field(
        default=None,
        description="Optional list of DKIM selectors to query in addition to defaults"
    )
    user_id: Optional[str] = Field(default=None, description="Optional authenticated user ID")


class MXRecordItem(BaseModel):
    host: str
    preference: int
    ipv4: List[str] = []
    ipv6: List[str] = []
    provider_detected: Optional[str] = None


class MXSummary(BaseModel):
    status: str = Field(..., description="optimal | warning | critical | missing")
    record_count: int
    records: List[MXRecordItem] = []
    raw: List[str] = []
    primary_provider: Optional[str] = None


class SPFSummary(BaseModel):
    status: str = Field(..., description="optimal | warning | critical | missing")
    raw: Optional[str] = None
    all_mechanism: Optional[str] = None  # -all, ~all, ?all, +all
    dns_lookup_count: int = 0
    includes: List[str] = []
    ip4: List[str] = []
    ip6: List[str] = []
    has_multiple_records: bool = False
    exceeds_lookup_limit: bool = False
    syntax_valid: bool = False


class DKIMSelectorResult(BaseModel):
    selector: str
    status: str = Field(..., description="optimal | warning | critical | missing")
    record_name: str
    raw: Optional[str] = None
    key_type: Optional[str] = None  # rsa, ed25519
    key_size_bits: Optional[int] = None
    has_public_key: bool = False


class DKIMSummary(BaseModel):
    status: str = Field(..., description="optimal | warning | critical | missing")
    tested_selectors: List[str] = []
    found_selectors: List[str] = []
    records: List[DKIMSelectorResult] = []


class DMARCSummary(BaseModel):
    status: str = Field(..., description="optimal | warning | critical | missing")
    raw: Optional[str] = None
    policy: Optional[str] = None  # reject, quarantine, none
    subdomain_policy: Optional[str] = None
    percentage: int = 100
    rua_emails: List[str] = []
    ruf_emails: List[str] = []
    adkim_alignment: str = "r"
    aspf_alignment: str = "r"
    syntax_valid: bool = False


class BIMISummary(BaseModel):
    status: str = Field(..., description="optimal | missing")
    raw: Optional[str] = None
    logo_url: Optional[str] = None
    vmc_url: Optional[str] = None


class DiagnosticSummary(BaseModel):
    mx: MXSummary
    spf: SPFSummary
    dkim: DKIMSummary
    dmarc: DMARCSummary
    bimi: BIMISummary


class DiagnosticIssue(BaseModel):
    id: str
    severity: str = Field(..., description="critical | warning | optimal")
    category: str = Field(..., description="DMARC | SPF | DKIM | MX | BIMI | GENERAL")
    title: str
    description: str
    impact: str
    recommendation: str


class DNSRecordFix(BaseModel):
    record_type: str = Field(..., description="TXT | MX | CNAME")
    host: str
    value: str
    ttl: int = 3600
    category: str
    rationale: str


class CategoryScoreBreakdown(BaseModel):
    dmarc_score: int
    dmarc_max: int = 35
    spf_score: int
    spf_max: int = 25
    dkim_score: int
    dkim_max: int = 25
    mx_score: int
    mx_max: int = 15
    bimi_score: int
    bimi_max: int = 5


class DNSAuditResponse(BaseModel):
    domain: str
    health_score: int = Field(..., ge=0, le=100)
    status: str = Field(..., description="optimal | warning | critical")
    timestamp: datetime
    execution_time_ms: float
    category_scores: CategoryScoreBreakdown
    summary: DiagnosticSummary
    issues: List[DiagnosticIssue] = []
    fixes: List[DNSRecordFix] = []
    raw_responses: Dict[str, Any] = {}


class GenerateRecordRequest(BaseModel):
    domain: str
    include_shopify: bool = True
    include_google: bool = False
    include_microsoft: bool = False
    include_klaviyo: bool = False
    include_sendgrid: bool = False
    dmarc_policy: str = Field(default="quarantine", description="reject | quarantine | none")
    dmarc_report_email: Optional[str] = None
    custom_dkim_selector: Optional[str] = "shopify"
