"""
InboundCheck - AI Content Intelligence REST Router (v1)
======================================================
Endpoints for template spam risk diagnostics and polymorphic copy generation.
"""

from fastapi import APIRouter, HTTPException, Query, status, Depends, Header
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Dict, Any, List
import asyncio
import uuid
import time
from datetime import datetime, timezone
import logging
import secrets

from app.core.config import settings
from app.core.security import get_current_user_id
from app.core.rate_limiter import rate_limit_ai_tier
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.ai.content_optimizer import ai_content_service, DEFAULT_SAMPLE_TEMPLATES
from app.services.ai.plan_policy import AIPlanPolicy, get_current_ai_policy
from app.services.ai.pricing import resolve_cost
from app.services.ai.provider import GenerationResult
from app.services.ai.telemetry_service import ai_telemetry_service
from app.services.alerting.ops_alert_service import ops_alert_service, OpsIncident

logger = logging.getLogger("AIRoutes")

router = APIRouter(prefix="/ai", tags=["AI Content Lab"])


class TemplateAnalyzeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    subject: str = Field(..., min_length=1, max_length=255, description="Email subject line")
    body_content: Optional[str] = Field(None, max_length=15000, description="Email body text or HTML template")
    body: Optional[str] = Field(None, max_length=15000, description="Alternative key for email body text or HTML template")
    template_name: Optional[str] = Field("Shopify Order Template", max_length=100)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Subject must not be empty or whitespace only")
        return v

    @model_validator(mode="after")
    def validate_content_presence(self) -> "TemplateAnalyzeRequest":
        content = self.get_content()
        if not content:
            raise ValueError("Email body content must not be empty or whitespace only")
        return self

    def get_content(self) -> str:
        return (self.body_content or self.body or "").strip()


class PolymorphicGenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    subject: str = Field(..., min_length=1, max_length=255, description="Original subject line")
    body_content: Optional[str] = Field(None, max_length=15000, description="Original HTML/text content")
    body: Optional[str] = Field(None, max_length=15000, description="Alternative key for original HTML/text content")

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Subject must not be empty or whitespace only")
        return v

    @model_validator(mode="after")
    def validate_content_presence(self) -> "PolymorphicGenerateRequest":
        content = self.get_content()
        if not content:
            raise ValueError("Email body content must not be empty or whitespace only")
        return self

    def get_content(self) -> str:
        return (self.body_content or self.body or "").strip()


@router.get("/sample-templates")
async def get_sample_templates(user_id: str = Depends(get_current_user_id)):
    """
    Return preset Shopify transactional templates for instant testing.
    """
    return {"success": True, "templates": DEFAULT_SAMPLE_TEMPLATES}


def verify_internal_access(
    x_service_role_key: Optional[str] = Header(None, alias="X-Service-Role-Key"),
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
) -> bool:
    """Validate internal operational API key for administrative endpoints using constant-time comparison."""
    candidate = (x_internal_key or x_service_role_key or "").strip()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal operational access requires valid service credentials.",
        )

    # Dedicated operational admin key
    allowed_keys: List[str] = []
    ops_key = (getattr(settings, "OPS_INTERNAL_API_KEY", "") or "").strip()
    if ops_key and "placeholder" not in ops_key.lower():
        allowed_keys.append(ops_key)

    # Non-production test compatibility bypass
    env = (getattr(settings, "ENVIRONMENT", "development") or "development").lower()
    if env in ["development", "test", "local"]:
        allowed_keys.append("test-internal-key")

    if not allowed_keys:
        # Production fail-closed: No valid internal key configured
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Internal operational access is unconfigured.",
        )

    # Constant-time comparison across allowed keys
    is_authorized = False
    for key in allowed_keys:
        if secrets.compare_digest(candidate, key):
            is_authorized = True

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid internal operational credentials.",
        )
    return True


