"""
InboundCheck - AI Generation Telemetry Aggregation Service (Phase 17D.4 / 17D.4.1)
================================================================================
Computes operational aggregates, metrics, and quota reconciliation reports from
public.ai_generation_telemetry.

AUTHORITY INVARIANT:
AI telemetry aggregates are strictly observational. They MUST NEVER be used as authoritative
sources for:
- billing
- subscription tier / plan state
- monthly quota enforcement (authoritative: public.ai_generation_usage)
- RPM enforcement (authoritative: rate_limit_ai_tier)
- concurrency enforcement (authoritative: public.ai_concurrency_leases)
- authentication or authorization

DATA RETENTION INVARIANT:
- Raw telemetry: 90 days
- Monthly aggregates / quota history: 24 months
"""

import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from app.services.supabase_client import supabase_service
from app.services.ai.plan_policy import AIPlanPolicy, PLAN_POLICIES

logger = logging.getLogger("AITelemetryAggregation")


def calculate_p95(values: List[int]) -> int:
    """Calculate 95th percentile using ceiling index selection."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    idx = int(math.ceil(0.95 * len(sorted_vals))) - 1
    clamped_idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[clamped_idx]


def compute_aggregates(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Pure aggregation function across raw ai_generation_telemetry records.
    Strictly preserves NULL vs 0 semantics for cost and token counts:
    - cost_status == 'zero_cost' -> 0 micro-USD (known)
    - cost_status in ('calculated', 'reported') -> numeric micro-USD (known)
    - cost_status == 'unreported' or cost_micro_usd IS NULL -> unknown (unreported count)
    - prompt_tokens / completion_tokens / total_tokens NULL -> unknown (unreported count)
    """
    total_generations = len(records)
    successful_generations = 0
    primary_success_count = 0
    fallback_success_count = 0
    total_fallback_count = 0
    liquid_failed_count = 0
    timeout_count = 0
    error_count = 0
    quota_consumed_count = 0

    known_prompt_tokens = 0
    known_completion_tokens = 0
    known_total_tokens = 0
    unreported_tokens_count = 0

    known_cost_micro_usd = 0
    unreported_cost_count = 0

    latencies: List[int] = []
    provider_latencies: List[int] = []

    by_outcome: Dict[str, int] = {
        "success": 0,
        "success_via_fallback": 0,
        "liquid_failed": 0,
        "timeout": 0,
        "error": 0,
    }
    by_plan_tier: Dict[str, int] = {
        "starter": 0,
        "growth": 0,
        "agency": 0,
    }
    by_provider: Dict[str, int] = {}

    for r in records:
        outcome = r.get("outcome") or "unknown"
        fallback_used = bool(r.get("fallback_used", False))
        quota_consumed = bool(r.get("quota_consumed", False))
        plan_tier = r.get("plan_tier") or "unknown"
        provider = r.get("provider") or "unknown"

        # 1. Outcome & Fallback counts
        if outcome in by_outcome:
            by_outcome[outcome] += 1
        else:
            by_outcome[outcome] = 1

        if outcome in ("success", "success_via_fallback"):
            successful_generations += 1

        if outcome == "success" and not fallback_used:
            primary_success_count += 1
        elif outcome == "success_via_fallback" and fallback_used:
            fallback_success_count += 1

        if fallback_used:
            total_fallback_count += 1

        if outcome == "liquid_failed":
            liquid_failed_count += 1
        elif outcome == "timeout":
            timeout_count += 1
        elif outcome == "error":
            error_count += 1

        # 2. Quota consumed indicator
        if quota_consumed:
            quota_consumed_count += 1

        # 3. Plan tier & Provider breakdowns
        by_plan_tier[plan_tier] = by_plan_tier.get(plan_tier, 0) + 1
        by_provider[provider] = by_provider.get(provider, 0) + 1

        # 4. Token metrics (Nullable semantics)
        pt = r.get("prompt_tokens")
        ct = r.get("completion_tokens")
        tt = r.get("total_tokens")

        if tt is not None and isinstance(tt, (int, float)) and tt >= 0:
            known_total_tokens += int(tt)
            if pt is not None and isinstance(pt, (int, float)) and pt >= 0:
                known_prompt_tokens += int(pt)
            if ct is not None and isinstance(ct, (int, float)) and ct >= 0:
                known_completion_tokens += int(ct)
        else:
            unreported_tokens_count += 1

        # 5. Cost metrics (Strict NULL vs 0 distinction)
        cs = r.get("cost_status")
        c_usd = r.get("cost_micro_usd")

        if cs == "zero_cost":
            known_cost_micro_usd += 0
        elif cs in ("calculated", "reported") and c_usd is not None and isinstance(c_usd, (int, float)) and c_usd >= 0:
            known_cost_micro_usd += int(c_usd)
        else:
            # Unreported or NULL cost
            unreported_cost_count += 1

        # 6. Latency distributions
        lat = r.get("latency_ms")
        if lat is not None and isinstance(lat, (int, float)) and lat >= 0:
            latencies.append(int(lat))

        plat = r.get("provider_latency_ms")
        if plat is not None and isinstance(plat, (int, float)) and plat >= 0:
            provider_latencies.append(int(plat))

    avg_latency_ms = round(sum(latencies) / len(latencies)) if latencies else 0
    p95_latency_ms = calculate_p95(latencies)
    avg_provider_latency_ms = (
        round(sum(provider_latencies) / len(provider_latencies)) if provider_latencies else None
    )

    return {
        "total_generations": total_generations,
        "successful_generations": successful_generations,
        "primary_success_count": primary_success_count,
        "fallback_success_count": fallback_success_count,
        "total_fallback_count": total_fallback_count,
        "liquid_failed_count": liquid_failed_count,
        "timeout_count": timeout_count,
        "error_count": error_count,
        "quota_consumed_count": quota_consumed_count,
        "known_prompt_tokens": known_prompt_tokens,
        "known_completion_tokens": known_completion_tokens,
        "known_total_tokens": known_total_tokens,
        "unreported_tokens_count": unreported_tokens_count,
        "known_cost_micro_usd": known_cost_micro_usd,
        "unreported_cost_count": unreported_cost_count,
        "avg_latency_ms": avg_latency_ms,
        "avg_provider_latency_ms": avg_provider_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "by_outcome": by_outcome,
        "by_plan_tier": by_plan_tier,
        "by_provider": by_provider,
    }


