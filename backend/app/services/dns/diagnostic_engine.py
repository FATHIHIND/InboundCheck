"""
InboundCheck - DNS Diagnostic Engine
====================================
High-performance asynchronous DNS resolver and validator using dnspython.
Audits MX, SPF, DKIM, DMARC, and BIMI records for domain authentication & deliverability.
"""

import re
import time
import asyncio
import base64
import logging
import ipaddress
from typing import List, Dict, Any, Optional, Tuple
import dns.asyncresolver
import dns.resolver
import dns.rdatatype
import dns.exception

# Restricted CIDR blocks blocked by Anti-SSRF Guard
RESTRICTED_SSRF_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Broadcast / Current network
    ipaddress.ip_network("10.0.0.0/8"),          # Private IPv4 (RFC 1918)
    ipaddress.ip_network("100.64.0.0/10"),       # Carrier-Grade NAT (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback IPv4
    ipaddress.ip_network("169.254.0.0/16"),      # Link-Local / Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),       # Private IPv4 (RFC 1918)
    ipaddress.ip_network("192.168.0.0/16"),      # Private IPv4 (RFC 1918)
    ipaddress.ip_network("192.0.2.0/24"),        # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.51.100.0/24"),     # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),         # Multicast
    ipaddress.ip_network("240.0.0.0/4"),         # Reserved
    ipaddress.ip_network("::1/128"),             # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),            # IPv6 Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),           # IPv6 Link-Local
    ipaddress.ip_network("::ffff:0:0/96"),       # IPv4-mapped IPv6
]

from app.schemas.dns import (
    MXRecordItem,
    MXSummary,
    SPFSummary,
    DKIMSelectorResult,
    DKIMSummary,
    DMARCSummary,
    BIMISummary,
    DiagnosticSummary,
    SOARecordItem,
    CAARecordItem,
    DNSRecordsSummary,
    MailInfrastructureSummary,
    ReputationSummary,
)

logger = logging.getLogger("DNSDiagnosticEngine")

DEFAULT_DKIM_SELECTORS = [
    "shopify",
    "k1",          # Klaviyo
    "s1",          # Klaviyo / SendGrid
    "google",      # Google Workspace
    "default",     # Generic / Postmark
    "mail",        # General Mail
    "smtp",        # SMTP relays
    "scph",        # SparkPost
    "mandrill",    # Mailchimp Mandrill
    "cm",          # Campaign Monitor
    "zoho"         # Zoho Mail
]

PROVIDER_SIGNATURES = {
    "google": ["google.com", "googlemail.com", "l.google.com", "aspmx.l.google.com"],
    "microsoft_365": ["outlook.com", "protection.outlook.com", "microsoft.com"],
    "shopify": ["shopify.com", "shops.shopify.com"],
    "klaviyo": ["klaviyo.com", "klaviyomail.com"],
    "sendgrid": ["sendgrid.net", "sendgrid.com"],
    "amazon_ses": ["amazonses.com", "aws.amazon.com"],
    "mailgun": ["mailgun.org", "mailgun.net"],
    "postmark": ["postmarkapp.com", "wildbit.com"],
    "zoho": ["zoho.com", "zoho.eu"],
    "proton": ["protonmail.ch", "proton.me"],
    "fastmail": ["fastmail.com", "messagingengine.com"]
}


