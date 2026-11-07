"""Allowlisted privacy selectors; never persist original webhook/customer data."""
from __future__ import annotations

import hashlib
import re
from typing import Any

KINDS = frozenset({"customers/data_request", "customers/redact", "shop/redact"})
SHOP = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")


class PrivacyValidationError(ValueError):
    """Malformed request. Messages deliberately exclude supplied values."""


def normalized_shop(shop: Any) -> str:
    if not isinstance(shop, str) or len(shop) > 255:
        raise PrivacyValidationError("Invalid shop domain")
    value = shop.strip().lower()
    if not SHOP.fullmatch(value):
        raise PrivacyValidationError("Invalid shop domain")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def minimize_request(kind: str, shop: Any, payload: Any) -> tuple[str, dict]:
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(payload, dict):
        raise PrivacyValidationError("Invalid privacy request")
    clean_shop = normalized_shop(shop)
    if "shop_domain" in payload and normalized_shop(payload["shop_domain"]) != clean_shop:
        raise PrivacyValidationError("Shop domain mismatch")
    selectors = {}
    if kind != "shop/redact":
        customer = payload.get("customer")
        if not isinstance(customer, dict):
            raise PrivacyValidationError("Missing customer selectors")
        email = customer.get("email")
        if email is not None:
            if not isinstance(email, str) or len(email) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
                raise PrivacyValidationError("Invalid customer email")
            selectors["customer_email_hash"] = _digest(email.strip().lower())
        customer_id = customer.get("id")
        if customer_id is not None:
            if isinstance(customer_id, bool) or not isinstance(customer_id, (int, str)) or not re.fullmatch(r"[0-9]{1,30}", str(customer_id)):
                raise PrivacyValidationError("Invalid customer identifier")
            selectors["customer_id_hash"] = _digest(str(customer_id))
        if not selectors:
            raise PrivacyValidationError("Missing customer selectors")
    return clean_shop, selectors


def minimize_diagnostics(value: Any) -> dict:
    """Drop free text, identifiers and unknown fields rather than guessing PII regexes.

    Only bounded numeric SMTP/HTTP status codes are useful safe diagnostics here.
    This helper does not yet wire existing ESP normalizers; owners must do so.
    """
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("smtp_status", "http_status"):
        code = value.get(key)
        if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
            result[key] = code
    return result
