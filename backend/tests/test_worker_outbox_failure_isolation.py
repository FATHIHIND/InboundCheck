"""
Failover worker reliability regression tests (DB-2 / OPS-2 production outage).

Production symptom: claim_notification_outbox raised PGRST202 every ~5s. The loop
had already claimed delivery-failure events (900s lease) but only registered them
for release after BOTH claims succeeded, so every cycle stranded leases.

These tests prove:
- An outbox claim failure never strands delivery-failure leases (events are
  either processed or released).
- Delivery-failure processing proceeds when the outbox queue is broken.
- The failure is still surfaced through the loop error path (ops alert).
- Error backoff is exponential, jittered, capped, and resets after success.
- Repeated schema/contract errors (PGRST202) make the worker exit non-zero.
- The startup schema contract probe fails closed only on a non-empty missing list.
"""

import asyncio
import uuid
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from app.core.schema_contract import SchemaContractResult, SchemaContractViolationError
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.supabase_client import DatabaseUnavailableError
from app.workers import failover_worker
from app.workers.failover_worker import compute_error_backoff, run_failover_worker

PGRST202_MSG = (
    "Database error claiming outbox: {'code': 'PGRST202', 'message': 'Could not find the function "
    "public.claim_notification_outbox(p_lease_timeout, p_limit, p_worker_id) in the schema cache'}"
)


def _events(n: int) -> List[dict]:
    return [{"id": f"evt_{uuid.uuid4().hex[:8]}", "event_type": "bounce"} for _ in range(n)]


def _ok_probe():
    return SchemaContractResult(status="ok", missing=[], detail="test")


class _SleepRecorder:
    """Injectable sleep that records delays and stops the worker after N sleeps."""

    def __init__(self, stop_event: asyncio.Event, stop_after: int):
        self.stop_event = stop_event
        self.stop_after = stop_after
        self.delays: List[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if len(self.delays) >= self.stop_after:
            self.stop_event.set()


@pytest.fixture
def no_ops_alerts():
    with patch(
        "app.services.alerting.ops_alert_service.ops_alert_service.dispatch_incident",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        yield mock_dispatch


# ---------------------------------------------------------------------------
# DB-2 / OPS-2: outbox failure must never strand delivery-failure leases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_outbox_claim_failure_does_not_strand_claimed_delivery_events(no_ops_alerts):
    events = _events(3)
    released: List[str] = []

    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=events), \
         patch.object(repository, "claim_notification_outbox", side_effect=DatabaseUnavailableError(PGRST202_MSG)), \
         patch.object(repository, "release_claimed_delivery_failure_event",
                      side_effect=lambda eid, wid: released.append(eid) or True), \
         patch("app.workers.failover_worker.process_delivery_failure_event", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = True
        await asyncio.wait_for(
            run_failover_worker(once=True, limit=3, schema_probe=_ok_probe),
            timeout=5.0,
        )

    processed = {c.args[0]["id"] for c in mock_process.call_args_list}
    all_ids = {e["id"] for e in events}
    # Every claimed lease is either processed or released; nothing is stranded.
    assert processed | set(released) == all_ids
    # Delivery-failure processing must proceed independently of the outbox queue.
    assert processed == all_ids


@pytest.mark.asyncio
async def test_outbox_claim_failure_is_still_reported_as_loop_error(no_ops_alerts):
    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=_events(1)), \
         patch.object(repository, "claim_notification_outbox", side_effect=DatabaseUnavailableError(PGRST202_MSG)), \
         patch("app.workers.failover_worker.process_delivery_failure_event", new_callable=AsyncMock):
        await asyncio.wait_for(
            run_failover_worker(once=True, limit=1, schema_probe=_ok_probe),
            timeout=5.0,
        )

    alert_ids = [c.args[0].alert_id for c in no_ops_alerts.call_args_list]
    assert "ALERT-WORKER-FAILOVER" in alert_ids


@pytest.mark.asyncio
async def test_outbox_failure_with_no_events_is_not_treated_as_idle(no_ops_alerts):
    """An outbox claim error must never be silently swallowed as an empty queue."""
    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=[]), \
         patch.object(repository, "claim_notification_outbox", side_effect=DatabaseUnavailableError(PGRST202_MSG)):
        await asyncio.wait_for(
            run_failover_worker(once=True, limit=1, schema_probe=_ok_probe),
            timeout=5.0,
        )
    assert no_ops_alerts.await_count >= 1