class DNSDiagnosticEngine:
    """
    Asynchronous DNS Diagnostic Engine for inspecting domain authentication records.
    """

    def __init__(self, nameservers: Optional[List[str]] = None, timeout: float = 4.0):
        self.nameservers = nameservers or ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
        self.timeout = timeout

    def _get_resolver(self) -> dns.asyncresolver.Resolver:
        """Create and configure an asynchronous DNS resolver."""
        resolver = dns.asyncresolver.Resolver()
        resolver.nameservers = self.nameservers
        resolver.timeout = self.timeout
        resolver.lifetime = self.timeout * 2
        return resolver

    BLOCKED_DOMAINS = [
        "localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"
    ]
    BLOCKED_SUFFIXES = [".local", ".internal", ".lan", ".home", ".corp", ".onion", ".arpa"]

    @classmethod
    def is_ssrf_restricted(cls, target: str) -> bool:
        """
        Validates whether target hostname or IP falls within restricted SSRF ranges:
        127.0.0.0/8, 169.254.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16,
        100.64.0.0/10, and ::ffff:0:0/96, or cloud metadata endpoints.
        """
        raw = target.strip("[]").strip().lower()

        # Check cloud metadata endpoints and internal names
        if raw in cls.BLOCKED_DOMAINS or any(raw.endswith(suffix) for suffix in cls.BLOCKED_SUFFIXES):
            return True

        # Check if target parses as a standard IPv4/IPv6 address
        try:
            ip_obj = ipaddress.ip_address(raw)
            for net in RESTRICTED_SSRF_NETWORKS:
                if ip_obj in net:
                    return True
            if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
                for net in RESTRICTED_SSRF_NETWORKS:
                    if ip_obj.ipv4_mapped in net:
                        return True
            # Any direct IP address is disallowed for domain audits
            return True
        except ValueError:
            pass

        # Regex fallback for dotted-decimal patterns (including carrier-grade NAT 100.64.0.0/10)
        if re.match(r"^(127\.|169\.254\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|192\.168\.|100\.(6[4-9]|[7-9][0-9]|1[0-1][0-9]|12[0-7])\.|0\.)", raw):
            return True

        # IPv4-mapped IPv6 text patterns
        if "::ffff:" in raw or raw.startswith("::"):
            return True

        return False

    @classmethod
    def normalize_domain(cls, domain: str) -> str:
        """
        Normalize and sanitize domain string from user input or URLs.
        - Strips whitespace
        - Lowercases
        - Removes leading http:// or https:// or any scheme
        - Removes user:pass@ if present
        - Removes path, query string, hash fragment
        - Removes port (:80, :443, etc.)
        - Normalizes www. prefix (for email deliverability, apex is authoritative for SPF/DMARC/MX unless subdomain has specific MX)
        - Removes trailing slashes and dots
        - Validates RFC 1035 compliance and SSRF restrictions
        """
        if not domain or not isinstance(domain, str):
            raise ValueError("Domain must be a non-empty string.")

        d = domain.strip().lower()
        # Remove scheme
        d = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", d)
        # Remove userinfo
        d = re.sub(r"^[^@/]+@", "", d)
        # Remove path, query string, fragment
        d = re.sub(r"[/?#].*$", "", d)
        # Remove port
        d = re.sub(r":\d+$", "", d)
        # Strip trailing dots and slashes
        d = d.strip("./")

        # Strip www. prefix for apex email deliverability analysis if standard domain
        if d.startswith("www.") and len(d.split(".")) > 2:
            d = d[4:]

        if not d or len(d) > 253:
            raise ValueError(f"Invalid domain length: '{domain}'")

        if cls.is_ssrf_restricted(d):
            raise ValueError(f"SSRF Protection: Domain or target '{d}' is restricted or points to a private/internal network.")

        domain_pattern = r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
        if not re.match(domain_pattern, d):
            raise ValueError(f"Invalid domain format: '{d}'")

        return d

    def _clean_domain(self, domain: str) -> str:
        """Sanitize domain string using class normalize_domain."""
        return self.normalize_domain(domain)

    def _sanitize_selector(self, selector: str) -> Optional[str]:
        """Validate and sanitize DKIM selector string."""
        s = selector.strip().lower()
        if re.match(r"^[a-zA-Z0-9_-]{1,63}$", s):
            return s
        return None

    async def _resolve_txt(self, resolver: dns.asyncresolver.Resolver, qname: str) -> List[str]:
        """Query TXT records for a specific name, concatenating chunks."""
        try:
            answers = await resolver.resolve(qname, dns.rdatatype.TXT)
            records = []
            for rdata in answers:
                txt_str = "".join([chunk.decode("utf-8", errors="ignore") for chunk in rdata.strings])
                records.append(txt_str)
            return records
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
            return []
        except Exception as e:
            logger.debug(f"TXT resolve error for {qname}: {e}")
            return []

    async def check_dns_records(self, domain: str, resolver: dns.asyncresolver.Resolver) -> Tuple[DNSRecordsSummary, Dict[str, Any]]:
        """
        Query core DNS infrastructure records: A, AAAA, NS, SOA, CAA, and apex CNAME.
        Detects misconfigurations such as apex CNAME (RFC 1912/2181), missing CAA (RFC 6844),
        or insufficient nameserver redundancy (RFC 2182).
        """
        a_records: List[str] = []
        aaaa_records: List[str] = []
        ns_records: List[str] = []
        soa_item: Optional[SOARecordItem] = None
        caa_records: List[CAARecordItem] = []
        cname_records: List[str] = []
        has_apex_cname = False

        # 1. A records (IPv4)
        try:
            a_ans = await asyncio.wait_for(resolver.resolve(domain, dns.rdatatype.A), timeout=2.0)
            for r in a_ans:
                ip_str = str(getattr(r, "address", r)).strip()
                if ip_str and ip_str not in a_records:
                    a_records.append(ip_str)
        except Exception:
            pass

        # 2. AAAA records (IPv6)
        try:
            aaaa_ans = await asyncio.wait_for(resolver.resolve(domain, dns.rdatatype.AAAA), timeout=2.0)
            for r in aaaa_ans:
                ip_str = str(getattr(r, "address", r)).strip()
                if ip_str and ip_str not in aaaa_records:
                    aaaa_records.append(ip_str)
        except Exception:
            pass

        # 3. NS records (Nameservers)
        try:
            ns_ans = await asyncio.wait_for(resolver.resolve(domain, dns.rdatatype.NS), timeout=2.0)
            for r in ns_ans:
                ns_name = str(getattr(r, "target", r)).rstrip(".")
                if ns_name and ns_name not in ns_records:
                    ns_records.append(ns_name)
        except Exception:
            pass

        # 4. SOA record (Start of Authority)
        try:
            soa_ans = await asyncio.wait_for(resolver.resolve(domain, dns.rdatatype.SOA), timeout=2.0)
            if soa_ans:
                rdata = soa_ans[0]
                soa_item = SOARecordItem(
                    mname=str(rdata.mname).rstrip("."),
                    rname=str(rdata.rname).rstrip("."),
                    serial=int(rdata.serial),
                    refresh=int(rdata.refresh),
                    retry=int(rdata.retry),
                    expire=int(rdata.expire),
                    minimum=int(rdata.minimum)
                )
        except Exception:
            pass

        # 5. CAA records (Certificate Authority Authorization, RFC 6844)
        try:
            caa_ans = await asyncio.wait_for(resolver.resolve(domain, dns.rdatatype.CAA), timeout=2.0)
            for r in caa_ans:
                tag = str(r.tag.decode("utf-8") if isinstance(r.tag, bytes) else r.tag).strip()
                val = str(r.value.decode("utf-8") if isinstance(r.value, bytes) else r.value).strip()
                caa_records.append(CAARecordItem(tag=tag, value=val, flags=int(r.flags)))
        except Exception:
            pass

        # 6. CNAME at apex domain (RFC 1912 §2.4 / RFC 2181 §10.1 error)
        try:
            cname_ans = await asyncio.wait_for(resolver.resolve(domain, dns.rdatatype.CNAME), timeout=2.0)
            for r in cname_ans:
                cname_val = str(getattr(r, "target", r)).rstrip(".")
                if cname_val:
                    cname_records.append(cname_val)
                    has_apex_cname = True
        except Exception:
            pass

        has_caa = len(caa_records) > 0
        ns_count = len(ns_records)

        # Status evaluation
        if has_apex_cname or (not a_records and not aaaa_records and not ns_records):
            status = "critical"
        elif ns_count < 2 or not has_caa or (not a_records and not aaaa_records):
            status = "warning"
        else:
            status = "optimal"

        dns_summary = DNSRecordsSummary(
            status=status,
            a_records=a_records,
            aaaa_records=aaaa_records,
            ns_records=ns_records,
            soa=soa_item,
            caa_records=caa_records,
            cname_records=cname_records,
            has_apex_cname=has_apex_cname,
            ns_count=ns_count,
            has_caa=has_caa
        )

        raw_dns = {
            "a": a_records,
            "aaaa": aaaa_records,
            "ns": ns_records,
            "soa": soa_item.model_dump() if soa_item else None,
            "caa": [c.model_dump() for c in caa_records],
            "cname": cname_records,
            "has_apex_cname": has_apex_cname
        }

        return dns_summary, raw_dns

    async def check_mx(
        self,
        domain: str,
        resolver: dns.asyncresolver.Resolver
    ) -> Tuple[MXSummary, List[str], MailInfrastructureSummary]:
        """
        Query and evaluate MX records for domain. Resolves host IPs (IPv4/IPv6),
        validates hostnames against RFC 5321/2181, performs reverse DNS (PTR),
        and verifies that mail hosts do not route to private/internal networks.
        """
        raw_lines = []
        records: List[MXRecordItem] = []
        primary_provider = None

        try:
            answers = await resolver.resolve(domain, dns.rdatatype.MX)
            for rdata in answers:
                host_str = str(rdata.exchange).rstrip(".")
                pref = int(rdata.preference)
                raw_lines.append(f"{pref} {host_str}")

                provider_name = None
                for pname, sigs in PROVIDER_SIGNATURES.items():
                    if any(sig in host_str.lower() for sig in sigs):
                        provider_name = pname
                        if not primary_provider:
                            primary_provider = pname
                        break

                records.append(MXRecordItem(
                    host=host_str,
                    preference=pref,
                    provider_detected=provider_name
                ))
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
            pass
        except Exception as e:
            logger.debug(f"MX lookup error for {domain}: {e}")

        records.sort(key=lambda x: x.preference)

        # Inspect Mail Infrastructure for each MX host (A, AAAA, CNAME, PTR)
        async def _inspect_mx_host(rec: MXRecordItem) -> Dict[str, Any]:
            h = rec.host
            ipv4_list: List[str] = []
            ipv6_list: List[str] = []
            is_cname = False
            is_null = h in [".", ""]
            is_ip_literal = bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", h))
            ptr_map: Dict[str, List[str]] = {}
            is_private = False

            if not is_null and not is_ip_literal:
                # Check CNAME on MX host (RFC 2181 §10.3 violation if True)
                try:
                    c_ans = await asyncio.wait_for(resolver.resolve(h, dns.rdatatype.CNAME), timeout=1.5)
                    if c_ans:
                        is_cname = True
                except Exception:
                    pass

                # Resolve IPv4
                try:
                    a_ans = await asyncio.wait_for(resolver.resolve(h, dns.rdatatype.A), timeout=1.5)
                    for r in a_ans:
                        ip_s = str(getattr(r, "address", r)).strip()
                        if ip_s and ip_s not in ipv4_list:
                            ipv4_list.append(ip_s)
                            if self.is_ssrf_restricted(ip_s):
                                is_private = True
                except Exception:
                    pass

                # Resolve IPv6
                try:
                    aaaa_ans = await asyncio.wait_for(resolver.resolve(h, dns.rdatatype.AAAA), timeout=1.5)
                    for r in aaaa_ans:
                        ip_s = str(getattr(r, "address", r)).strip()
                        if ip_s and ip_s not in ipv6_list:
                            ipv6_list.append(ip_s)
                except Exception:
                    pass

                # Query reverse DNS (PTR) for public IPv4
                for ip_s in ipv4_list:
                    if not self.is_ssrf_restricted(ip_s):
                        try:
                            rev_name = dns.reversename.from_address(ip_s)
                            ptr_ans = await asyncio.wait_for(resolver.resolve(rev_name, dns.rdatatype.PTR), timeout=1.5)
                            ptrs = [str(r.target).rstrip(".") for r in ptr_ans]
                            ptr_map[ip_s] = ptrs
                        except Exception:
                            ptr_map[ip_s] = []

            rec.ipv4 = ipv4_list
            rec.ipv6 = ipv6_list

            return {
                "host": h,
                "preference": rec.preference,
                "provider": rec.provider_detected,
                "ipv4": ipv4_list,
                "ipv6": ipv6_list,
                "ptr": ptr_map,
                "is_cname": is_cname,
                "is_null": is_null,
                "is_ip_literal": is_ip_literal,
                "is_private": is_private,
                "resolves": len(ipv4_list) > 0 or len(ipv6_list) > 0,
            }

        mx_details: List[Dict[str, Any]] = []
        if records:
            mx_details = await asyncio.gather(*[_inspect_mx_host(r) for r in records])

        all_mail_ips: List[str] = []
        all_ptrs: Dict[str, List[str]] = {}
        for d in mx_details:
            for ip in d["ipv4"]:
                if ip not in all_mail_ips and not d["is_private"]:
                    all_mail_ips.append(ip)
            all_ptrs.update(d.get("ptr", {}))

        has_cname_mx = any(d["is_cname"] for d in mx_details)
        has_private_ip = any(d["is_private"] for d in mx_details)
        has_unresolvable = any(not d["resolves"] and not d["is_null"] for d in mx_details)
        has_null_mx = any(d["is_null"] for d in mx_details)
        all_mx_valid = not has_cname_mx and not has_private_ip and not has_unresolvable and not has_null_mx
        has_redundancy = len(records) >= 2

        # Infrastructure status
        if len(records) == 0:
            infra_status = "missing"
        elif has_private_ip or has_unresolvable or has_null_mx:
            infra_status = "critical"
        elif not has_redundancy or has_cname_mx or any(len(p) == 0 for p in all_ptrs.values()):
            infra_status = "warning"
        else:
            infra_status = "optimal"

        mail_infra = MailInfrastructureSummary(
            status=infra_status,
            mx_hosts_count=len(records),
            mx_host_count=len(records),
            mx_records=mx_details,
            resolved_mail_ips=all_mail_ips,
            ptr_records=all_ptrs,
            all_mx_valid=all_mx_valid,
            has_redundancy=has_redundancy,
            has_private_ip=has_private_ip,
            has_cname_mx=has_cname_mx,
            details=mx_details
        )

        status = "missing"
        if len(records) >= 2:
            status = "optimal"
        elif len(records) == 1:
            status = "warning"

        return MXSummary(
            status=status,
            record_count=len(records),
            records=records,
            raw=raw_lines,
            primary_provider=primary_provider
        ), raw_lines, mail_infra

    async def check_spf(self, domain: str, resolver: dns.asyncresolver.Resolver) -> Tuple[SPFSummary, List[str]]:
        """Query, parse, and validate SPF TXT record according to RFC 7208."""
        txt_records = await self._resolve_txt(resolver, domain)
        spf_records = [r for r in txt_records if r.strip().startswith("v=spf1")]

        if not spf_records:
            return SPFSummary(
                status="missing",
                raw=None,
                all_mechanism=None,
                dns_lookup_count=0,
                includes=[],
                ip4=[],
                ip6=[],
                has_multiple_records=False,
                exceeds_lookup_limit=False,
                syntax_valid=False
            ), txt_records

        has_multiple = len(spf_records) > 1
        raw_spf = spf_records[0]

        tokens = raw_spf.split()
        includes = []
        ip4_list = []
        ip6_list = []
        all_mech = None
        lookup_count = 0

        for token in tokens[1:]:
            lower_token = token.lower()
            if lower_token.startswith("include:"):
                includes.append(token.split(":", 1)[1])
                lookup_count += 1
            elif lower_token.startswith("ip4:"):
                ip4_list.append(token.split(":", 1)[1])
            elif lower_token.startswith("ip6:"):
                ip6_list.append(token.split(":", 1)[1])
            elif lower_token in ["a", "+a", "-a", "~a", "?a"] or lower_token.startswith("a:"):
                lookup_count += 1
            elif lower_token in ["mx", "+mx", "-mx", "~mx", "?mx"] or lower_token.startswith("mx:"):
                lookup_count += 1
            elif lower_token.startswith("ptr"):
                lookup_count += 1
            elif lower_token.startswith("exists:"):
                lookup_count += 1
            elif lower_token.startswith("redirect="):
                lookup_count += 1
            elif lower_token in ["-all", "~all", "?all", "+all", "all"]:
                all_mech = lower_token if lower_token.startswith(("-", "~", "?", "+")) else f"+{lower_token}"

        for inc in includes:
            if "google" in inc or "outlook" in inc or "sendgrid" in inc or "shopify" in inc:
                lookup_count += 1

        exceeds_limit = lookup_count > 10
        syntax_valid = not has_multiple and all_mech is not None

        if has_multiple or exceeds_limit or all_mech == "+all":
            status = "critical"
        elif all_mech in ["?all", None]:
            status = "warning"
        elif all_mech == "~all":
            status = "warning"
        elif all_mech == "-all" and not exceeds_limit:
            status = "optimal"
        else:
            status = "warning"

        return SPFSummary(
            status=status,
            raw=raw_spf,
            all_mechanism=all_mech,
            dns_lookup_count=lookup_count,
            includes=includes,
            ip4=ip4_list,
            ip6=ip6_list,
            has_multiple_records=has_multiple,
            exceeds_lookup_limit=exceeds_limit,
            syntax_valid=syntax_valid
        ), spf_records

    async def check_dkim_selector(
        self,
        domain: str,
        selector: str,
        resolver: dns.asyncresolver.Resolver
    ) -> DKIMSelectorResult:
        """Query and evaluate a specific DKIM selector."""
        qname = f"{selector}._domainkey.{domain}"
        txt_records = await self._resolve_txt(resolver, qname)
        dkim_records = [r for r in txt_records if "v=dkim1" in r.lower() or "p=" in r.lower()]

        if not dkim_records:
            return DKIMSelectorResult(
                selector=selector,
                status="missing",
                record_name=qname,
                raw=None,
                key_type=None,
                key_size_bits=None,
                has_public_key=False
            )

        raw = dkim_records[0]
        has_p = False
        p_val = ""
        key_type = "rsa"
        key_bits = None

        tags = [t.strip() for t in raw.split(";") if "=" in t]
        for tag in tags:
            k, v = tag.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "p":
                if v:
                    has_p = True
                    p_val = v
                    try:
                        raw_bytes = base64.b64decode(p_val + "==")
                        key_bits = len(raw_bytes) * 8
                    except Exception:
                        key_bits = len(p_val) * 6
            elif k == "k":
                key_type = v.lower()

        if not has_p or not p_val:
            status = "critical"
        elif key_bits and key_bits < 1024:
            status = "critical"
        elif key_bits and key_bits < 2048:
            status = "warning"
        else:
            status = "optimal"

        return DKIMSelectorResult(
            selector=selector,
            status=status,
            record_name=qname,
            raw=raw,
            key_type=key_type,
            key_size_bits=key_bits,
            has_public_key=has_p
        )

    async def check_dkim(
        self,
        domain: str,
        selectors: Optional[List[str]],
        resolver: dns.asyncresolver.Resolver
    ) -> Tuple[DKIMSummary, Dict[str, Any]]:
        """Query multiple DKIM selectors concurrently with strict input sanitization."""
        raw_list = (selectors or []) + DEFAULT_DKIM_SELECTORS
        sanitized_selectors = [self._sanitize_selector(s) for s in raw_list if self._sanitize_selector(s)]
        target_selectors = list(dict.fromkeys(sanitized_selectors))
        tasks = [self.check_dkim_selector(domain, sel, resolver) for sel in target_selectors]
        results: List[DKIMSelectorResult] = await asyncio.gather(*tasks)

        found_selectors = [r.selector for r in results if r.status != "missing"]
        active_records = [r for r in results if r.status != "missing"]

        if not found_selectors:
            status = "critical"
        elif any(r.status == "optimal" for r in active_records):
            status = "optimal"
        elif any(r.status == "warning" for r in active_records):
            status = "warning"
        else:
            status = "critical"

        return DKIMSummary(
            status=status,
            tested_selectors=target_selectors,
            found_selectors=found_selectors,
            records=active_records
        ), {r.selector: r.raw for r in active_records}

    async def check_dmarc(self, domain: str, resolver: dns.asyncresolver.Resolver) -> Tuple[DMARCSummary, List[str]]:
        """Query and evaluate DMARC TXT record at _dmarc.{domain}."""
        qname = f"_dmarc.{domain}"
        txt_records = await self._resolve_txt(resolver, qname)
        dmarc_records = [r for r in txt_records if r.strip().startswith("v=DMARC1")]

        if not dmarc_records:
            return DMARCSummary(
                status="critical",
                raw=None,
                policy=None,
                subdomain_policy=None,
                percentage=100,
                rua_emails=[],
                ruf_emails=[],
                adkim_alignment="r",
                aspf_alignment="r",
                syntax_valid=False
            ), txt_records

        raw = dmarc_records[0]
        tags = [t.strip() for t in raw.split(";") if "=" in t]
        policy = None
        subdomain_policy = None
        percentage = 100
        rua_list = []
        ruf_list = []
        adkim = "r"
        aspf = "r"

        for tag in tags:
            k, v = tag.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "p":
                policy = v.lower()
            elif k == "sp":
                subdomain_policy = v.lower()
            elif k == "pct":
                try:
                    percentage = int(v)
                except ValueError:
                    percentage = 100
            elif k == "rua":
                rua_list = [email.replace("mailto:", "").strip() for email in v.split(",")]
            elif k == "ruf":
                ruf_list = [email.replace("mailto:", "").strip() for email in v.split(",")]
            elif k == "adkim":
                adkim = v.lower()
            elif k == "aspf":
                aspf = v.lower()

        syntax_valid = policy in ["none", "quarantine", "reject"]

        if policy == "reject" and rua_list:
            status = "optimal"
        elif policy == "quarantine":
            status = "optimal" if rua_list else "warning"
        elif policy == "none":
            status = "warning"
        else:
            status = "critical"

        return DMARCSummary(
            status=status,
            raw=raw,
            policy=policy,
            subdomain_policy=subdomain_policy,
            percentage=percentage,
            rua_emails=rua_list,
            ruf_emails=ruf_list,
            adkim_alignment=adkim,
            aspf_alignment=aspf,
            syntax_valid=syntax_valid
        ), dmarc_records

    async def check_bimi(self, domain: str, resolver: dns.asyncresolver.Resolver) -> Tuple[BIMISummary, List[str]]:
        """Query BIMI record at default._bimi.{domain}."""
        qname = f"default._bimi.{domain}"
        txt_records = await self._resolve_txt(resolver, qname)
        bimi_records = [r for r in txt_records if r.strip().startswith("v=BIMI1")]

        if not bimi_records:
            return BIMISummary(status="missing", raw=None, logo_url=None, vmc_url=None), txt_records

        raw = bimi_records[0]
        logo_url = None
        vmc_url = None

        tags = [t.strip() for t in raw.split(";") if "=" in t]
        for tag in tags:
            k, v = tag.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "l":
                logo_url = v
            elif k == "a":
                vmc_url = v

        return BIMISummary(
            status="optimal" if logo_url else "missing",
            raw=raw,
            logo_url=logo_url,
            vmc_url=vmc_url
        ), bimi_records

    async def audit_domain(
        self,
        domain: str,
        custom_selectors: Optional[List[str]] = None,
        include_reputation: bool = True
    ) -> Tuple[DiagnosticSummary, Dict[str, Any], float]:
        """
        Execute full asynchronous parallel DNS audit across:
        1. DNS core records (A, AAAA, NS, SOA, CAA, CNAME)
        2. Email Authentication (SPF, DKIM, DMARC, BIMI)
        3. Mail Infrastructure (MX hosts, IPs, PTR reverse DNS)
        4. Reputation / DNSBL scans (domain + mail server IPs)
        """
        start_time = time.perf_counter()
        clean_domain = self._clean_domain(domain)
        resolver = self._get_resolver()

        dns_task = self.check_dns_records(clean_domain, resolver)
        mx_task = self.check_mx(clean_domain, resolver)
        spf_task = self.check_spf(clean_domain, resolver)
        dkim_task = self.check_dkim(clean_domain, custom_selectors, resolver)
        dmarc_task = self.check_dmarc(clean_domain, resolver)
        bimi_task = self.check_bimi(clean_domain, resolver)

        (
            (dns_summary, raw_dns),
            (mx_res, raw_mx, mail_infra_res),
            (spf_res, raw_spf),
            (dkim_res, raw_dkim),
            (dmarc_res, raw_dmarc),
            (bimi_res, raw_bimi)
        ) = await asyncio.gather(dns_task, mx_task, spf_task, dkim_task, dmarc_task, bimi_task)

        # Reputation / RBL Check (Domain + Mail Server IPs)
        rep_summary = None
        raw_rep: Dict[str, Any] = {}
        if include_reputation:
            try:
                from app.services.dns.rbl_scanner import rbl_scanner
                mail_ips = mail_infra_res.resolved_mail_ips if mail_infra_res else []
                rbl_result = await asyncio.wait_for(
                    rbl_scanner.scan_domain(clean_domain, additional_ips=mail_ips),
                    timeout=4.0
                )
                rep_summary = ReputationSummary(
                    clean_count=rbl_result.rbl_clean_count,
                    listed_count=rbl_result.rbl_listed_count,
                    unknown_count=rbl_result.rbl_unknown_count,
                    error_count=rbl_result.rbl_error_count,
                    total_providers=rbl_result.rbl_total_count,
                    overall_status=rbl_result.overall_status,
                    highest_severity=rbl_result.highest_severity,
                    listings=[
                        {
                            "provider_id": r.provider_id,
                            "provider_name": r.provider_name,
                            "zone": r.zone,
                            "target_type": r.target_type,
                            "status": r.status,
                            "severity": r.severity,
                            "queried_target": r.queried_target,
                            "response_codes": r.response_codes,
                            "latency_ms": r.latency_ms,
                            "message": r.message,
                            "delisting_url": r.delisting_url,
                        }
                        for r in rbl_result.results
                    ]
                )
                raw_rep = rbl_result.model_dump()
            except Exception as e:
                logger.warning(f"RBL reputation scan notice for {clean_domain}: {e}")
                rep_summary = ReputationSummary(
                    clean_count=0,
                    listed_count=0,
                    unknown_count=0,
                    error_count=10,
                    total_providers=10,
                    overall_status="unavailable",
                    highest_severity="none",
                    listings=[]
                )
                raw_rep = {"error": str(e), "overall_status": "unavailable"}

        exec_ms = round((time.perf_counter() - start_time) * 1000, 2)

        summary = DiagnosticSummary(
            mx=mx_res,
            spf=spf_res,
            dkim=dkim_res,
            dmarc=dmarc_res,
            bimi=bimi_res,
            dns_records=dns_summary,
            mail_infrastructure=mail_infra_res,
            reputation=rep_summary
        )

        raw_responses = {
            "dns": raw_dns,
            "mx": raw_mx,
            "mail_infrastructure": mail_infra_res.model_dump() if mail_infra_res else None,
            "spf": raw_spf,
            "dkim": raw_dkim,
            "dmarc": raw_dmarc,
            "bimi": raw_bimi,
            "reputation": raw_rep
        }

        return summary, raw_responses, exec_ms
