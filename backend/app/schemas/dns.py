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


class DeliverabilityResult(BaseModel):
    """
    Normalized payload representing domain deliverability audit calculation result.
    Compatible with DNSAuditResponse and internal calculation pipelines.
    """
    health_score: int = Field(..., ge=0, le=100, description="Overall deliverability health score (0-100)")
    status: str = Field(default="warning", description="optimal | warning | critical")
    category_scores: Optional[CategoryScoreBreakdown] = None
    summary: Optional[DiagnosticSummary] = None
    issues: List[DiagnosticIssue] = []
    fixes: List[DNSRecordFix] = []
    raw_responses: Dict[str, Any] = {}


class DNSAuditLogCreate(BaseModel):
    """
    Strict schema corresponding to public.dns_audit_logs production table columns.
    Eliminates schema drift by explicitly mapping all required DNS status fields.
    """
    user_id: str = Field(..., description="UUID of user profile owning the domain")
    domain_id: Optional[str] = Field(default=None, description="Nullable UUID referencing public.monitored_domains(id)")
    domain_name: str = Field(..., description="Normalized target domain name")
    health_score: int = Field(..., ge=0, le=100, description="Compliance score 0-100")
    spf_record: Optional[str] = Field(default=None, description="Raw SPF TXT record")
    spf_status: str = Field(default="missing", description="optimal | warning | critical | missing")
    dkim_records: List[Dict[str, Any]] = Field(default_factory=list, description="Discovered DKIM selectors and records")
    dkim_status: str = Field(default="missing", description="optimal | warning | critical | missing")
    dmarc_record: Optional[str] = Field(default=None, description="Raw DMARC TXT record")
    dmarc_status: str = Field(default="missing", description="optimal | warning | critical | missing")
    mx_records: List[Dict[str, Any]] = Field(default_factory=list, description="Resolved MX mail exchange hosts")
    mx_status: str = Field(default="missing", description="optimal | warning | critical | missing")
    bimi_record: Optional[str] = Field(default=None, description="Raw BIMI record")
    bimi_status: str = Field(default="missing", description="optimal | missing")
    fixes: List[Dict[str, Any]] = Field(default_factory=list, description="Actionable DNS record remediation fixes")
    raw_responses: Dict[str, Any] = Field(default_factory=dict, description="Raw resolver query responses")
    created_at: Optional[str] = Field(default=None, description="ISO 8601 creation timestamp")


class RBLScanRequest(BaseModel):
    domain: str = Field(..., description="Target domain or hostname to scan, e.g. brandshop.com", min_length=3)


class RBLZoneResult(BaseModel):
    id: str = Field(..., description="Unique zone identifier (e.g. spamhaus_zen)")
    name: str = Field(..., description="Human-readable provider name")
    host: str = Field(..., description="Authoritative DNSBL root host")
    category: str = Field(..., description="'ip' or 'domain'")
    status: str = Field(..., description="'clean' | 'listed' | 'timeout' | 'error'")
    return_code: Optional[str] = Field(default=None, description="Raw 127.0.0.x response if listed")
    latency_ms: float = Field(..., description="Query latency in milliseconds")
    delisting_url: str = Field(..., description="Direct remediation URL")
    description: str = Field(..., description="Provider coverage description")
    listed_details: Optional[str] = Field(default=None, description="Diagnostic classification message")


class RBLScanResponse(BaseModel):
    domain: str
    target_ip: Optional[str] = None
    clean_count: int = Field(..., ge=0, le=10)
    total_count: int = Field(default=10)
    listed_count: int = Field(..., ge=0, le=10)
    predicted_risk_48h: str = Field(..., description="'low' | 'medium' | 'high'")
    scan_time_ms: float
    results: List[RBLZoneResult]
    timestamp: datetime


# ============================================================================
# Milestone B: SPF Conflict Resolution & Merge Engine Schemas
# ============================================================================

class SpfMergePlanRequest(BaseModel):
    domain: str = Field(..., min_length=3, description="Apex domain with multiple/conflicting SPF records")
    preferred_qualifier: str = Field(default="~all", pattern="^(~all|-all)$", description="Terminal qualifier (~all or -all)")
    provider_hints: List[str] = Field(default_factory=list, description="Known provider templates to consider")


