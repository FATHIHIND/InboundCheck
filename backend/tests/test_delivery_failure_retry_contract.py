"""DB2-2 regression: schedule_delivery_failure_retry RPC response-contract handling.

Production defines ``public.schedule_delivery_failure_retry(...) RETURNS boolean``
(live catalog, verified 2026-11-08), while repository migration
20261031000002 defines ``RETURNS TABLE(event_id, new_status, attempt_count,
scheduled_for)``. The client must accept exactly those two contracts and fail
closed on anything else. Before the fix, a boolean response raised
``TypeError: object of type 'bool' has no len()`` which surfaced as
``DatabaseUnavailableError`` on every retry.

Only the external PostgREST client boundary is stubbed. The in-memory fallback is
disabled so the tests exercise production behaviour.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.supabase_client import DatabaseUnavailableError, supabase_service


class _Response:
    def __init__(self, data):
        self.data = data


class _StubRpcClient:
    """Minimal stand-in for the supabase-py client RPC chain: rpc(...).execute()."""

    def __init__(self, data):
        self._data = data
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        data = self._data

        class _Call:
            def execute(self_inner):
                return _Response(data)

        return _Call()


@pytest.fixture
def production_like(monkeypatch):
    """Install a stub client, forbid the in-memory fallback, and isolate the cache."""

    def install(data):
        stub = _StubRpcClient(data)
        monkeypatch.setattr(supabase_service, "_client", stub, raising=False)
        monkeypatch.setattr(supabase_service, "_allow_in_memory_fallback", lambda: False)
        monkeypatch.setattr(supabase_service, "_in_memory_delivery_failure_events", {}, raising=False)
        return stub

    return install


def _call():
    event_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    next_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    result = supabase_service.schedule_delivery_failure_retry(
        event_id=event_id,
        worker_id=worker_id,
        error="Telegram 429 Rate Limit",
        next_attempt_at=next_at,
        max_attempts=5,
    )
    return result, event_id, worker_id, next_at


def test_boolean_true_is_accepted_without_exception(production_like):
    """Live production contract: TRUE means the owner's retry transition committed."""
    stub = production_like(True)

    result, event_id, worker_id, next_at = _call()

    assert isinstance(result, dict)
    assert result["event_id"] == event_id
    assert result["contract"] == "boolean"
    # The server alone decides between requeue and dead-letter; the client must not guess.
    assert result["new_status"] == "scheduled_or_terminal"
    assert result["scheduled_for"] == next_at.isoformat()
    name, params = stub.calls[0]
    assert name == "schedule_delivery_failure_retry"
    assert set(params) == {"p_event_id", "p_worker_id", "p_error", "p_next_attempt_at", "p_max_attempts"}


def test_boolean_false_means_not_owner_and_returns_none(production_like):
    production_like(False)

    result, *_ = _call()

    assert result is None


def test_none_response_returns_none(production_like):
    production_like(None)

    result, *_ = _call()

    assert result is None


def test_table_contract_row_list_is_accepted(production_like):
    """Repository contract (20261031000002): RETURNS TABLE -> list of row objects."""
    row = {
        "event_id": "e-1",
        "new_status": "received",
        "attempt_count": 2,
        "scheduled_for": "2026-11-08T22:00:00+00:00",
    }
    production_like([row])

    result, *_ = _call()

    assert result == row


def test_table_contract_empty_list_means_not_owner(production_like):
    production_like([])

    result, *_ = _call()

    assert result is None


@pytest.mark.parametrize(
    "unexpected",
    [
        {"event_id": "e-1", "new_status": "received"},  # bare object: not produced by either contract
        "true",
        1,
        0,
        ["not-a-row"],
        [None],
        3.14,
    ],
    ids=["dict", "string", "int-1", "int-0", "list-of-str", "list-of-none", "float"],
)
def test_unexpected_shapes_fail_closed(production_like, unexpected):
    """Anything outside the two contracts must raise, never be treated as success."""
    production_like(unexpected)

    with pytest.raises(DatabaseUnavailableError):
        _call()


def test_true_does_not_write_an_invented_status_into_the_cache(production_like):
    """The boolean contract carries no row; the dev-only cache must not be mutated."""
    production_like(True)
    event_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    original = {
        "id": event_id,
        "processing_status": "dispatching",
        "claimed_by": worker_id,
        "lease_until": "2026-11-08T23:00:00+00:00",
    }
    supabase_service._in_memory_delivery_failure_events[event_id] = dict(original)

    result = supabase_service.schedule_delivery_failure_retry(
        event_id=event_id,
        worker_id=worker_id,
        error="transient",
        next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        max_attempts=5,
    )

    assert result is not None
    assert supabase_service._in_memory_delivery_failure_events[event_id] == original


def test_false_does_not_fall_through_to_in_memory_state_machine(production_like):
    """An authoritative 'not owner' answer must not be overridden by the local cache."""
    production_like(False)
    event_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    original = {
        "id": event_id,
        "processing_status": "dispatching",
        "claimed_by": worker_id,
        "dispatch_attempt_count": 1,
    }
    supabase_service._in_memory_delivery_failure_events[event_id] = dict(original)

    result = supabase_service.schedule_delivery_failure_retry(
        event_id=event_id,
        worker_id=worker_id,
        error="transient",
        next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        max_attempts=5,
    )

    assert result is None
    assert supabase_service._in_memory_delivery_failure_events[event_id] == original
