"""
InboundCheck - SPF Conflict Resolution & Merge Engine
======================================================
Autonomous RFC 7208 multi-record consolidation, semantic mechanism deduplication,
and recursive DNS lookup budget analyzer.
"""

import re
import uuid
import hashlib
import ipaddress
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Set, Tuple

import dns.asyncresolver
import dns.resolver
import dns.exception

from app.schemas.dns import (
    SpfMechanism,
    SpfLookupBudget,
    SpfMergeWarning,
    SpfMergePlanResponse,
)
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.supabase_client import supabase_service

logger = logging.getLogger("SpfMergeEngine")


class SpfMergeEngine:
    """
    RFC 7208 SPF consolidation engine with cycle-detected recursive lookup budgeting
    and deterministic deduplication.
    """

    def __init__(self, nameservers: Optional[List[str]] = None, timeout: float = 3.5):
        self.diagnostic_engine = DNSDiagnosticEngine(nameservers=nameservers, timeout=timeout)
        self.timeout = timeout
        self.nameservers = nameservers or ["1.1.1.1", "8.8.8.8"]

    def _get_resolver(self) -> dns.asyncresolver.Resolver:
        resolver = dns.asyncresolver.Resolver()
        resolver.nameservers = self.nameservers
        resolver.timeout = self.timeout
        resolver.lifetime = self.timeout * 2
        return resolver

    async def fetch_source_records(
        self, domain: str, resolver: Optional[dns.asyncresolver.Resolver] = None
    ) -> List[str]:
        """
        Query TXT records for apex domain and isolate all records starting with v=spf1.
        """
        clean_domain = self.diagnostic_engine._clean_domain(domain)
        if DNSDiagnosticEngine.is_ssrf_restricted(clean_domain):
            logger.warning(f"Anti-SSRF guard rejected domain: {clean_domain}")
            return []

        res = resolver or self._get_resolver()
        try:
            txt_records = await self.diagnostic_engine._resolve_txt(res, clean_domain)
            spf_records = [
                r.strip() for r in txt_records if r.strip().lower().startswith("v=spf1")
            ]
            return spf_records
        except Exception as e:
            logger.debug(f"Failed to fetch SPF source records for {domain}: {e}")
            return []

    def _normalize_mechanism(
        self, token: str, record_idx: int
    ) -> Tuple[Optional[SpfMechanism], List[SpfMergeWarning]]:
        """
        Parse and canonicalize a single mechanism or modifier token.
        """
        warnings: List[SpfMergeWarning] = []
        clean = token.strip()
        if not clean:
            return None, warnings

        # Macro detection: % followed by macro letter or brace
        if "%" in clean:
            warnings.append(
                SpfMergeWarning(
                    code="SPF_MACRO_DETECTED",
                    severity="critical",
                    message=f"Macro syntax found in token '{clean}'. Automated merging of dynamic macros requires manual policy review.",
                )
            )

        # Qualifiers (+, -, ~, ?)
        qualifier = "+"
        body = clean
        if clean[0] in "+-~?":
            qualifier = clean[0]
            body = clean[1:]

        lower_body = body.lower()

        # Terminal mechanism: all
        if lower_body == "all":
            return (
                SpfMechanism(
                    raw=clean,
                    kind="all",
                    qualifier=qualifier,
                    normalized_value="all",
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # include:<domain>
        if lower_body.startswith("include:"):
            target_domain = body.split(":", 1)[1].strip().lower().rstrip(".")
            return (
                SpfMechanism(
                    raw=clean,
                    kind="include",
                    qualifier=qualifier,
                    normalized_value=target_domain,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # ip4:<ip/cidr>
        if lower_body.startswith("ip4:"):
            raw_ip = body.split(":", 1)[1].strip()
            try:
                net = ipaddress.ip_network(raw_ip, strict=False)
                normalized = str(net)
            except ValueError:
                normalized = raw_ip
                warnings.append(
                    SpfMergeWarning(
                        code="SPF_INVALID_IP4",
                        severity="critical",
                        message=f"Invalid IPv4 network definition: '{raw_ip}'",
                    )
                )

            return (
                SpfMechanism(
                    raw=clean,
                    kind="ip4",
                    qualifier=qualifier,
                    normalized_value=normalized,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # ip6:<ip/cidr>
        if lower_body.startswith("ip6:"):
            raw_ip = body.split(":", 1)[1].strip()
            try:
                net = ipaddress.ip_network(raw_ip, strict=False)
                normalized = str(net)
            except ValueError:
                normalized = raw_ip
                warnings.append(
                    SpfMergeWarning(
                        code="SPF_INVALID_IP6",
                        severity="critical",
                        message=f"Invalid IPv6 network definition: '{raw_ip}'",
                    )
                )

            return (
                SpfMechanism(
                    raw=clean,
                    kind="ip6",
                    qualifier=qualifier,
                    normalized_value=normalized,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # a or a:<domain> or a/<prefix>
        if lower_body == "a" or lower_body.startswith("a:") or lower_body.startswith("a/"):
            return (
                SpfMechanism(
                    raw=clean,
                    kind="a",
                    qualifier=qualifier,
                    normalized_value=lower_body,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # mx or mx:<domain> or mx/<prefix>
        if lower_body == "mx" or lower_body.startswith("mx:") or lower_body.startswith("mx/"):
            return (
                SpfMechanism(
                    raw=clean,
                    kind="mx",
                    qualifier=qualifier,
                    normalized_value=lower_body,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # ptr or ptr:<domain>
        if lower_body == "ptr" or lower_body.startswith("ptr:"):
            warnings.append(
                SpfMergeWarning(
                    code="SPF_PTR_DEPRECATED",
                    severity="critical",
                    message=f"Mechanism '{clean}' uses PTR which is explicitly deprecated in RFC 7208 Section 5.5.",
                )
            )
            return (
                SpfMechanism(
                    raw=clean,
                    kind="ptr",
                    qualifier=qualifier,
                    normalized_value=lower_body,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # exists:<domain>
        if lower_body.startswith("exists:"):
            return (
                SpfMechanism(
                    raw=clean,
                    kind="exists",
                    qualifier=qualifier,
                    normalized_value=lower_body,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # redirect=<domain>
        if lower_body.startswith("redirect="):
            warnings.append(
                SpfMergeWarning(
                    code="SPF_REDIRECT_MODIFIER",
                    severity="warning",
                    message=f"Redirect modifier '{clean}' found. Merging redirects into standard SPF policy requires manual review.",
                )
            )
            return (
                SpfMechanism(
                    raw=clean,
                    kind="redirect",
                    qualifier="+",
                    normalized_value=lower_body,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # exp=<domain> modifier
        if lower_body.startswith("exp="):
            return (
                SpfMechanism(
                    raw=clean,
                    kind="unknown",
                    qualifier="+",
                    normalized_value=lower_body,
                    source_record_indexes=[record_idx],
                ),
                warnings,
            )

        # Unknown term
        warnings.append(
            SpfMergeWarning(
                code="SPF_UNKNOWN_MECHANISM",
                severity="warning",
                message=f"Unrecognized mechanism or modifier token: '{clean}'",
            )
        )
        return (
            SpfMechanism(
                raw=clean,
                kind="unknown",
                qualifier=qualifier,
                normalized_value=lower_body,
                source_record_indexes=[record_idx],
            ),
            warnings,
        )

    async def _calculate_recursive_lookups(
        self,
        domain: str,
        mechanisms: List[SpfMechanism],
        resolver: dns.asyncresolver.Resolver,
        visited_domains: Optional[Set[str]] = None,
        depth: int = 0,
        max_depth: int = 6,
    ) -> Tuple[int, List[str], List[SpfMergeWarning]]:
        """
        Recursively compute DNS lookup consumption with cycle detection.
        RFC 7208 lookup mechanisms: include, a, mx, ptr, exists, redirect.
        """
        if visited_domains is None:
            visited_domains = set()

        clean_current = domain.lower().rstrip(".")
        visited_domains.add(clean_current)

        recursively_resolved = 0
        resolution_failures: List[str] = []
        warnings: List[SpfMergeWarning] = []

        if depth >= max_depth:
            warnings.append(
                SpfMergeWarning(
                    code="SPF_MAX_DEPTH_EXCEEDED",
                    severity="warning",
                    message=f"Maximum include recursion depth ({max_depth}) reached for {domain}.",
                )
            )
            return recursively_resolved, resolution_failures, warnings

        # Process each mechanism
        for mech in mechanisms:
            if mech.kind == "include":
                target = mech.normalized_value.lower().rstrip(".")
                if target in visited_domains:
                    warnings.append(
                        SpfMergeWarning(
                            code="SPF_CIRCULAR_INCLUDE",
                            severity="critical",
                            message=f"Circular reference detected in SPF include tree: {target}",
                        )
                    )
                    continue

                # Each include mechanism incurs 1 lookup itself plus any lookups in the included record
                if depth > 0:
                    recursively_resolved += 1

                # Query target domain SPF
                try:
                    txts = await self.diagnostic_engine._resolve_txt(resolver, target)
                    nested_spf = [
                        r.strip() for r in txts if r.strip().lower().startswith("v=spf1")
                    ]
                    if not nested_spf:
                        continue

                    # Parse nested mechanisms
                    nested_tokens = nested_spf[0].split()[1:]
                    nested_mechs: List[SpfMechanism] = []
                    for t in nested_tokens:
                        m, _ = self._normalize_mechanism(t, -1)
                        if m and m.kind not in ("all", "unknown"):
                            nested_mechs.append(m)

                    # Lookups inside nested record (a, mx, ptr, exists, redirect)
                    for nm in nested_mechs:
                        if nm.kind in ("a", "mx", "ptr", "exists", "redirect"):
                            recursively_resolved += 1

                    # Recurse further
                    sub_count, sub_fails, sub_warns = await self._calculate_recursive_lookups(
                        domain=target,
                        mechanisms=nested_mechs,
                        resolver=resolver,
                        visited_domains=set(visited_domains),
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                    recursively_resolved += sub_count
                    resolution_failures.extend(sub_fails)
                    warnings.extend(sub_warns)

                except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout) as e:
                    fail_msg = f"Failed to resolve SPF include for {target}: {type(e).__name__}"
                    resolution_failures.append(fail_msg)
                    warnings.append(
                        SpfMergeWarning(
                            code="SPF_INCLUDE_RESOLUTION_FAILURE",
                            severity="warning",
                            message=fail_msg,
                        )
                    )
                except Exception as e:
                    fail_msg = f"Resolution error on {target}: {str(e)}"
                    resolution_failures.append(fail_msg)

        return recursively_resolved, resolution_failures, warnings

    async def create_plan(
        self,
        domain: str,
        user_id: str,
        preferred_qualifier: str = "~all",
        provider_hints: Optional[List[str]] = None,
        source_records: Optional[List[str]] = None,
        resolver: Optional[dns.asyncresolver.Resolver] = None,
        domain_id: Optional[str] = None,
    ) -> SpfMergePlanResponse:
        """
        Analyze current SPF state, deduplicate terms, calculate lookups, and formulate safe merge plan.
        """
        clean_domain = self.diagnostic_engine._clean_domain(domain)
        res = resolver or self._get_resolver()

        # Step 1: Fetch source records if not directly supplied (e.g. in test suite)
        if source_records is None:
            source_records = await self.fetch_source_records(clean_domain, res)

        warnings: List[SpfMergeWarning] = []
        removed_duplicates: List[str] = []

        # Step 2: Validate RFC 7208 multi-record conflict
        if len(source_records) == 0:
            warnings.append(
                SpfMergeWarning(
                    code="SPF_MISSING_RECORD",
                    severity="warning",
                    message="No existing v=spf1 TXT records found. Generating a new baseline SPF policy.",
                )
            )
        elif len(source_records) > 1:
            warnings.append(
                SpfMergeWarning(
                    code="RFC7208_MULTIPLE_RECORDS",
                    severity="critical",
                    message=f"Found {len(source_records)} conflicting v=spf1 TXT records. RFC 7208 mandates exactly one SPF record; receivers will evaluate this as PermError.",
                )
            )

        # Step 3: Parse and deduplicate mechanisms across all source records
        dedup_map: Dict[Tuple[str, str], SpfMechanism] = {}
        has_ptr = False
        has_redirect = False
        has_macro = False
        syntax_errors = False

        for idx, rec in enumerate(source_records):
            tokens = rec.split()
            if not tokens or tokens[0].lower() != "v=spf1":
                continue

            for tok in tokens[1:]:
                mech, mech_warns = self._normalize_mechanism(tok, idx)
                warnings.extend(mech_warns)

                if any(w.code == "SPF_MACRO_DETECTED" for w in mech_warns):
                    has_macro = True
                if any(w.severity == "critical" for w in mech_warns):
                    syntax_errors = True

                if not mech:
                    continue

                if mech.kind == "ptr":
                    has_ptr = True
                elif mech.kind == "redirect":
                    has_redirect = True
                elif mech.kind == "all":
                    continue  # Terminal qualifier handled separately

                key = (mech.kind, mech.normalized_value)
                if key in dedup_map:
                    existing = dedup_map[key]
                    if idx not in existing.source_record_indexes:
                        existing.source_record_indexes.append(idx)
                    removed_duplicates.append(mech.raw)
                else:
                    dedup_map[key] = mech

        # Incorporate optional provider hints if specified (e.g. shops.shopify.com)
        if provider_hints:
            for hint in provider_hints:
                hint_clean = hint.strip().lower()
                if hint_clean and ("include", hint_clean) not in dedup_map:
                    dedup_map[("include", hint_clean)] = SpfMechanism(
                        raw=f"include:{hint_clean}",
                        kind="include",
                        qualifier="+",
                        normalized_value=hint_clean,
                        source_record_indexes=[],
                    )

        mechanisms = list(dedup_map.values())

        # Step 4: Calculate DNS lookup budget
        # Direct static terms in apex record: include, a, mx, ptr, exists, redirect
        static_terms = sum(
            1 for m in mechanisms if m.kind in ("include", "a", "mx", "ptr", "exists", "redirect")
        )

        # Recursive lookup count
        rec_lookups, res_fails, rec_warns = await self._calculate_recursive_lookups(
            domain=clean_domain,
            mechanisms=mechanisms,
            resolver=res,
            visited_domains=set(),
            depth=0,
        )
        warnings.extend(rec_warns)

        total_lookups = static_terms + rec_lookups
        lookup_status = "within_limit" if total_lookups <= 10 else "over_limit"

        if total_lookups > 10:
            warnings.append(
                SpfMergeWarning(
                    code="RFC7208_LOOKUP_LIMIT_EXCEEDED",
                    severity="critical",
                    message=f"Total DNS lookup budget ({total_lookups}/10) exceeds the RFC 7208 limit of 10 lookups. Inbound MTAs will fail SPF evaluation with PermError.",
                )
            )

        lookup_budget = SpfLookupBudget(
            static_terms=static_terms,
            recursively_resolved_terms=rec_lookups,
            maximum_allowed=10,
            status=lookup_status,
            resolution_failures=res_fails,
        )

        # Step 5: Formulate Proposed Record
        # Order: ip4, ip6, a, mx, include, exists, other, preferred_qualifier
        parts: List[str] = ["v=spf1"]

        # Sort IP4
        ip4_mechs = sorted(
            [m for m in mechanisms if m.kind == "ip4"],
            key=lambda x: x.normalized_value,
        )
        for m in ip4_mechs:
            qual_prefix = m.qualifier if m.qualifier != "+" else ""
            parts.append(f"{qual_prefix}ip4:{m.normalized_value}")

        # Sort IP6
        ip6_mechs = sorted(
            [m for m in mechanisms if m.kind == "ip6"],
            key=lambda x: x.normalized_value,
        )
        for m in ip6_mechs:
            qual_prefix = m.qualifier if m.qualifier != "+" else ""
            parts.append(f"{qual_prefix}ip6:{m.normalized_value}")

        # Sort a
        a_mechs = sorted(
            [m for m in mechanisms if m.kind == "a"],
            key=lambda x: x.normalized_value,
        )
        for m in a_mechs:
            parts.append(m.raw if m.raw.startswith(("+", "-", "~", "?")) else m.normalized_value)

        # Sort mx
        mx_mechs = sorted(
            [m for m in mechanisms if m.kind == "mx"],
            key=lambda x: x.normalized_value,
        )
        for m in mx_mechs:
            parts.append(m.raw if m.raw.startswith(("+", "-", "~", "?")) else m.normalized_value)

        # Sort include
        inc_mechs = sorted(
            [m for m in mechanisms if m.kind == "include"],
            key=lambda x: x.normalized_value,
        )
        for m in inc_mechs:
            qual_prefix = m.qualifier if m.qualifier != "+" else ""
            parts.append(f"{qual_prefix}include:{m.normalized_value}")

        # Other terms (exists, etc.)
        other_mechs = sorted(
            [m for m in mechanisms if m.kind not in ("ip4", "ip6", "a", "mx", "include")],
            key=lambda x: x.normalized_value,
        )
        for m in other_mechs:
            parts.append(m.raw)

        # Terminal qualifier
        terminal = preferred_qualifier if preferred_qualifier in ("~all", "-all") else "~all"
        parts.append(terminal)

        proposed_record = " ".join(parts)

        # Step 6: Determine Safety and Manual Review Flags
        safe_to_apply = (
            lookup_status == "within_limit"
            and not has_ptr
            and not has_redirect
            and not has_macro
            and not syntax_errors
            and len(res_fails) == 0
        )
        requires_manual_review = not safe_to_apply

        # Step 7: Deterministic Plan Hash and Expiration
        hash_input = f"{clean_domain}:{','.join(sorted(source_records))}:{proposed_record}"
        plan_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=24)).isoformat()
        plan_id = str(uuid.uuid4())

        # Step 8: Persist merge plan into public.spf_merge_plans
        plan_record = {
            "id": plan_id,
            "user_id": user_id,
            "domain_id": domain_id,
            "domain_name": clean_domain,
            "source_records": source_records,
            "proposed_record": proposed_record,
            "plan_hash": plan_hash,
            "safe_to_apply": safe_to_apply,
            "requires_manual_review": requires_manual_review,
            "lookup_budget": lookup_budget.model_dump(),
            "warnings": [w.model_dump() for w in warnings],
            "expires_at": expires_at,
            "created_at": now.isoformat(),
        }

        try:
            supabase_service.save_spf_merge_plan(plan_record)
        except Exception as e:
            logger.warning(f"Failed to persist spf_merge_plan: {e}")

        return SpfMergePlanResponse(
            plan_id=plan_id,
            domain=clean_domain,
            source_records=source_records,
            proposed_record=proposed_record,
            mechanisms=mechanisms,
            removed_duplicates=removed_duplicates,
            warnings=warnings,
            lookup_budget=lookup_budget,
            safe_to_apply=safe_to_apply,
            requires_manual_review=requires_manual_review,
            expires_at=expires_at,
        )


spf_merge_engine = SpfMergeEngine()
