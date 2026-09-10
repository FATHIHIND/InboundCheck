"""
InboundCheck - Asynchronous DNSBL / RBL Scanning Engine
=======================================================
Evidence-based reputation service measuring live DNSBL responses across 10 authoritative zones:
- Strict 4-state per-provider status: clean | listed | unknown | error
- Target types: ip | domain
- Bounded concurrency with async semaphore and 1.5s per-query lifetime
- Multi-IP aggregation (any listed IP marks provider as listed; unknown/timeout never reported as clean)
- Overall status: clean | listed | partial | unavailable
"""

import time
import ipaddress
import asyncio
import logging
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import dns.asyncresolver
import dns.resolver
import dns.exception
import dns.rdatatype

from app.services.dns.diagnostic_engine import DNSDiagnosticEngine

logger = logging.getLogger("RBLScannerService")

RBLStatus = Literal["clean", "listed", "unknown", "error"]
RBLTargetType = Literal["ip", "domain"]
RBLSeverity = Literal["none", "low", "medium", "high", "critical"]


class RBLProviderDefinition(BaseModel):
    id: str
    name: str
    zone: str
    target_type: RBLTargetType
    delisting_url: str
    description: str
    enabled: bool = True


class RBLListingResult(BaseModel):
    provider_id: str
    provider_name: str
    zone: str
    target_type: RBLTargetType
    status: RBLStatus
    severity: RBLSeverity = "none"
    queried_target: str
    response_codes: List[str] = Field(default_factory=list)
    latency_ms: Optional[int] = None
    message: Optional[str] = None
    delisting_url: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RBLScanResult(BaseModel):
    domain: str
    resolved_ips: List[str]
    results: List[RBLListingResult]
    rbl_clean_count: int
    rbl_listed_count: int
    rbl_unknown_count: int
    rbl_error_count: int
    rbl_total_count: int
    overall_status: Literal["clean", "listed", "partial", "unavailable"]
    highest_severity: RBLSeverity
    execution_time_ms: float
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Authoritative Modernized 10-DNSBL Registry
RBL_PROVIDERS: List[RBLProviderDefinition] = [
    RBLProviderDefinition(
        id="spamhaus_zen",
        name="Spamhaus ZEN",
        zone="zen.spamhaus.org",
        target_type="ip",
        delisting_url="https://check.spamhaus.org/",
        description="IP reputation composite list covering SBL, XBL, and PBL.",
    ),
    RBLProviderDefinition(
        id="barracuda_brbl",
        name="Barracuda BRBL",
        zone="b.barracudacentral.org",
        target_type="ip",
        delisting_url="https://www.barracudacentral.org/rbl/removal-request",
        description="Barracuda sender-IP reputation list verified against spam traps.",
    ),
    RBLProviderDefinition(
        id="spamcop_scbl",
        name="SpamCop SCBL",
        zone="bl.spamcop.net",
        target_type="ip",
        delisting_url="https://www.spamcop.net/bl.shtml",
        description="Dynamic IP listing based on verified spam report submissions.",
    ),
    RBLProviderDefinition(
        id="invaluement_uri",
        name="Invaluement URI",
        zone="ival.invaluement.com",
        target_type="domain",
        delisting_url="https://www.invaluement.com/lookup/",
        description="Anti-spam reputation blacklist specialized in domain URIs.",
    ),
    RBLProviderDefinition(
        id="uceprotect_l1",
        name="UCEPROTECT Level 1",
        zone="dnsbl-1.uceprotect.net",
        target_type="ip",
        delisting_url="http://www.uceprotect.net/en/rblcheck.php",
        description="Strict single-IP address blacklist for direct spam emitters.",
    ),
    RBLProviderDefinition(
        id="spamhaus_dbl",
        name="Spamhaus DBL",
        zone="dbl.spamhaus.org",
        target_type="domain",
        delisting_url="https://check.spamhaus.org/",
        description="Authoritative domain blacklist covering phishing and spam domain URIs.",
    ),
    RBLProviderDefinition(
        id="cbl",
        name="Composite Blocking List",
        zone="cbl.abuseat.org",
        target_type="ip",
        delisting_url="https://www.abuseat.org/lookup.cgi",
        description="Detects botnet infections, Trojan relays, and open proxies.",
    ),
    RBLProviderDefinition(
        id="abuse_ro",
        name="Abuse.ro Network",
        zone="rbl.abuse.ro",
        target_type="ip",
        delisting_url="https://rbl.abuse.ro/",
        description="Real-time spam origin and attack IP blacklist.",
    ),
    RBLProviderDefinition(
        id="surbl",
        name="SURBL Multi-Depth",
        zone="multi.surbl.org",
        target_type="domain",
        delisting_url="http://www.surbl.org/surbl-analysis",
        description="Detects domain hosts appearing in unsolicited email messages.",
    ),
    RBLProviderDefinition(
        id="mailspike",
        name="Mailspike Reputation",
        zone="rep.mailspike.net",
        target_type="ip",
        delisting_url="https://mailspike.org/iplookup.html",
        description="Distributed sender IP reputation scoring network.",
    ),
]


