"""Minimal Telegram delivery result safe to return, log, or persist."""

from typing import Any, Dict
import re


_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s().\-]{6,}\d")


def redact_telegram_text(value: Any, max_chars: int = 200) -> str:
    """Remove direct email/phone identifiers and bound untrusted alert text."""
    text = "" if value is None else str(value)
    text = _EMAIL_PATTERN.sub("[redacted-email]", text)
    text = _PHONE_PATTERN.sub(
        lambda match: "[redacted-phone]" if sum(char.isdigit() for char in match.group(0)) >= 7 else match.group(0),
        text,
    )
    text = text.replace("`", "'")
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def safe_telegram_delivery_result(response: Any) -> Dict[str, Any]:
    """Drop provider body, recipient metadata, and free-form error text."""
    raw = response if isinstance(response, dict) else {}
    result = {
        "success": raw.get("success") is True,
        "skipped": raw.get("skipped") is True,
        "simulated": raw.get("simulated") is True,
        "retryable": raw.get("retryable") is True,
    }
    status_code = raw.get("status_code")
    if type(status_code) is int and 100 <= status_code <= 599:
        result["status_code"] = status_code
    retry_after = raw.get("retry_after")
    if type(retry_after) is int and 0 <= retry_after <= 86400:
        result["retry_after"] = retry_after
    if not result["success"]:
        result["error"] = "Telegram delivery failed"
    return result


def safe_telegram_message_id(value: Any, simulated: bool = False) -> str | None:
    """Accept only a Telegram numeric ID or our bounded simulation ID."""
    if type(value) is int and 0 < value < 2**63:
        return str(value)
    if isinstance(value, str):
        if re.fullmatch(r"[1-9][0-9]{0,18}", value) and int(value) < 2**63:
            return value
        if simulated and re.fullmatch(r"mock_tg_[0-9a-f]{8}", value):
            return value
    return None
