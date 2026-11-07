"""
InboundCheck - Database Schema Contract Probe (ARCH-1)
======================================================
Verifies at startup (worker) and on readiness (API ``/ready``) that the Postgres
RPC functions the failover worker depends on actually exist, so a missing
migration is detected once, loudly, instead of as a PGRST202 every poll cycle.

DATABASE DEPENDENCY (must be provided by a migration)
----------------------------------------------------
PostgREST cannot query ``pg_proc`` directly, so the probe calls one RPC::

    public.schema_contract_missing_functions(p_required text[]) RETURNS text[]

It must return the subset of ``p_required`` names that do NOT exist as functions
in schema ``public`` (an empty array when everything is present). It should be
``SECURITY DEFINER`` with a pinned ``search_path`` and EXECUTE granted only to
``service_role``.

Probe outcomes
--------------
- ``ok``       : every required function (group) exists.
- ``missing``  : at least one required group is absent -> FAIL CLOSED
                 (worker refuses to start; ``/ready`` returns 503 with the names).
- ``unknown``  : the probe RPC itself is not deployed (PGRST202 on the probe).
                 Logged as WARNING and treated as fail-open. This is the ONLY
                 fail-open case, so rollout does not depend on deploy ordering.
- ``error``    : transient/malformed probe failure -> WARNING, fail-open (the
                 worker loop's own error handling and backoff still apply).
- ``skipped``  : no database client (local development / automated tests).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("SchemaContract")

SCHEMA_CONTRACT_PROBE_RPC = "schema_contract_missing_functions"

# Each group is satisfied when at least ONE of its members exists. Single-member
# groups are hard requirements. Derived from the RPC calls made on the failover
# worker path (failover_worker.py -> failover_repository.py -> supabase_client.py).
WORKER_REQUIRED_RPC_GROUPS: Tuple[Tuple[str, ...], ...] = (
    # Delivery-failure queue (claim has a legacy fallback RPC name).
    ("claim_pending_delivery_failure_events", "claim_received_delivery_failure_events"),
    ("release_claimed_delivery_failure_event",),
    ("mark_delivery_failure_event_processed",),
    ("mark_delivery_failure_event_failed",),
    ("record_delivery_failure_dispatch_intent",),
    ("quarantine_expired_dispatch_intent_events",),
    ("schedule_delivery_failure_retry",),
    # Durable notification outbox.
    ("claim_notification_outbox",),
    ("record_notification_outbox_dispatch_intent",),
    ("complete_notification_outbox",),
    ("fail_or_retry_notification_outbox",),
)


def flatten_required_functions(groups: Sequence[Sequence[str]] = WORKER_REQUIRED_RPC_GROUPS) -> List[str]:
    """Return every function name referenced by the contract, de-duplicated, order preserved."""
    seen: List[str] = []
    for group in groups:
        for name in group:
            if name not in seen:
                seen.append(name)
    return seen


WORKER_REQUIRED_RPC_FUNCTIONS: Tuple[str, ...] = tuple(flatten_required_functions())

# Error markers for schema/contract-class failures (as opposed to transient outages).
_SCHEMA_ERROR_MARKERS = (
    "PGRST202",  # function not found in schema cache
    "PGRST205",  # table not found in schema cache
    "PGRST204",  # column not found in schema cache
    "42883",  # undefined_function
    "42P01",  # undefined_table
    "COULD NOT FIND THE FUNCTION",
)


class SchemaContractViolationError(RuntimeError):
    """Raised when required database functions are missing (fatal; process must exit non-zero)."""

    def __init__(self, message: str, missing: Optional[Iterable[str]] = None):
        super().__init__(message)
        self.missing: List[str] = list(missing or [])


@dataclass
class SchemaContractResult:
    status: str  # ok | missing | unknown | error | skipped
    missing: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def is_violation(self) -> bool:
        return self.status == "missing" and bool(self.missing)


def is_schema_contract_error(exc: BaseException) -> bool:
    """True if the exception (or anything in its cause/context chain) is a schema-class error."""
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = f"{current!s} {current!r}".upper()
        if any(marker in text for marker in _SCHEMA_ERROR_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _default_client() -> Any:
    from app.services.supabase_client import supabase_service

    return getattr(supabase_service, "_client", None)


def probe_schema_contract(
    groups: Sequence[Sequence[str]] = WORKER_REQUIRED_RPC_GROUPS,
    client: Any = None,
    client_factory: Callable[[], Any] = _default_client,
) -> SchemaContractResult:
    """Ask the database which required functions are missing. Never raises."""
    if client is None:
        try:
            client = client_factory()
        except Exception as exc:  # pragma: no cover - defensive
            return SchemaContractResult(status="error", detail=f"client unavailable: {type(exc).__name__}")
    if client is None:
        return SchemaContractResult(status="skipped", detail="no database client configured")

    required = flatten_required_functions(groups)
    try:
        res = client.rpc(SCHEMA_CONTRACT_PROBE_RPC, {"p_required": required}).execute()
    except Exception as exc:
        if is_schema_contract_error(exc):
            logger.warning(
                f"[SCHEMA_CONTRACT_UNKNOWN] Probe RPC public.{SCHEMA_CONTRACT_PROBE_RPC}(p_required text[]) "
                "is not deployed; required-function verification skipped (fail-open for probe absence only)."
            )
            return SchemaContractResult(status="unknown", detail="probe RPC not deployed")
        logger.warning(f"[SCHEMA_CONTRACT_ERROR] Schema contract probe failed: {type(exc).__name__}")
        return SchemaContractResult(status="error", detail=f"probe failed: {type(exc).__name__}")

    data = getattr(res, "data", None)
    if data is None:
        data = []
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        logger.warning("[SCHEMA_CONTRACT_ERROR] Schema contract probe returned a malformed response.")
        return SchemaContractResult(status="error", detail="malformed probe response")

    absent = set(data)
    missing_groups: List[str] = []
    for group in groups:
        if all(name in absent for name in group):
            missing_groups.append(" | ".join(group))

    if missing_groups:
        logger.critical(f"[SCHEMA_CONTRACT_VIOLATION] Required database functions missing: {missing_groups}")
        return SchemaContractResult(status="missing", missing=missing_groups, detail="required functions missing")
    return SchemaContractResult(status="ok", detail="all required functions present")


def enforce_schema_contract(probe: Callable[[], SchemaContractResult] = probe_schema_contract) -> SchemaContractResult:
    """Run the probe and raise SchemaContractViolationError only on a non-empty missing list."""
    result = probe()
    if result.is_violation:
        raise SchemaContractViolationError(
            f"Database schema contract violated; missing functions: {', '.join(result.missing)}",
            missing=result.missing,
        )
    return result


_cache_lock = threading.Lock()
_cache: Optional[Tuple[float, SchemaContractResult]] = None


def get_cached_schema_contract_result(ttl_seconds: float = 60.0) -> SchemaContractResult:
    """Probe result cached for ``ttl_seconds`` so frequent /ready polling costs at most one RPC per TTL."""
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and now - _cache[0] < ttl_seconds:
            return _cache[1]
    result = probe_schema_contract()
    if result.status != "skipped":
        with _cache_lock:
            _cache = (now, result)
    return result


def reset_schema_contract_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None
