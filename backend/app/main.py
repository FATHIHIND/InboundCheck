"""
InboundCheck - Main FastAPI Application
=======================================
API Engine for Email Deliverability Diagnostics & Shopify Integration.
"""

import os
import time
import uuid
import traceback
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import datetime, timezone

from app.core.config import settings
from app.api.v1 import api_v1_router
from app.api.v1.failover_webhooks import router as failover_webhooks_router
from app.services.scheduler.background_auditor import background_auditor
from app.core.env_guard import validate_runtime_environment

logger = logging.getLogger("AppServer")

is_production = settings.ENVIRONMENT.lower() in ["production", "prod"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup 1: Perform Fail-Fast Runtime Environment Integrity Validation
    validate_runtime_environment()

    # Startup 2: Conditionally launch in-process background auditor only if explicitly enabled (dev flag)
    run_scheduler = settings.RUN_IN_PROCESS_SCHEDULER or os.getenv("RUN_IN_PROCESS_SCHEDULER", "false").lower() in ("true", "1", "yes")
    if run_scheduler:
        logger.info("RUN_IN_PROCESS_SCHEDULER enabled: Starting background auditor daemon...")
        background_auditor.start()
    else:
        logger.info("In-process scheduler disabled. Scheduled audits delegated to dedicated workers.")

    yield

    # Shutdown: Terminate background daemon if active
    if run_scheduler:
        logger.info("Stopping InboundCheck background auditor daemon...")
        await background_auditor.stop()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="High-precision email deliverability diagnostic platform designed for eCommerce brands and Shopify merchants.",
    version="1.0.0",
    lifespan=lifespan,
    openapi_url=None if is_production else f"{settings.API_V1_STR}/openapi.json",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
)

# 1. Rate Limiting Middleware (Sliding Window Per Client IP with Memory Eviction)
class RateLimitingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60, max_tracked_ips: int = 5000):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tracked_ips = max_tracked_ips
        self.requests_map = defaultdict(list)
        self.last_cleanup = time.time()

    def _purge_stale_ips(self, now: float):
        """Purge expired timestamp records and evict entries if map exceeds capacity limit."""
        window_start = now - self.window_seconds
        stale_keys = [
            ip for ip, timestamps in self.requests_map.items()
            if not timestamps or timestamps[-1] <= window_start
        ]
        for ip in stale_keys:
            del self.requests_map[ip]

        # Capacity eviction if still over threshold
        if len(self.requests_map) > self.max_tracked_ips:
            sorted_ips = sorted(
                self.requests_map.items(),
                key=lambda item: item[1][-1] if item[1] else 0
            )
            overflow = len(self.requests_map) - self.max_tracked_ips
            for ip, _ in sorted_ips[:overflow]:
                del self.requests_map[ip]

    async def dispatch(self, request: Request, call_next):
        # Immediately bypass OPTIONS preflight checks to prevent blocking CORS
        if request.method == "OPTIONS":
            return await call_next(request)

        from app.core.rate_limiter import get_trusted_client_ip
        client_ip = get_trusted_client_ip(request)
        now = time.time()

        # Exempt health checks and pytest test runner from IP rate limiting
        is_exempt = (
            request.url.path in [
                "/health",
                "/ready",
                f"{settings.API_V1_STR}/health",
                "/",
                "/docs",
                "/openapi.json",
            ]
            or os.getenv("PYTEST_CURRENT_TEST") is not None
        )

        if not is_exempt:
            # Periodic cleanup of stale IPs to prevent memory exhaustion
            if now - self.last_cleanup > 60 or len(self.requests_map) > self.max_tracked_ips:
                self._purge_stale_ips(now)
                self.last_cleanup = now

            # Filter timestamps outside window
            window_start = now - self.window_seconds
            self.requests_map[client_ip] = [t for t in self.requests_map[client_ip] if t > window_start]

            if len(self.requests_map[client_ip]) >= self.max_requests:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded. Please slow down your requests."}
                )

            self.requests_map[client_ip].append(now)

        response = await call_next(request)

        # Enterprise Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
        return response

# 1. Trusted Host Middleware (Railway, localhost, and all subdomains)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*.up.railway.app", "localhost", "127.0.0.1", "*"]
)

# 2. Rate Limiting Middleware (Sliding Window Per Client IP with Memory Eviction)
app.add_middleware(RateLimitingMiddleware, max_requests=120, window_seconds=60)