class SpfMechanism(BaseModel):
    raw: str = Field(..., description="Original raw representation of mechanism")
    kind: str = Field(..., description="include | ip4 | ip6 | a | mx | exists | ptr | redirect | all | unknown")
    qualifier: str = Field(default="+", description="Mechanism qualifier: +, -, ~, ?")
    normalized_value: str = Field(..., description="Canonicalized term for deduplication")
    source_record_indexes: List[int] = Field(default_factory=list, description="Indexes of source TXT records containing this mechanism")


class SpfLookupBudget(BaseModel):
    static_terms: int = Field(..., ge=0, description="Count of lookups incurred directly in apex record (include, a, mx, ptr, exists, redirect)")
    recursively_resolved_terms: int = Field(..., ge=0, description="Total lookups incurred across recursive include/redirect chain")
    maximum_allowed: int = Field(default=10, description="RFC 7208 maximum allowable DNS lookups (10)")
    status: str = Field(..., description="'within_limit' | 'over_limit' | 'unknown'")
    resolution_failures: List[str] = Field(default_factory=list, description="DNS resolution errors encountered during lookups")


class SpfMergeWarning(BaseModel):
    code: str = Field(..., description="Machine-readable error/warning code")
    severity: str = Field(..., description="'info' | 'warning' | 'critical'")
    message: str = Field(..., description="Actionable human explanation")


class SpfMergePlanResponse(BaseModel):
    plan_id: str = Field(..., description="UUID or unique identifier for the generated merge plan")
    domain: str = Field(..., description="Normalized target domain")
    source_records: List[str] = Field(..., description="All discovered v=spf1 TXT records on target domain")
    proposed_record: Optional[str] = Field(None, description="Consolidated single proposed SPF record string")
    mechanisms: List[SpfMechanism] = Field(default_factory=list, description="Resolved and retained mechanisms")
    removed_duplicates: List[str] = Field(default_factory=list, description="Redundant mechanisms eliminated during merge")
    warnings: List[SpfMergeWarning] = Field(default_factory=list, description="Safety and RFC compliance notices")
    lookup_budget: SpfLookupBudget = Field(..., description="Lookup usage analysis against RFC 7208 10-lookup limit")
    safe_to_apply: bool = Field(..., description="Whether plan can safely be injected automatically")
    requires_manual_review: bool = Field(..., description="Whether administrative review is required before application")
    expires_at: str = Field(..., description="ISO 8601 expiration timestamp of the plan snapshot")


# ============================================================================
# Milestone C: Deep Hardening for Remote Asset Fetching Schemas
# ============================================================================

class VerifyRemoteAssetRequest(BaseModel):
    domain: str = Field(..., min_length=3, description="Apex domain under inspection")
    asset_type: str = Field(default="bimi_logo", pattern="^(bimi_logo|bimi_vmc)$", description="Type of asset ('bimi_logo' | 'bimi_vmc')")
    url: Optional[str] = Field(None, description="Explicit asset URL to verify. If omitted, discovered from DNS BIMI record.")


class VerifyRemoteAssetResponse(BaseModel):
    audit_id: str = Field(..., description="UUID of persisted security audit snapshot")
    domain: str = Field(..., description="Normalized target domain")
    asset_type: str = Field(..., description="'bimi_logo' | 'bimi_vmc'")
    requested_url: str = Field(..., description="Target URL evaluated")
    final_url: Optional[str] = Field(None, description="Final resolved URL after any valid redirects")
    pinned_ip: Optional[str] = Field(None, description="Cryptographically pinned public socket IP")
    fetch_status: str = Field(..., description="'verified' | 'rejected' | 'failed'")
    http_status: Optional[int] = Field(None, description="HTTP status code received")
    content_type: Optional[str] = Field(None, description="Content-Type header")
    content_length_bytes: int = Field(default=0, description="Payload size in bytes (capped at 500 KB)")
    content_sha256: Optional[str] = Field(None, description="SHA-256 cryptographic digest of asset content")
    redirect_count: int = Field(default=0, description="Number of manual redirect hops taken")
    failure_code: Optional[str] = Field(None, description="Machine-readable security failure code if rejected")
    error_message: Optional[str] = Field(None, description="Human-readable diagnosis")
    created_at: str = Field(..., description="ISO 8601 audit timestamp")
