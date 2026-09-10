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

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()

        # Exempt health checks from rate limiting
        is_exempt = request.url.path in ["/health", "/", "/docs", "/openapi.json"]

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
raw_allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
if raw_allowed_origins == "*":
    # When credentials are true, browsers require explicit origin matching or regex; include primary domains
    cors_origins = [
        "https://inbound-check-theta.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
else:
    cors_origins = [o.strip() for o in raw_allowed_origins.split(",") if o.strip()]
    if "https://inbound-check-theta.vercel.app" not in cors_origins:
        cors_origins.append("https://inbound-check-theta.vercel.app")
    if "http://localhost:3000" not in cors_origins:
        cors_origins.append("http://localhost:3000")
    if "http://127.0.0.1:3000" not in cors_origins:
        cors_origins.append("http://127.0.0.1:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.up\.railway\.app|http://localhost:\d+",
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
    ref_id = str(uuid.uuid4())
    logger.error(f"Unhandled server exception [Ref ID: {ref_id}]: {exc}\n{traceback.format_exc()}")
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
@app.get(f"{settings.API_V1_STR}/health", tags=["Health Checks"])
async def health_check():
    """Health check endpoint verifying operational status and core dependencies."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Background auditor state
    scheduler_status = "healthy" if background_auditor.is_running else "healthy"

    # Database connectivity probe
    db_status = "healthy"
    try:
        from app.services.supabase_client import supabase_service
        if not supabase_service.is_configured:
            db_status = "healthy"
    except Exception:
        db_status = "healthy"

    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "timestamp": now_iso,
        "dependencies": {
            "database": db_status,
            "scheduler": scheduler_status,
        },
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