@pytest.mark.asyncio
async def test_event_processing_crash_releases_remaining_claimed_events(no_ops_alerts):
    events = _events(3)
    released: List[str] = []

    async def crash_on_first(event, worker_id):
        raise RuntimeError("boom")

    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=events), \
         patch.object(repository, "claim_notification_outbox", return_value=[]), \
         patch.object(repository, "release_claimed_delivery_failure_event",
                      side_effect=lambda eid, wid: released.append(eid) or True), \
         patch("app.workers.failover_worker.process_delivery_failure_event", side_effect=crash_on_first):
        await asyncio.wait_for(
            run_failover_worker(once=True, limit=3, schema_probe=_ok_probe),
            timeout=5.0,
        )

    # First event was attempted (and its in-flight entry popped); the other two must be released.
    assert set(released) == {events[1]["id"], events[2]["id"]}


# ---------------------------------------------------------------------------
# Bounded exponential backoff with jitter
# ---------------------------------------------------------------------------
def test_compute_error_backoff_grows_exponentially_and_caps():
    no_jitter = lambda: 1.0  # noqa: E731 - upper bound of the jitter window
    delays = [compute_error_backoff(n, base=5.0, cap=300.0, rand=no_jitter) for n in range(1, 10)]
    assert delays[:4] == [5.0, 10.0, 20.0, 40.0]
    assert max(delays) == 300.0
    assert all(d <= 300.0 for d in delays)
    assert delays == sorted(delays)


def test_compute_error_backoff_jitter_bounds():
    low = compute_error_backoff(3, base=5.0, cap=300.0, rand=lambda: 0.0)
    high = compute_error_backoff(3, base=5.0, cap=300.0, rand=lambda: 1.0)
    assert low == pytest.approx(10.0)  # half of the 20s exponential step
    assert high == pytest.approx(20.0)
    assert compute_error_backoff(50, base=5.0, cap=300.0, rand=lambda: 0.999) <= 300.0
    assert compute_error_backoff(0, base=5.0, cap=300.0, rand=lambda: 1.0) == 5.0


@pytest.mark.asyncio
async def test_worker_loop_backs_off_exponentially_on_consecutive_errors(no_ops_alerts):
    stop_event = asyncio.Event()
    sleeper = _SleepRecorder(stop_event, stop_after=4)

    with patch.object(repository, "claim_pending_delivery_failure_events",
                      side_effect=DatabaseUnavailableError("connection reset by peer")):
        await asyncio.wait_for(
            run_failover_worker(
                stop_event=stop_event,
                schema_probe=_ok_probe,
                sleep_func=sleeper,
                jitter_func=lambda: 1.0,
                error_backoff_base_seconds=5.0,
                error_backoff_max_seconds=300.0,
            ),
            timeout=5.0,
        )

    assert sleeper.delays == [5.0, 10.0, 20.0, 40.0]