def dnsbl_query_name(ip: str, zone: str) -> str:
    """Format reverse-octet DNSBL query: 203.0.113.25 -> 25.113.0.203.zen.spamhaus.org."""
    reversed_octets = ".".join(reversed(ip.strip().split(".")))
    return f"{reversed_octets}.{zone}"


def domain_rbl_query_name(domain: str, zone: str) -> str:
    """Format RHSBL domain query: brandshop.com -> brandshop.com.dbl.spamhaus.org."""
    clean = domain.strip().rstrip(".")
    return f"{clean}.{zone}"


def severity_from_codes(provider: RBLProviderDefinition, codes: List[str]) -> RBLSeverity:
    """Classify listing severity based on return codes."""
    if not codes:
        return "none"
    if provider.id in ["spamhaus_zen", "barracuda_brbl", "spamhaus_dbl"]:
        return "critical"
    return "high"


class RBLScannerService:
    """
    Evidence-based asynchronous DNSBL scanning engine.
    """

    def __init__(
        self,
        nameservers: Optional[List[str]] = None,
        query_timeout: float = 1.5,
        max_concurrency: int = 10,
    ):
        self.nameservers = nameservers or ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
        self.query_timeout = query_timeout
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def registry(self) -> List[RBLProviderDefinition]:
        return [p for p in RBL_PROVIDERS if p.enabled]

    def _get_resolver(self) -> dns.asyncresolver.Resolver:
        resolver = dns.asyncresolver.Resolver()
        if self.nameservers:
            resolver.nameservers = self.nameservers
        resolver.timeout = self.query_timeout
        resolver.lifetime = self.query_timeout
        return resolver

    async def resolve_public_a_records(self, domain: str) -> List[str]:
        """
        Resolve A records for apex domain, keeping only globally-routable public IPv4 addresses.
        """
        resolver = self._get_resolver()
        public_ips = []
        try:
            answers = await asyncio.wait_for(resolver.resolve(domain, "A"), timeout=2.0)
            for rdata in answers:
                ip_str = str(getattr(rdata, "address", rdata)).strip()
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                    if ip_obj.version == 4 and ip_obj.is_global and not ip_obj.is_private and not ip_obj.is_loopback:
                        public_ips.append(ip_str)
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Could not resolve A records for domain {domain}: {e}")
        return list(dict.fromkeys(public_ips))

    async def _query_single_target(
        self,
        provider: RBLProviderDefinition,
        target: str,
        query_host: str,
        resolver: dns.asyncresolver.Resolver,
    ) -> Dict[str, Any]:
        """Execute a single DNS query with semaphore control and strict exception mapping."""
        start_time = time.perf_counter()
        now = datetime.now(timezone.utc)

        try:
            async with self._semaphore:
                answers = await asyncio.wait_for(
                    resolver.resolve(query_host, dns.rdatatype.A, lifetime=self.query_timeout),
                    timeout=self.query_timeout,
                )

            latency = int((time.perf_counter() - start_time) * 1000)
            codes = [str(getattr(rdata, "address", rdata)).strip() for rdata in answers]

            # Commercial open-resolver volume notice
            if any(code.startswith("127.255.255.") for code in codes):
                return {
                    "status": "unknown",
                    "severity": "none",
                    "response_codes": codes,
                    "latency_ms": latency,
                    "message": "Resolver query volume limit notice (open resolver policy)",
                    "checked_at": now,
                    "target": target,
                }

            # Mailspike specific response interpretation
            if provider.id == "mailspike":
                bad_codes = {"127.0.0.10", "127.0.0.11", "127.0.0.12", "127.0.0.13", "127.0.0.14"}
                if any(c in bad_codes for c in codes):
                    return {
                        "status": "listed",
                        "severity": "medium",
                        "response_codes": codes,
                        "latency_ms": latency,
                        "message": f"Listed on Mailspike with code {codes[0]}",
                        "checked_at": now,
                        "target": target,
                    }
                else:
                    return {
                        "status": "clean",
                        "severity": "none",
                        "response_codes": codes,
                        "latency_ms": latency,
                        "message": None,
                        "checked_at": now,
                        "target": target,
                    }

            # Standard 127.0.0.x / 127.0.1.x positive listing
            if any(code.startswith("127.") for code in codes):
                return {
                    "status": "listed",
                    "severity": severity_from_codes(provider, codes),
                    "response_codes": codes,
                    "latency_ms": latency,
                    "message": f"Listed on {provider.name} with code {codes[0]}",
                    "checked_at": now,
                    "target": target,
                }

            return {
                "status": "clean",
                "severity": "none",
                "response_codes": codes,
                "latency_ms": latency,
                "message": None,
                "checked_at": now,
                "target": target,
            }

        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            latency = int((time.perf_counter() - start_time) * 1000)
            return {
                "status": "clean",
                "severity": "none",
                "response_codes": [],
                "latency_ms": latency,
                "message": None,
                "checked_at": now,
                "target": target,
            }
        except (asyncio.TimeoutError, dns.exception.Timeout):
            latency = int(self.query_timeout * 1000)
            return {
                "status": "unknown",
                "severity": "none",
                "response_codes": [],
                "latency_ms": latency,
                "message": "DNSBL query timed out (unresponsive nameserver)",
                "checked_at": now,
                "target": target,
            }
        except dns.resolver.NoNameservers:
            latency = int((time.perf_counter() - start_time) * 1000)
            return {
                "status": "unknown",
                "severity": "none",
                "response_codes": [],
                "latency_ms": latency,
                "message": "Provider nameserver unavailable",
                "checked_at": now,
                "target": target,
            }
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            logger.warning(f"RBL probe error for {provider.id} ({query_host}): {e}")
            return {
                "status": "error",
                "severity": "none",
                "response_codes": [],
                "latency_ms": latency,
                "message": f"RBL query failed: {str(e)}",
                "checked_at": now,
                "target": target,
            }

    async def scan_domain(self, domain: str) -> RBLScanResult:
        """
        Scan all enabled DNSBL providers against apex public A records and domain URI lists.
        """
        start_time = time.perf_counter()
        clean_domain = domain.strip().lower()

        # Resolve public A records
        resolved_ips = await self.resolve_public_a_records(clean_domain)
        resolver = self._get_resolver()

        results: List[RBLListingResult] = []

        # Iterate over each enabled provider
        for provider in RBL_PROVIDERS:
            if not provider.enabled:
                results.append(
                    RBLListingResult(
                        provider_id=provider.id,
                        provider_name=provider.name,
                        zone=provider.zone,
                        target_type=provider.target_type,
                        status="unknown",
                        severity="none",
                        queried_target=clean_domain,
                        response_codes=[],
                        message="Provider disabled in configuration",
                        delisting_url=provider.delisting_url,
                        checked_at=datetime.now(timezone.utc),
                    )
                )
                continue

            if provider.target_type == "domain":
                query_host = domain_rbl_query_name(clean_domain, provider.zone)
                raw = await self._query_single_target(provider, clean_domain, query_host, resolver)
                results.append(
                    RBLListingResult(
                        provider_id=provider.id,
                        provider_name=provider.name,
                        zone=provider.zone,
                        target_type="domain",
                        status=raw["status"],
                        severity=raw["severity"],
                        queried_target=clean_domain,
                        response_codes=raw["response_codes"],
                        latency_ms=raw["latency_ms"],
                        message=raw["message"],
                        delisting_url=provider.delisting_url,
                        checked_at=raw["checked_at"],
                    )
                )
            else:
                # IP-based provider
                if not resolved_ips:
                    results.append(
                        RBLListingResult(
                            provider_id=provider.id,
                            provider_name=provider.name,
                            zone=provider.zone,
                            target_type="ip",
                            status="unknown",
                            severity="none",
                            queried_target="none",
                            response_codes=[],
                            message="No public IPv4 A-records found to query IP zone",
                            delisting_url=provider.delisting_url,
                            checked_at=datetime.now(timezone.utc),
                        )
                    )
                else:
                    # Query all resolved IPs concurrently
                    tasks = [
                        self._query_single_target(
                            provider,
                            ip,
                            dnsbl_query_name(ip, provider.zone),
                            resolver,
                        )
                        for ip in resolved_ips
                    ]
                    ip_raw_results = await asyncio.gather(*tasks)

                    # Multi-IP aggregation rules:
                    # 1. Any listed IP => provider status is listed
                    # 2. All clean => clean
                    # 3. No listed IP, but one or more unknown/error => unknown/error
                    listed_entry = next((r for r in ip_raw_results if r["status"] == "listed"), None)
                    if listed_entry:
                        results.append(
                            RBLListingResult(
                                provider_id=provider.id,
                                provider_name=provider.name,
                                zone=provider.zone,
                                target_type="ip",
                                status="listed",
                                severity=listed_entry["severity"],
                                queried_target=listed_entry["target"],
                                response_codes=listed_entry["response_codes"],
                                latency_ms=listed_entry["latency_ms"],
                                message=listed_entry["message"],
                                delisting_url=provider.delisting_url,
                                checked_at=listed_entry["checked_at"],
                            )
                        )
                    elif any(r["status"] == "error" for r in ip_raw_results):
                        err_entry = next(r for r in ip_raw_results if r["status"] == "error")
                        results.append(
                            RBLListingResult(
                                provider_id=provider.id,
                                provider_name=provider.name,
                                zone=provider.zone,
                                target_type="ip",
                                status="error",
                                severity="none",
                                queried_target=", ".join(resolved_ips),
                                response_codes=[],
                                latency_ms=err_entry["latency_ms"],
                                message=err_entry["message"],
                                delisting_url=provider.delisting_url,
                                checked_at=err_entry["checked_at"],
                            )
                        )
                    elif any(r["status"] == "unknown" for r in ip_raw_results):
                        unk_entry = next(r for r in ip_raw_results if r["status"] == "unknown")
                        results.append(
                            RBLListingResult(
                                provider_id=provider.id,
                                provider_name=provider.name,
                                zone=provider.zone,
                                target_type="ip",
                                status="unknown",
                                severity="none",
                                queried_target=", ".join(resolved_ips),
                                response_codes=[],
                                latency_ms=unk_entry["latency_ms"],
                                message=unk_entry["message"],
                                delisting_url=provider.delisting_url,
                                checked_at=unk_entry["checked_at"],
                            )
                        )
                    else:
                        first_clean = ip_raw_results[0]
                        results.append(
                            RBLListingResult(
                                provider_id=provider.id,
                                provider_name=provider.name,
                                zone=provider.zone,
                                target_type="ip",
                                status="clean",
                                severity="none",
                                queried_target=", ".join(resolved_ips),
                                response_codes=[],
                                latency_ms=first_clean["latency_ms"],
                                message=None,
                                delisting_url=provider.delisting_url,
                                checked_at=first_clean["checked_at"],
                            )
                        )

        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Counting rules
        rbl_total_count = len(results)
        rbl_clean_count = sum(1 for r in results if r.status == "clean")
        rbl_listed_count = sum(1 for r in results if r.status == "listed")
        rbl_unknown_count = sum(1 for r in results if r.status == "unknown")
        rbl_error_count = sum(1 for r in results if r.status == "error")

        # Highest severity calculation
        severities = [r.severity for r in results]
        if "critical" in severities:
            highest_severity: RBLSeverity = "critical"
        elif "high" in severities:
            highest_severity = "high"
        elif "medium" in severities:
            highest_severity = "medium"
        elif "low" in severities:
            highest_severity = "low"
        else:
            highest_severity = "none"

        # Overall status rules:
        # clean: valid only when ALL enabled providers return definitive negative result
        # listed: one or more listed
        # partial: some providers could not be measured
        # unavailable: no provider returned a definitive measurement
        if rbl_listed_count > 0:
            overall_status: Literal["clean", "listed", "partial", "unavailable"] = "listed"
        elif rbl_clean_count == rbl_total_count:
            overall_status = "clean"
        elif rbl_clean_count == 0 and (rbl_unknown_count + rbl_error_count == rbl_total_count):
            overall_status = "unavailable"
        else:
            overall_status = "partial"

        return RBLScanResult(
            domain=clean_domain,
            resolved_ips=resolved_ips,
            results=results,
            rbl_clean_count=rbl_clean_count,
            rbl_listed_count=rbl_listed_count,
            rbl_unknown_count=rbl_unknown_count,
            rbl_error_count=rbl_error_count,
            rbl_total_count=rbl_total_count,
            overall_status=overall_status,
            highest_severity=highest_severity,
            execution_time_ms=execution_time_ms,
            scanned_at=datetime.now(timezone.utc),
        )


rbl_scanner = RBLScannerService()