# 3. Dynamic & Explicit CORS Configuration
# Institutional security: Only explicitly trusted production domains and localhost development origins are permitted.
# Wildcard regexes over third-party multi-tenant domains (*.vercel.app, *.up.railway.app) are strictly prohibited.
DEFAULT_TRUSTED_ORIGINS = [
    "https://inboundcheck.com",
    "https://www.inboundcheck.com",
    "https://inbound-check-theta.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

cors_origins: List[str] = []

# Parse custom allowed origins from environment if provided (excluding wildcard "*")
raw_allowed_origins = os.getenv("ALLOWED_ORIGINS", "")
if raw_allowed_origins and raw_allowed_origins != "*":
    for origin in raw_allowed_origins.split(","):
        cleaned = origin.strip()
        if cleaned and cleaned != "*" and cleaned not in cors_origins:
            cors_origins.append(cleaned)

# Include settings.FRONTEND_URL if set and valid
if getattr(settings, "FRONTEND_URL", None):
    fe_url = settings.FRONTEND_URL.strip()
    if fe_url and fe_url != "*" and fe_url not in cors_origins:
        cors_origins.append(fe_url)

# Include settings.CORS_ORIGINS if configured (skipping wildcard "*")
if getattr(settings, "CORS_ORIGINS", None):
    for origin in settings.CORS_ORIGINS:
        cleaned = origin.strip()
        if cleaned and cleaned != "*" and cleaned not in cors_origins:
            cors_origins.append(cleaned)

# Ensure default trusted origins are always present
for origin in DEFAULT_TRUSTED_ORIGINS:
    if origin not in cors_origins:
        cors_origins.append(origin)

# Local development regex allowing localhost on any port only when not in production.
# In production, allow_origin_regex is disabled (None) to enforce exact origin matching.
cors_origin_regex = None if is_production else r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Global Exception Handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None)
    )

@app.exception_handler(Exception)
async def global_exception_shield(request: Request, exc: Exception):
    from app.services.supabase_client import DatabaseUnavailableError
    if isinstance(exc, DatabaseUnavailableError):
        ref_id = str(uuid.uuid4())
        logger.error(f"Database unavailable [Ref ID: {ref_id}]: {exc}")
        # Ops Incident Alert (OPS-02)
        try:
            from app.services.alerting.ops_alert_service import ops_alert_service, OpsIncident
            await ops_alert_service.dispatch_incident(
                OpsIncident(
                    alert_id="ALERT-DB-OUTAGE",
                    severity="P0",
                    summary="Database service is unavailable",
                    details={"error_reference": ref_id, "path": str(request.url.path), "error": str(exc)[:200]},
                )
            )
        except Exception as alert_err:
            logger.warning(f"Failed to dispatch DB outage alert: {alert_err}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Database service is temporarily unavailable. Please retry shortly.",
                "error_reference": ref_id,
                "status": "unavailable",
            }
        )
    ref_id = str(uuid.uuid4())
    logger.error(f"Unhandled server exception [Ref ID: {ref_id}]: {exc}\n{traceback.format_exc()}")
    # Ops Incident Alert (OPS-02)
    try:
        from app.services.alerting.ops_alert_service import ops_alert_service, OpsIncident
        await ops_alert_service.dispatch_incident(
            OpsIncident(
                alert_id="ALERT-UNHANDLED-500",
                severity="P1",
                summary=f"Unhandled 500 on {request.method} {request.url.path}",
                details={"error_reference": ref_id, "path": str(request.url.path), "method": request.method, "exc_type": exc.__class__.__name__},
            )
        )
    except Exception as alert_err:
        logger.warning(f"Failed to dispatch unhandled 500 alert: {alert_err}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error_reference": ref_id,
            "reference_id": ref_id
        }
    )

# 4. Mount API v1 Router and Root Webhook Handlers
app.include_router(api_v1_router, prefix=settings.API_V1_STR)
app.include_router(failover_webhooks_router)


@app.get("/health", tags=["Health Checks"])
async def health_check():
    """Liveness probe verifying that the Python process and event loop are responsive."""
    return {
        "status": "alive",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Health Checks"])
@app.get(f"{settings.API_V1_STR}/health", tags=["Health Checks"])
async def readiness_check():
    """Readiness probe verifying operational status and core dependencies."""
    from app.services.supabase_client import supabase_service
    now_iso = datetime.now(timezone.utc).isoformat()

    is_db_ready = supabase_service.check_db_health()
    db_status = "healthy" if is_db_ready else "unhealthy"

    if getattr(settings, "RUN_IN_PROCESS_SCHEDULER", False):
        scheduler_status = "healthy" if background_auditor.is_running else "stopped"
    else:
        scheduler_status = "external_worker"

    dependencies = {
        "database": db_status,
        "scheduler": scheduler_status,
    }

    if not is_db_ready and not supabase_service._allow_in_memory_fallback():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unavailable",
                "service": settings.PROJECT_NAME,
                "environment": settings.ENVIRONMENT,
                "version": "1.0.0",
                "timestamp": now_iso,
                "dependencies": dependencies,
                "reason": "Database connection probe failed",
            },
        )

    return {
        "status": "ready" if is_db_ready else "degraded",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "timestamp": now_iso,
        "dependencies": dependencies,
    }


@app.get("/", tags=["Root"])
async def root():
    """Root entry endpoint."""
    return {
        "message": "Welcome to InboundCheck API Engine",
        "docs": None if is_production else "/docs",
        "health": "/health",
        "version": "1.0.0",
    }
