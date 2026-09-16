"""
InboundCheck - Automated Seed Inbox Testing REST Router (v1)
============================================================
Endpoints for generating unique tracking tokens and verifying real-world
folder placement across Gmail, Yahoo, and Outlook.
"""

from fastapi import APIRouter, Depends, HTTPException, status
import logging

from app.core.security import get_current_user_id
from app.schemas.seed_testing import (
    GenerateSeedRequest,
    GenerateSeedResponse,
    VerifySeedRequest,
    SeedPlacementResult,
)
from app.services.seed_testing.seed_verifier import seed_verifier

logger = logging.getLogger("SeedTestingRouter")

router = APIRouter(prefix="/seed-testing", tags=["Automated Seed Inbox Testing"])


@router.post("/generate", response_model=GenerateSeedResponse)
async def generate_seed_session(
    request: GenerateSeedRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Generate a new seed testing address and unique tracking token for merchant transactional receipts.
    """
    try:
        clean_domain = request.store_domain.strip().lower()
        if not clean_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Store domain must not be empty"
            )

        return seed_verifier.create_seed_session(
            store_domain=clean_domain,
            provider=request.provider or "seed"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate seed testing session for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate seed session"
        )


@router.post("/verify", response_model=SeedPlacementResult)
async def verify_seed_placement(
    request: VerifySeedRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Evaluate seed inbox placement across Gmail, Yahoo, and Outlook with strict 10s per-provider timeout.
    """
    try:
        clean_token = request.tracking_token.strip()
        clean_domain = request.store_domain.strip().lower()

        if not clean_token or not clean_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tracking token and store domain are required"
            )

        return await seed_verifier.verify_seed_placement(
            token=clean_token,
            store_domain=clean_domain,
            timeout_seconds=request.timeout_seconds
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify seed placement for token {request.tracking_token}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to evaluate seed inbox placement"
        )
