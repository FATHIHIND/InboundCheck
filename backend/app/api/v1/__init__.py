"""
InboundCheck - API v1 Router Aggregator
"""

from fastapi import APIRouter
from app.api.v1.dns import router as dns_router
from app.api.v1.shopify import router as shopify_router
from app.api.v1.domains import router as domains_router
from app.api.v1.settings import router as settings_router
from app.api.v1.billing import router as billing_router
from app.api.v1.ai import router as ai_router
from app.api.v1.failover import router as failover_router
from app.api.v1.auto_fix import router as auto_fix_router
from app.api.v1.analytics import router as analytics_router

api_v1_router = APIRouter()
api_v1_router.include_router(dns_router)
api_v1_router.include_router(shopify_router)
api_v1_router.include_router(domains_router)
api_v1_router.include_router(settings_router)
api_v1_router.include_router(billing_router)
api_v1_router.include_router(ai_router)
api_v1_router.include_router(failover_router)
api_v1_router.include_router(auto_fix_router)
api_v1_router.include_router(analytics_router)
