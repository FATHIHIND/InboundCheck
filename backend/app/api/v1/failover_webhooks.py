"""
InboundCheck - Secure ESP Delivery-Failure Webhook Ingestion API (Phase 4 Step 4)
=================================================================================
Ingests raw delivery failure webhooks from major ESP providers (Postmark, SendGrid,
Mailgun, Amazon SES, Klaviyo) with cryptographic HMAC verification, 1 MB payload limits,
replay protection, PII hashing, and asynchronous event queuing.
"""

from typing import Literal, Dict, Any, List
import logging
from fastapi import APIRouter, Request, status, HTTPException
from starlette.responses import JSONResponse

from app.services.failover.esp_webhook_service import (
    read_body_with_limit,
    esp_webhook_verifier,
)
from app.services.failover.event_normalizers import (
    normalize_provider_events,
    NormalizedDeliveryFailure,
)
from app.services.supabase_client import supabase_service

logger = logging.getLogger("FailoverWebhooks")

router = APIRouter(tags=["Delivery Failure Webhooks"])


class FailureEventRepository:
    """Repository handling idempotent insertion of normalized delivery failures."""

    @staticmethod
    async def insert_if_absent(event: NormalizedDeliveryFailure) -> Dict[str, Any]:
        """
        Durable insertion into delivery_failure_events with deduplication on (esp_provider, provider_event_id).
        Correlates user_id from transactional_message_registry when provider_message_id is known.
        """
        user_id = None
        if event.provider_message_id:
            msg = supabase_service.get_transactional_message(event.provider, event.provider_message_id)
            if msg and msg.get("user_id"):
                user_id = msg.get("user_id")

        return supabase_service.record_delivery_failure_event(
            esp_provider=event.provider,
            provider_event_id=event.provider_event_id,
            provider_message_id=event.provider_message_id,
            event_type=event.event_type,
            event_timestamp=event.occurred_at.isoformat(),
            signature_verified=True,
            event_payload=event.event_payload,
            user_id=user_id,
            processing_status="received",
        )


failure_event_repository = FailureEventRepository()


@router.post("/webhook/delivery-failure/{provider}", status_code=status.HTTP_200_OK)
async def ingest_delivery_failure(
    provider: Literal["postmark", "sendgrid", "mailgun", "ses", "klaviyo"],
    request: Request,
):
    """
    Ingest delivery-failure webhook events from ESP providers.
    - No Bearer JWT required: authenticity is validated via provider HMAC / cryptographic signatures.
    - 1 MB maximum payload ceiling enforced.
    - Clock skew tolerance (max 300s) to prevent replay attacks.
    - Deduplicates on (esp_provider, provider_event_id).
    - Asynchronous processing: customer fallbacks are NOT dispatched synchronously from this request.
    """
    # 1. Enforce 1 MB payload limit
    raw_body = await read_body_with_limit(request, max_bytes=1_048_576)

    # 2. Cryptographic signature and clock skew verification
    verifier = esp_webhook_verifier.for_provider(provider)
    await verifier.verify(
        raw_body=raw_body,
        headers=request.headers,
        max_clock_skew_seconds=300,
    )

    # 3. Normalize provider-specific schema into NormalizedDeliveryFailure models
    events = normalize_provider_events(provider, raw_body)

    if not events:
        logger.info(f"Webhook received from {provider} with no failure events (e.g. non-failure event type).")
        return {"accepted": True, "processed_events": 0}

    # 4. Durable insertion with deduplication
    for event in events:
        await failure_event_repository.insert_if_absent(event)

    logger.info(f"Successfully ingested {len(events)} delivery failure event(s) from {provider}.")
    return {"accepted": True, "processed_events": len(events)}
