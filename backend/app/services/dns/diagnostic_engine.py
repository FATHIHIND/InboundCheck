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
from typing import List, Dict, Any, Optional, Tuple
import dns.asyncresolver
import dns.resolver
import dns.rdatatype
import dns.exception

from app.schemas.dns import (
    MXRecordItem,
    MXSummary,
    SPFSummary,
    DKIMSelectorResult,
    DKIMSummary,
    DMARCSummary,
    BIMISummary,
    DiagnosticSummary
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

    def _clean_domain(self, domain: str) -> str:
        """Sanitize domain string and prevent SSRF / injection attacks."""
        d = domain.strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = re.sub(r"/.*$", "", d)
        d = re.sub(r":\d+$", "", d)
        d = d.strip(".")

        # SSRF & Injection checks
        if not d or len(d) > 253:
            raise ValueError(f"Invalid domain length: '{domain}'")

        if d in self.BLOCKED_DOMAINS or any(d.endswith(suffix) for suffix in self.BLOCKED_SUFFIXES):
            raise ValueError(f"Domain '{d}' is restricted or points to a private/internal target.")

        # Check for private IP patterns (10.x, 192.168.x, 172.16-31.x)
        if re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|127\.|0\.)", d):
            raise ValueError(f"Direct IP addresses or private networks are not allowed: '{d}'")

        # RFC 1035 Domain Format Validation
        domain_pattern = r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
        if not re.match(domain_pattern, d):
            raise ValueError(f"Invalid domain format: '{d}'")

        return d

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

    async def check_mx(self, domain: str, resolver: dns.asyncresolver.Resolver) -> Tuple[MXSummary, List[str]]:
        """Query and evaluate MX records for the apex domain."""
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
        ), raw_lines

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
        custom_selectors: Optional[List[str]] = None
    ) -> Tuple[DiagnosticSummary, Dict[str, Any], float]:
        """
        Execute full asynchronous parallel DNS audit across MX, SPF, DKIM, DMARC, and BIMI.
        """
        start_time = time.perf_counter()
        clean_domain = self._clean_domain(domain)
        resolver = self._get_resolver()

        mx_task = self.check_mx(clean_domain, resolver)
        spf_task = self.check_spf(clean_domain, resolver)
        dkim_task = self.check_dkim(clean_domain, custom_selectors, resolver)
        dmarc_task = self.check_dmarc(clean_domain, resolver)
        bimi_task = self.check_bimi(clean_domain, resolver)

        (mx_res, raw_mx), (spf_res, raw_spf), (dkim_res, raw_dkim), (dmarc_res, raw_dmarc), (bimi_res, raw_bimi) = (
            await asyncio.gather(mx_task, spf_task, dkim_task, dmarc_task, bimi_task)
        )

        exec_ms = round((time.perf_counter() - start_time) * 1000, 2)

        summary = DiagnosticSummary(
            mx=mx_res,
            spf=spf_res,
            dkim=dkim_res,
            dmarc=dmarc_res,
            bimi=bimi_res
        )

        raw_responses = {
            "mx": raw_mx,
            "spf": raw_spf,
            "dkim": raw_dkim,
            "dmarc": raw_dmarc,
            "bimi": raw_bimi
        }

        return summary, raw_responses, exec_ms
