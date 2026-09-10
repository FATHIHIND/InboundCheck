"""
InboundCheck - ESP Webhook Event Normalizers (Phase 4 Step 4)
==============================================================
Provides high-precision normalization, PII sanitization, and failover-eligibility
guardrails across major ESP delivery failure webhooks (Postmark, SendGrid, Mailgun, SES, Klaviyo).
"""

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

logger = logging.getLogger("ESPEventNormalizers")

# Critical eligibility filters: only permanent, mission-critical transactional delivery failures
# are eligible to trigger an incident alert (Telegram).
FAILOVER_ELIGIBLE_EVENTS = {"bounce", "dropped", "rejected"}

FAILOVER_ELIGIBLE_MESSAGE_TYPES = {
    "order_confirmation",
    "shipping_update",
    "delivery_update",
}


def hash_email(email: Optional[str]) -> Optional[str]:
    """Calculate deterministic SHA-256 hash of email for zero-PII correlation."""
    if not email:
        return None
    clean = email.strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


class NormalizedDeliveryFailure(BaseModel):
    provider: str
    provider_event_id: str
    provider_message_id: Optional[str] = None
    event_type: Literal["bounce", "dropped", "rejected", "deferred", "complaint"]
    reason_code: Optional[str] = None
    occurred_at: datetime
    recipient_email_hash: Optional[str] = None
    event_payload: Dict[str, Any] = Field(default_factory=dict)

    def is_failover_eligible(self, message_type: Optional[str] = None) -> bool:
        """
        Complaints, unsubscribes, marketing events, soft bounces, and ambiguous events
        must never trigger customer fallback.
        """
        if self.event_type not in FAILOVER_ELIGIBLE_EVENTS:
            return False
        if message_type is not None and message_type not in FAILOVER_ELIGIBLE_MESSAGE_TYPES:
            return False
        return True


def _parse_timestamp(val: Any) -> datetime:
    """Parse various timestamp representations (unix epoch integer/float or ISO string) to UTC datetime."""
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        try:
            # Handle ISO string with trailing Z or timezone offset
            clean_str = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _normalize_postmark(data: Any) -> List[NormalizedDeliveryFailure]:
    """Normalize Postmark bounce and delivery failure webhook payloads."""
    items = data if isinstance(data, list) else [data]
    events: List[NormalizedDeliveryFailure] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_type = str(item.get("Type", "")).strip().lower()
        record_type = str(item.get("RecordType", "")).strip().lower()

        # Map Postmark bounce types
        if raw_type in ("hardbounce", "bademailaddress"):
            event_type = "bounce"
        elif raw_type in ("transient", "softbounce", "dnserror"):
            event_type = "deferred"
        elif "spam" in raw_type or "complaint" in raw_type or record_type == "complaint":
            event_type = "complaint"
        elif raw_type in ("blocked", "inactivated"):
            event_type = "dropped"
        else:
            event_type = "bounce" if "bounce" in record_type else "dropped"

        provider_event_id = str(item.get("ID") or item.get("MessageID") or "")
        provider_message_id = str(item.get("MessageID") or "") or None
        occurred_at = _parse_timestamp(item.get("BouncedAt") or item.get("DeliveredAt"))
        recipient_email = item.get("Email")
        details = item.get("Details") or item.get("Description") or item.get("Type")

        cleaned_payload = {
            "type": item.get("Type"),
            "type_code": item.get("TypeCode"),
            "name": item.get("Name"),
            "details": details,
            "server_id": item.get("ServerID"),
        }

        events.append(
            NormalizedDeliveryFailure(
                provider="postmark",
                provider_event_id=provider_event_id,
                provider_message_id=provider_message_id,
                event_type=event_type,
                reason_code=str(item.get("TypeCode") or raw_type),
                occurred_at=occurred_at,
                recipient_email_hash=hash_email(recipient_email),
                event_payload=cleaned_payload,
            )
        )

    return events


