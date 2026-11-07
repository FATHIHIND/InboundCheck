"""Fail-closed service-only RPC boundary. No in-process durability fallback."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID
from typing import Any

from .minimization import PrivacyValidationError, minimize_request

_DEFAULT_CLIENT = object()

STATES = frozenset({"queued", "processing", "completed", "failed", "requires_manual_review"})


class PrivacyAcceptanceError(RuntimeError):
    """Retryable storage/contract failure; safe for HTTP 503 translation."""


def _client_or_default(client: Any) -> Any:
    if client is _DEFAULT_CLIENT:
        from app.services.supabase_client import supabase_service
        # SupabaseService exposes the PostgREST client only as ``_client``; a
        # missing attribute here previously turned every GDPR webhook into 503.
        client = getattr(supabase_service, "_client", None)
    if client is None:
        raise PrivacyAcceptanceError("Privacy persistence unavailable")
    return client


def call_rpc(client: Any, name: str, params: dict) -> Any:
    try:
        response = _client_or_default(client).rpc(name, params).execute()
        if getattr(response, "error", None):
            raise PrivacyAcceptanceError("Privacy persistence unavailable")
        return response.data
    except Exception:
        # Do not expose/log provider exceptions: they may contain raw query data.
        raise PrivacyAcceptanceError("Privacy persistence unavailable") from None


def require_uuid(value: Any) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise PrivacyAcceptanceError("Invalid privacy persistence receipt") from None


def accept_gdpr_request(kind: str, shop: str, payload: dict, delivery_id: str, *, client: Any = _DEFAULT_CLIENT) -> dict:
    """Call after HMAC/header/topic checks, synchronously BEFORE HTTP acknowledgement.

    Returns a durable acceptance receipt, never a claim of subject-right completion.
    Tenant identity is resolved in SQL from the verified shop; caller user_id ignored.
    """
    clean_shop, selectors = minimize_request(kind, shop, payload)
    if not isinstance(delivery_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", delivery_id):
        raise PrivacyValidationError("Missing or invalid webhook delivery identifier")
    canonical = {"kind": kind, "shop": clean_shop, **selectors}
    request_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    data = call_rpc(client, "enqueue_privacy_job", {
        "p_event_id": delivery_id, "p_request_hash": request_hash,
        "p_shop_domain": clean_shop, "p_kind": kind,
        "p_subject_hash": selectors.get("customer_email_hash"),
        "p_customer_id": selectors.get("customer_id_hash"),
    })
    if not isinstance(data, dict) or data.get("status") != "accepted" or data.get("state") not in STATES or type(data.get("idempotent")) is not bool:
        raise PrivacyAcceptanceError("Invalid privacy persistence receipt")
    return {"status": "accepted", "job_id": require_uuid(data.get("job_id")), "state": data["state"], "idempotent": data["idempotent"]}