class AITelemetryAggregationService:
    """
    High-level aggregation and reporting service for AI usage and operational telemetry.
    """

    @staticmethod
    def get_merchant_usage_summary(
        user_id: str,
        billing_period: Optional[str] = None,
        ai_policy: Optional[AIPlanPolicy] = None,
    ) -> Dict[str, Any]:
        """
        Produce merchant-facing telemetry and quota summary with strict server-side tenant isolation.
        Sourced from:
        - Authoritative quota: public.ai_generation_usage (via get_ai_monthly_usage)
        - Observational telemetry: public.ai_generation_telemetry
        Zero internal provider names, upstream pricing, or prompt contents are exposed.
        """
        clean_uid = str(user_id).strip()
        period = (billing_period or datetime.now(timezone.utc).strftime("%Y-%m")).strip()

        # 1. Authoritative quota ledger lookup
        used_quota = supabase_service.get_ai_monthly_usage(clean_uid, period)
        tier_name = ai_policy.tier if ai_policy else "starter"
        policy = ai_policy or PLAN_POLICIES.get(tier_name, PLAN_POLICIES["starter"])
        monthly_limit = policy.monthly_generation_limit
        remaining_quota = max(0, monthly_limit - used_quota)

        # 2. Observational telemetry lookup (tenant-isolated to clean_uid)
        records = supabase_service.get_ai_telemetry_records(user_id=clean_uid, billing_period=period)
        aggs = compute_aggregates(records)

        return {
            "billing_period": period,
            "tier": tier_name,
            "quota": {
                "monthly_limit": monthly_limit,
                "used": used_quota,
                "remaining": remaining_quota,
            },
            "telemetry_summary": {
                "total_generations": aggs["total_generations"],
                "successful_generations": aggs["successful_generations"],
                "primary_success_count": aggs["primary_success_count"],
                "fallback_success_count": aggs["fallback_success_count"],
                "total_fallback_count": aggs["total_fallback_count"],
                "liquid_failed_count": aggs["liquid_failed_count"],
                "timeout_count": aggs["timeout_count"],
                "error_count": aggs["error_count"],
                "avg_latency_ms": aggs["avg_latency_ms"],
                "p95_latency_ms": aggs["p95_latency_ms"],
            },
        }

    @staticmethod
    def get_operational_summary(
        billing_period: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        plan_tier: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 5000,
    ) -> Dict[str, Any]:
        """
        Produce internal operational aggregate metrics across all tenants or bounded by filters.
        Separated strictly from merchant-facing endpoints.
        """
        records = supabase_service.get_ai_telemetry_records(
            user_id=user_id,
            billing_period=billing_period,
            plan_tier=plan_tier,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        aggs = compute_aggregates(records)

        return {
            "filters": {
                "billing_period": billing_period,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "plan_tier": plan_tier,
                "user_id": user_id,
            },
            "total_generations": aggs["total_generations"],
            "successful_generations": aggs["successful_generations"],
            "primary_success_count": aggs["primary_success_count"],
            "fallback_success_count": aggs["fallback_success_count"],
            "total_fallback_count": aggs["total_fallback_count"],
            "liquid_failed_count": aggs["liquid_failed_count"],
            "timeout_count": aggs["timeout_count"],
            "error_count": aggs["error_count"],
            "quota_consumed_count": aggs["quota_consumed_count"],
            "tokens": {
                "known_prompt_tokens": aggs["known_prompt_tokens"],
                "known_completion_tokens": aggs["known_completion_tokens"],
                "known_total_tokens": aggs["known_total_tokens"],
                "unreported_tokens_count": aggs["unreported_tokens_count"],
            },
            "cost": {
                "known_cost_micro_usd": aggs["known_cost_micro_usd"],
                "unreported_cost_count": aggs["unreported_cost_count"],
            },
            "latencies": {
                "avg_latency_ms": aggs["avg_latency_ms"],
                "avg_provider_latency_ms": aggs["avg_provider_latency_ms"],
                "p95_latency_ms": aggs["p95_latency_ms"],
            },
            "breakdowns": {
                "by_outcome": aggs["by_outcome"],
                "by_plan_tier": aggs["by_plan_tier"],
                "by_provider": aggs["by_provider"],
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def reconcile_quota(user_id: str, billing_period: str) -> Dict[str, Any]:
        """
        Diagnostic anomaly detection comparing:
        - Authoritative quota usage in public.ai_generation_usage
        - Observational quota_consumed=true rows in public.ai_generation_telemetry
        
        CRITICAL: Never mutates quota ledger or repairs state. Purely read-only.
        """
        clean_uid = str(user_id).strip()
        clean_period = str(billing_period).strip()

        # 1. Authoritative ledger usage
        ledger_usage = supabase_service.get_ai_monthly_usage(clean_uid, clean_period)

        # 2. Telemetry records for user and period
        records = supabase_service.get_ai_telemetry_records(user_id=clean_uid, billing_period=clean_period)
        telemetry_consumed = sum(1 for r in records if bool(r.get("quota_consumed", False)))

        # 3. Discrepancy calculation
        discrepancy = telemetry_consumed - ledger_usage
        is_anomaly = discrepancy != 0
        status = "balanced" if not is_anomaly else "anomaly_detected"

        return {
            "user_id": clean_uid,
            "billing_period": clean_period,
            "ledger_usage": ledger_usage,
            "telemetry_consumed": telemetry_consumed,
            "discrepancy": discrepancy,
            "status": status,
            "is_anomaly": is_anomaly,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def prune_expired_records(retention_days: int = 90) -> Dict[str, Any]:
        """
        Execute operational pruning of telemetry records older than retention_days.
        Default: 90 days approved retention for raw telemetry.
        """
        deleted_count = supabase_service.prune_expired_ai_telemetry(retention_days=retention_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        return {
            "retention_days": retention_days,
            "cutoff_timestamp": cutoff.isoformat(),
            "deleted_count": deleted_count,
        }


ai_telemetry_service = AITelemetryAggregationService()