def _normalize_sendgrid(data: Any) -> List[NormalizedDeliveryFailure]:
    """Normalize SendGrid Event Webhook batch payloads."""
    items = data if isinstance(data, list) else [data]
    events: List[NormalizedDeliveryFailure] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_event = str(item.get("event", "")).strip().lower()

        if raw_event == "bounce":
            event_type = "bounce"
        elif raw_event == "dropped":
            event_type = "dropped"
        elif raw_event == "deferred":
            event_type = "deferred"
        elif raw_event in ("spamreport", "unsubscribe", "group_unsubscribe"):
            event_type = "complaint"
        else:
            # Non-failure events (e.g. delivered, processed, open, click)
            continue

        provider_event_id = str(item.get("sg_event_id") or f"{item.get('sg_message_id')}_{item.get('timestamp')}")
        # Strip trailing SendGrid internal suffix (e.g., .filter0001...)
        raw_msg_id = item.get("sg_message_id")
        provider_message_id = str(raw_msg_id).split(".")[0] if raw_msg_id else None

        occurred_at = _parse_timestamp(item.get("timestamp"))
        recipient_email = item.get("email")

        cleaned_payload = {
            "event": raw_event,
            "type": item.get("type"),
            "reason": item.get("reason"),
            "status": item.get("status"),
        }

        events.append(
            NormalizedDeliveryFailure(
                provider="sendgrid",
                provider_event_id=provider_event_id,
                provider_message_id=provider_message_id,
                event_type=event_type,
                reason_code=str(item.get("status") or item.get("type") or raw_event),
                occurred_at=occurred_at,
                recipient_email_hash=hash_email(recipient_email),
                event_payload=cleaned_payload,
            )
        )

    return events


def _normalize_mailgun(data: Any) -> List[NormalizedDeliveryFailure]:
    """Normalize Mailgun Webhook event payload."""
    event_data = data.get("event-data", {}) if isinstance(data, dict) else {}
    if not event_data:
        return []

    raw_event = str(event_data.get("event", "")).strip().lower()
    severity = str(event_data.get("severity", "")).strip().lower()

    if raw_event == "failed":
        if severity == "permanent":
            event_type = "bounce"
        elif severity == "temporary":
            event_type = "deferred"
        else:
            event_type = "rejected"
    elif raw_event == "rejected":
        event_type = "rejected"
    elif raw_event == "complained":
        event_type = "complaint"
    else:
        return []

    provider_event_id = str(event_data.get("id") or "")
    # Mailgun headers message-id
    headers = event_data.get("message", {}).get("headers", {})
    provider_message_id = headers.get("message-id")
    if provider_message_id:
        # Strip wrapping angle brackets if present (<id@mail.domain.com>)
        provider_message_id = provider_message_id.strip("<>")

    occurred_at = _parse_timestamp(event_data.get("timestamp"))
    recipient_email = event_data.get("recipient")

    delivery_status = event_data.get("delivery-status", {})
    reason_code = str(delivery_status.get("code") or event_data.get("reason") or raw_event)

    cleaned_payload = {
        "event": raw_event,
        "severity": severity,
        "reason": event_data.get("reason"),
        "delivery_status_code": delivery_status.get("code"),
        "delivery_status_message": delivery_status.get("message"),
        "delivery_status_description": delivery_status.get("description"),
    }

    return [
        NormalizedDeliveryFailure(
            provider="mailgun",
            provider_event_id=provider_event_id,
            provider_message_id=provider_message_id,
            event_type=event_type,
            reason_code=reason_code,
            occurred_at=occurred_at,
            recipient_email_hash=hash_email(recipient_email),
            event_payload=cleaned_payload,
        )
    ]