@router.get("/usage")
@router.get("/telemetry/summary")
async def get_ai_merchant_usage(
    billing_period: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    user_id: str = Depends(get_current_user_id),
    ai_policy: AIPlanPolicy = Depends(get_current_ai_policy),
):
    """
    Retrieve merchant-facing monthly AI generation quota and operational summary.
    Strictly isolated to authenticated user_id; zero cross-tenant exposure.
    Zero prompt, body, Liquid, or provider secret exposure.
    """
    summary = await asyncio.to_thread(
        ai_telemetry_service.get_merchant_usage_summary,
        user_id=user_id,
        billing_period=billing_period,
        ai_policy=ai_policy,
    )
    return {
        "success": True,
        **summary,
    }


@router.get("/admin/telemetry-summary")
async def get_ai_operational_telemetry_summary(
    billing_period: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    plan_tier: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None, alias="user_id"),
    limit: int = Query(5000, ge=1, le=10000),
    _authorized: bool = Depends(verify_internal_access),
):
    """
    Internal operational reporting endpoint across tenants or filtered by tier/period.
    Requires internal service key authentication.
    """
    summary = await asyncio.to_thread(
        ai_telemetry_service.get_operational_summary,
        billing_period=billing_period,
        plan_tier=plan_tier,
        user_id=tenant_id,
        limit=limit,
    )
    return {
        "success": True,
        "operational_telemetry": summary,
    }


@router.get("/admin/reconcile-quota")
async def reconcile_ai_quota(
    user_id: str = Query(..., min_length=1),
    billing_period: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    _authorized: bool = Depends(verify_internal_access),
):
    """
    Diagnostic anomaly detection comparing authoritative quota ledger vs telemetry records.
    Strictly read-only; never mutates quota or auto-repairs state.
    """
    report = await asyncio.to_thread(
        ai_telemetry_service.reconcile_quota,
        user_id=user_id,
        billing_period=billing_period,
    )
    return {
        "success": True,
        "reconciliation": report,
    }


@router.post("/admin/prune-telemetry")
async def prune_ai_telemetry(
    retention_days: int = Query(90, ge=1, le=365),
    _authorized: bool = Depends(verify_internal_access),
):
    """
    Operational maintenance pruning for telemetry older than approved retention period (90 days).
    """
    res = await asyncio.to_thread(
        ai_telemetry_service.prune_expired_records,
        retention_days=retention_days,
    )
    return {
        "success": True,
        "pruned": res,
    }


@router.post("/analyze-template")
@router.post("/audit-template")
async def analyze_email_template(
    payload: TemplateAnalyzeRequest,
    user_id: str = Depends(rate_limit_ai_tier)
):
    """
    Audit template content for spam trigger density, formatting anomalies, and risk score.
    """
    try:
        content = payload.get_content()
        result = await ai_content_service.analyze_template(
            subject=payload.subject,
            body_content=content
        )
        return {
            "success": True,
            "template_name": payload.template_name,
            "audit": result,
            "spam_score": result.get("spam_score", 0),
            "risk_level": result.get("risk_level", "low"),
            "flagged_triggers": result.get("flagged_triggers", []),
            "recommendations": result.get("recommendations", [])
        }
    except Exception as e:
        logger.error(f"Error analyzing template: {e}")
        raise HTTPException(status_code=500, detail="Failed to analyze email template deliverability")


async def _safe_rollback_monthly_quota(user_id: str, billing_period: str) -> None:
    """Best-effort compensation rollback for reserved AI generation credits."""
    try:
        await asyncio.to_thread(
            supabase_service.rollback_ai_monthly_generation,
            user_id=user_id,
            billing_period=billing_period,
        )
    except Exception as rollback_err:
        logger.error(f"Failed to rollback monthly AI quota for user {user_id}: {rollback_err}")


async def _safe_release_concurrency_slot(user_id: str, lease_id: str) -> None:
    """Best-effort graceful release for reserved distributed AI concurrency lease."""
    try:
        await asyncio.to_thread(
            supabase_service.release_ai_concurrency_slot,
            user_id=user_id,
            lease_id=lease_id,
        )
    except Exception as release_err:
        logger.warning(f"Failed to release AI concurrency slot {lease_id} for user {user_id}: {release_err}")