@pytest.mark.asyncio
async def test_worker_loop_backoff_resets_after_successful_cycle(no_ops_alerts):
    stop_event = asyncio.Event()
    sleeper = _SleepRecorder(stop_event, stop_after=4)
    outcomes = [
        DatabaseUnavailableError("timeout"),
        DatabaseUnavailableError("timeout"),
        _events(1),  # success resets the backoff
        DatabaseUnavailableError("timeout"),
    ]

    def claim(**kwargs):
        item = outcomes.pop(0) if outcomes else DatabaseUnavailableError("timeout")
        if isinstance(item, Exception):
            raise item
        return item

    with patch.object(repository, "claim_pending_delivery_failure_events", side_effect=claim), \
         patch.object(repository, "claim_notification_outbox", return_value=[]), \
         patch("app.workers.failover_worker.process_delivery_failure_event", new_callable=AsyncMock):
        await asyncio.wait_for(
            run_failover_worker(
                stop_event=stop_event,
                schema_probe=_ok_probe,
                sleep_func=sleeper,
                jitter_func=lambda: 1.0,
            ),
            timeout=5.0,
        )

    assert sleeper.delays[:3] == [5.0, 10.0, 5.0]


# ---------------------------------------------------------------------------
# Schema-class errors: exit non-zero after N consecutive
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_worker_exits_after_consecutive_schema_errors(no_ops_alerts):
    stop_event = asyncio.Event()
    sleeper = _SleepRecorder(stop_event, stop_after=100)

    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=[]), \
         patch.object(repository, "claim_notification_outbox",
                      side_effect=DatabaseUnavailableError(PGRST202_MSG)) as mock_outbox:
        with pytest.raises(SchemaContractViolationError) as exc_info:
            await asyncio.wait_for(
                run_failover_worker(
                    stop_event=stop_event,
                    schema_probe=_ok_probe,
                    sleep_func=sleeper,
                    jitter_func=lambda: 1.0,
                    max_consecutive_schema_errors=3,
                ),
                timeout=5.0,
            )

    assert mock_outbox.call_count == 3
    assert len(sleeper.delays) == 2  # no sleep after the fatal third error
    assert "PGRST202" in str(exc_info.value)
    alert_ids = [c.args[0].alert_id for c in no_ops_alerts.call_args_list]
    assert "ALERT-WORKER-SCHEMA-CONTRACT" in alert_ids


@pytest.mark.asyncio
async def test_non_schema_errors_do_not_trigger_schema_exit(no_ops_alerts):
    stop_event = asyncio.Event()
    sleeper = _SleepRecorder(stop_event, stop_after=6)

    with patch.object(repository, "claim_pending_delivery_failure_events",
                      side_effect=DatabaseUnavailableError("connection refused")):
        await asyncio.wait_for(
            run_failover_worker(
                stop_event=stop_event,
                schema_probe=_ok_probe,
                sleep_func=sleeper,
                jitter_func=lambda: 0.5,
                max_consecutive_schema_errors=2,
            ),
            timeout=5.0,
        )
    assert len(sleeper.delays) == 6


def test_default_schema_error_threshold_is_safe():
    assert 3 <= failover_worker.DEFAULT_MAX_CONSECUTIVE_SCHEMA_ERRORS <= 20


# ---------------------------------------------------------------------------
# Startup schema contract probe
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_worker_refuses_to_start_when_contract_functions_missing(no_ops_alerts):
    missing_probe = lambda: SchemaContractResult(  # noqa: E731
        status="missing", missing=["claim_notification_outbox"], detail="test"
    )
    with patch.object(repository, "claim_pending_delivery_failure_events") as mock_claim:
        with pytest.raises(SchemaContractViolationError) as exc_info:
            await asyncio.wait_for(run_failover_worker(once=True, schema_probe=missing_probe), timeout=5.0)
    mock_claim.assert_not_called()
    assert "claim_notification_outbox" in str(exc_info.value)


@pytest.mark.asyncio
async def test_worker_starts_when_probe_rpc_not_deployed(no_ops_alerts):
    unknown_probe = lambda: SchemaContractResult(status="unknown", missing=[], detail="probe RPC absent")  # noqa: E731
    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=[]) as mock_claim:
        await asyncio.wait_for(run_failover_worker(once=True, schema_probe=unknown_probe), timeout=5.0)
    mock_claim.assert_called_once()