def _normalize_ses(data: Any) -> List[NormalizedDeliveryFailure]:
    """Normalize Amazon SES notification (direct or wrapped in SNS)."""
    payload = data
    # Unwrap SNS wrapper if present
    if isinstance(data, dict) and data.get("Type") == "Notification" and "Message" in data:
        try:
            payload = json.loads(data["Message"])
        except Exception:
            payload = data

    if not isinstance(payload, dict):
        return []

    notification_type = str(payload.get("notificationType", "")).strip().lower()
    mail = payload.get("mail", {})
    provider_message_id = mail.get("messageId")

    events: List[NormalizedDeliveryFailure] = []

    if notification_type == "bounce":
        bounce = payload.get("bounce", {})
        bounce_type = str(bounce.get("bounceType", "")).strip().lower()
        bounce_sub_type = str(bounce.get("bounceSubType", ""))
        feedback_id = bounce.get("feedbackId") or f"{provider_message_id}_bounce"
        occurred_at = _parse_timestamp(bounce.get("timestamp") or mail.get("timestamp"))

        event_type = "bounce" if bounce_type == "permanent" else "deferred"

        recipients = bounce.get("bouncedRecipients", [])
        if recipients:
            for idx, r in enumerate(recipients):
                r_email = r.get("emailAddress")
                r_status = r.get("status")
                r_diag = r.get("diagnosticCode")
                evt_id = f"{feedback_id}_{idx}" if len(recipients) > 1 else feedback_id

                events.append(
                    NormalizedDeliveryFailure(
                        provider="ses",
                        provider_event_id=evt_id,
                        provider_message_id=provider_message_id,
                        event_type=event_type,
                        reason_code=r_status or bounce_sub_type,
                        occurred_at=occurred_at,
                        recipient_email_hash=hash_email(r_email),
                        event_payload={
                            "bounce_type": bounce_type,
                            "bounce_sub_type": bounce_sub_type,
                            "diagnostic_code": r_diag,
                            "status": r_status,
                        },
                    )
                )
        else:
            events.append(
                NormalizedDeliveryFailure(
                    provider="ses",
                    provider_event_id=feedback_id,
                    provider_message_id=provider_message_id,
                    event_type=event_type,
                    reason_code=bounce_sub_type,
                    occurred_at=occurred_at,
                    event_payload={
                        "bounce_type": bounce_type,
                        "bounce_sub_type": bounce_sub_type,
                    },
                )
            )

    elif notification_type == "complaint":
        complaint = payload.get("complaint", {})
        feedback_id = complaint.get("feedbackId") or f"{provider_message_id}_complaint"
        occurred_at = _parse_timestamp(complaint.get("timestamp") or mail.get("timestamp"))

        events.append(
            NormalizedDeliveryFailure(
                provider="ses",
                provider_event_id=feedback_id,
                provider_message_id=provider_message_id,
                event_type="complaint",
                reason_code=complaint.get("complaintFeedbackType"),
                occurred_at=occurred_at,
                event_payload={
                    "complaint_feedback_type": complaint.get("complaintFeedbackType"),
                    "user_agent": complaint.get("userAgent"),
                },
            )
        )

    return events


def _normalize_klaviyo(data: Any) -> List[NormalizedDeliveryFailure]:
    """Normalize Klaviyo webhook events."""
    items = data if isinstance(data, list) else [data]
    events: List[NormalizedDeliveryFailure] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        # Handle Klaviyo JSON:API or raw event envelope
        attrs = item.get("data", {}).get("attributes", {}) if "data" in item else item
        raw_event_type = str(attrs.get("metric_name") or attrs.get("type") or attrs.get("event") or "").strip().lower()

        if "bounced" in raw_event_type or "bounce" in raw_event_type:
            event_type = "bounce"
        elif "dropped" in raw_event_type:
            event_type = "dropped"
        elif "spam" in raw_event_type or "complaint" in raw_event_type:
            event_type = "complaint"
        else:
            continue

        provider_event_id = str(item.get("id") or attrs.get("id") or attrs.get("event_id") or "")
        provider_message_id = str(attrs.get("message_id") or attrs.get("campaign_id") or attrs.get("flow_id") or "") or None
        occurred_at = _parse_timestamp(attrs.get("timestamp") or attrs.get("datetime"))
        recipient_email = attrs.get("email") or attrs.get("recipient")

        events.append(
            NormalizedDeliveryFailure(
                provider="klaviyo",
                provider_event_id=provider_event_id,
                provider_message_id=provider_message_id,
                event_type=event_type,
                reason_code=attrs.get("reason") or raw_event_type,
                occurred_at=occurred_at,
                recipient_email_hash=hash_email(recipient_email),
                event_payload={
                    "metric_name": raw_event_type,
                    "reason": attrs.get("reason"),
                },
            )
        )

    return events


def normalize_provider_events(provider: str, raw_body: bytes) -> List[NormalizedDeliveryFailure]:
    """
    Parse and normalize delivery-failure webhook events across supported ESPs.
    Fails closed: returns empty list if payload is malformed or unparseable.
    """
    clean_provider = provider.strip().lower()
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to parse JSON body for provider {clean_provider}: {exc}")
        return []

    if clean_provider == "postmark":
        return _normalize_postmark(data)
    elif clean_provider == "sendgrid":
        return _normalize_sendgrid(data)
    elif clean_provider == "mailgun":
        return _normalize_mailgun(data)
    elif clean_provider == "ses":
        return _normalize_ses(data)
    elif clean_provider == "klaviyo":
        return _normalize_klaviyo(data)
    else:
        logger.warning(f"Unsupported ESP provider for event normalization: {clean_provider}")
        return []