@router.post("/generate-polymorphic-variants")
@router.post("/generate-variants")
async def generate_polymorphic_variants(
    payload: PolymorphicGenerateRequest,
    user_id: str = Depends(rate_limit_ai_tier),
    ai_policy: AIPlanPolicy = Depends(get_current_ai_policy),
):
    """
    Generate 3 deliverability-optimized polymorphic variations of the email copy.
    Authoritative AI plan policy is resolved per authenticated user and enforces
    RPM burst limit, monthly generation quota, and distributed concurrency slots.
    """
    # 1. Acquire distributed AI concurrency slot (Step 17C / 17C.1: 60s TTL)
    # Step 17D.3: Unified generation_id for the complete request lifecycle
    generation_id = str(uuid.uuid4())
    lease_id = generation_id
    t_lifecycle_start = time.perf_counter()
    telemetry_recorded = False

    try:
        lease_res = await asyncio.to_thread(
            supabase_service.acquire_ai_concurrency_slot,
            user_id=user_id,
            concurrency_limit=ai_policy.concurrency_limit,
            lease_id=lease_id,
            ttl_seconds=60,
        )
    except DatabaseUnavailableError as db_err:
        logger.error(f"Concurrency verification failed due to database unavailability: {db_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "AI_CONCURRENCY_SERVICE_UNAVAILABLE",
                "message": "AI generation service temporarily unavailable due to concurrency verification failure. Please retry shortly.",
            },
        )
    except Exception as e:
        logger.error(f"Unexpected error verifying AI concurrency: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "AI_CONCURRENCY_SERVICE_UNAVAILABLE",
                "message": "AI generation service temporarily unavailable due to concurrency verification failure.",
            },
        )

    if not lease_res.get("allowed", False):
        current_active = lease_res.get("current_active", ai_policy.concurrency_limit)
        limit = lease_res.get("concurrency_limit", ai_policy.concurrency_limit)
        logger.info(
            f"Concurrent AI generation limit exceeded for user {user_id} on tier '{ai_policy.tier}': {current_active}/{limit}"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "AI_CONCURRENCY_LIMIT_EXCEEDED",
                "message": (
                    f"Concurrent AI generation limit reached for {ai_policy.tier} tier "
                    f"({current_active}/{limit} in-flight runs). Please wait for your "
                    "in-flight generation to complete before starting another."
                ),
                "current_active": current_active,
                "concurrency_limit": limit,
                "tier": ai_policy.tier,
            },
            headers={"Retry-After": "5"},
        )

    # 2. Execute generation with guaranteed concurrency lease release in finally block
    try:
        # 2.1 Deterministic calendar month billing period identifier (UTC 'YYYY-MM')
        billing_period = datetime.now(timezone.utc).strftime("%Y-%m")

        ALLOWED_TELEMETRY_KEYS = {
            "generation_id",
            "user_id",
            "plan_tier",
            "billing_period",
            "provider",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost_micro_usd",
            "cost_status",
            "latency_ms",
            "provider_latency_ms",
            "outcome",
            "fallback_used",
            "quota_consumed",
            "created_at",
        }

        async def _record_telemetry_once(
            *,
            provider: str,
            model: str,
            outcome: str,
            fallback_used: bool,
            quota_consumed: bool,
            latency_ms: int,
            provider_latency_ms: Optional[int] = None,
            prompt_tokens: Optional[int] = None,
            completion_tokens: Optional[int] = None,
            total_tokens: Optional[int] = None,
            cost_micro_usd: Optional[int] = None,
            cost_status: str = "unreported",
        ) -> None:
            nonlocal telemetry_recorded
            if telemetry_recorded:
                return
            telemetry_recorded = True

            # Strict data minimization: only schema-whitelisted attributes, never prompts, bodies, Liquid, or PII
            raw_payload = {
                "generation_id": generation_id,
                "user_id": user_id,
                "plan_tier": ai_policy.tier,
                "billing_period": billing_period,
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_micro_usd": cost_micro_usd,
                "cost_status": cost_status,
                "latency_ms": max(0, latency_ms),
                "provider_latency_ms": provider_latency_ms if (provider_latency_ms is not None and provider_latency_ms >= 0) else None,
                "outcome": outcome,
                "fallback_used": bool(fallback_used),
                "quota_consumed": bool(quota_consumed),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            payload_to_write = {k: v for k, v in raw_payload.items() if k in ALLOWED_TELEMETRY_KEYS}

            try:
                write_success = await asyncio.to_thread(supabase_service.record_ai_telemetry, payload_to_write)
                if not write_success:
                    logger.warning(
                        f"AI generation telemetry write failed for generation {generation_id}. Operational record skipped."
                    )
                    try:
                        await ops_alert_service.dispatch_incident(
                            OpsIncident(
                                alert_id="ALERT-AI-TELEMETRY-WRITE-FAILURE",
                                severity="P2",
                                summary="Best-effort AI generation telemetry write failed",
                                details={
                                    "generation_id": generation_id,
                                    "user_id": user_id,
                                    "plan_tier": ai_policy.tier,
                                    "outcome": outcome,
                                },
                            )
                        )
                    except Exception as alert_err:
                        logger.debug(f"OpsAlert dispatch suppressed: {alert_err}")
            except Exception as e:
                logger.warning(
                    f"AI generation telemetry exception for generation {generation_id}: {e}. Operational record skipped."
                )
                try:
                    await ops_alert_service.dispatch_incident(
                        OpsIncident(
                            alert_id="ALERT-AI-TELEMETRY-WRITE-FAILURE",
                            severity="P2",
                            summary="Best-effort AI generation telemetry write exception",
                            details={
                                "generation_id": generation_id,
                                "user_id": user_id,
                                "plan_tier": ai_policy.tier,
                                "outcome": outcome,
                            },
                        )
                    )
                except Exception as alert_err:
                    logger.debug(f"OpsAlert dispatch suppressed: {alert_err}")

        # 2.2 Atomic monthly quota reservation under row lock
        try:
            quota_res = await asyncio.to_thread(
                supabase_service.consume_ai_monthly_generation,
                user_id=user_id,
                billing_period=billing_period,
                monthly_limit=ai_policy.monthly_generation_limit,
            )
        except DatabaseUnavailableError as db_err:
            logger.error(f"Quota verification failed due to database unavailability: {db_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI generation service temporarily unavailable due to quota verification failure. Please retry shortly.",
            )
        except Exception as e:
            logger.error(f"Unexpected error verifying AI monthly quota: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI generation service temporarily unavailable due to quota verification failure.",
            )

        # 2.3 Quota Exceeded Enforcement
        if not quota_res.get("allowed", False):
            current_usage = quota_res.get("current_usage", ai_policy.monthly_generation_limit)
            limit = quota_res.get("limit", ai_policy.monthly_generation_limit)
            logger.info(
                f"Monthly AI generation quota exceeded for user {user_id} on tier '{ai_policy.tier}': {current_usage}/{limit}"
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error_code": "AI_MONTHLY_QUOTA_EXCEEDED",
                    "message": (
                        f"Monthly AI generation quota exceeded for {ai_policy.tier} tier "
                        f"({current_usage}/{limit} runs used). Upgrade your plan to continue "
                        "generating email optimizations."
                    ),
                    "current_usage": current_usage,
                    "monthly_limit": limit,
                    "remaining": 0,
                    "tier": ai_policy.tier,
                },
            )

        # 2.4 Generate polymorphic variants with 25.0s wall-clock timeout and compensation rollback on failure
        content = payload.get_content()
        success = False
        default_provider_name = getattr(ai_content_service.provider, "provider_name", "agent_router")
        cfg = getattr(ai_content_service.provider, "config", None)
        default_model_name = getattr(cfg, "model_name", "google/gemma-4-26b-a4b-it") if cfg else "google/gemma-4-26b-a4b-it"

        try:
            async with asyncio.timeout(25.0):
                gen_res: GenerationResult = await ai_content_service.generate_polymorphic_variants_result(
                    subject=payload.subject,
                    body_content=content,
                    ai_policy=ai_policy,
                )
                variants = gen_res.variants
                fallback_used = (gen_res.provider == "heuristic_fallback")
                provider_latency_ms = gen_res.provider_latency_ms

                cost_micro_usd, cost_status = resolve_cost(
                    model=gen_res.model,
                    prompt_tokens=gen_res.prompt_tokens,
                    completion_tokens=gen_res.completion_tokens,
                    provider=gen_res.provider,
                )
                latency_ms = max(0, int((time.perf_counter() - t_lifecycle_start) * 1000))

                if variants and len(variants) > 0:
                    success = True
                    outcome = "success_via_fallback" if fallback_used else "success"
                    await _record_telemetry_once(
                        provider=gen_res.provider,
                        model=gen_res.model,
                        outcome=outcome,
                        fallback_used=fallback_used,
                        quota_consumed=True,
                        latency_ms=latency_ms,
                        provider_latency_ms=provider_latency_ms,
                        prompt_tokens=gen_res.prompt_tokens,
                        completion_tokens=gen_res.completion_tokens,
                        total_tokens=gen_res.total_tokens,
                        cost_micro_usd=cost_micro_usd,
                        cost_status=cost_status,
                    )
                    return {
                        "success": True,
                        "variants": variants,
                    }
                else:
                    # Liquid preservation safety rejection or empty candidate set: refund reserved quota
                    logger.warning(
                        f"No valid variants generated for user {user_id}; rolling back reserved monthly quota credit."
                    )
                    await _record_telemetry_once(
                        provider=gen_res.provider,
                        model=gen_res.model,
                        outcome="liquid_failed",
                        fallback_used=fallback_used,
                        quota_consumed=False,
                        latency_ms=latency_ms,
                        provider_latency_ms=provider_latency_ms,
                        prompt_tokens=gen_res.prompt_tokens,
                        completion_tokens=gen_res.completion_tokens,
                        total_tokens=gen_res.total_tokens,
                        cost_micro_usd=cost_micro_usd,
                        cost_status=cost_status,
                    )
                    await _safe_rollback_monthly_quota(user_id, billing_period)
                    return {
                        "success": True,
                        "variants": [],
                    }
        except TimeoutError:
            logger.error(
                f"AI generation wall-clock timeout (25.0s) exceeded for user {user_id}; cancelling and rolling back quota."
            )
            latency_ms = max(0, int((time.perf_counter() - t_lifecycle_start) * 1000))
            await _record_telemetry_once(
                provider=default_provider_name,
                model=default_model_name,
                outcome="timeout",
                fallback_used=False,
                quota_consumed=False,
                latency_ms=latency_ms,
                provider_latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                cost_micro_usd=None,
                cost_status="unreported",
            )
            if not success:
                await _safe_rollback_monthly_quota(user_id, billing_period)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={
                    "error_code": "AI_GENERATION_TIMEOUT",
                    "message": "AI email optimization exceeded wall-clock timeout limit of 25 seconds. Please retry.",
                },
            )
        except asyncio.CancelledError:
            logger.warning(
                f"AI generation task cancelled for user {user_id}; rolling back reserved quota credit."
            )
            latency_ms = max(0, int((time.perf_counter() - t_lifecycle_start) * 1000))
            await _record_telemetry_once(
                provider=default_provider_name,
                model=default_model_name,
                outcome="error",
                fallback_used=False,
                quota_consumed=False,
                latency_ms=latency_ms,
                provider_latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                cost_micro_usd=None,
                cost_status="unreported",
            )
            if not success:
                await _safe_rollback_monthly_quota(user_id, billing_period)
            raise
        except HTTPException:
            if not success:
                await _safe_rollback_monthly_quota(user_id, billing_period)
            raise
        except Exception as e:
            logger.error(f"Error generating polymorphic variants: {e}")
            latency_ms = max(0, int((time.perf_counter() - t_lifecycle_start) * 1000))
            await _record_telemetry_once(
                provider=default_provider_name,
                model=default_model_name,
                outcome="error",
                fallback_used=True,  # Primary and fallback failed
                quota_consumed=False,
                latency_ms=latency_ms,
                provider_latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                cost_micro_usd=None,
                cost_status="unreported",
            )
            if not success:
                await _safe_rollback_monthly_quota(user_id, billing_period)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate deliverability-optimized variants"
            )
    finally:
        # Step 17C / 17C.1: Concurrency slot is ALWAYS released across all exit branches
        await _safe_release_concurrency_slot(user_id, lease_id)

