"""
ARCH-1: database schema contract probe.

Proves the probe fails closed only on a positive "missing functions" answer,
fails open (with WARNING) when the probe RPC itself is not deployed, and that
/ready returns HTTP 503 (missing names are logged server-side, never returned).
"""

import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core import schema_contract as sc
from app.core.schema_contract import (
    SCHEMA_CONTRACT_PROBE_RPC,
    WORKER_REQUIRED_RPC_FUNCTIONS,
    SchemaContractResult,
    SchemaContractViolationError,
    enforce_schema_contract,
    is_schema_contract_error,
    probe_schema_contract,
)


class _FakeClient:
    def __init__(self, data=None, exc=None):
        self.data = data
        self.exc = exc
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        outer = self

        class _Q:
            def execute(self_inner):
                if outer.exc is not None:
                    raise outer.exc
                return SimpleNamespace(data=outer.data)

        return _Q()


PROBE_MISSING_EXC = Exception(
    "{'code': 'PGRST202', 'message': 'Could not find the function public.schema_contract_missing_functions(p_required)'}"
)


def test_probe_rpc_name_and_payload():
    client = _FakeClient(data=[])
    result = probe_schema_contract(client=client)
    assert result.status == "ok"
    name, params = client.calls[0]
    assert name == SCHEMA_CONTRACT_PROBE_RPC == "schema_contract_missing_functions"
    assert params == {"p_required": list(WORKER_REQUIRED_RPC_FUNCTIONS)}


def test_registry_covers_production_outage_function():
    assert "claim_notification_outbox" in WORKER_REQUIRED_RPC_FUNCTIONS
    assert "release_claimed_delivery_failure_event" in WORKER_REQUIRED_RPC_FUNCTIONS


def test_registry_matches_rpcs_called_on_worker_path():
    """Every RPC name in the registry is actually invoked by the worker data path."""
    backend = Path(__file__).resolve().parents[1]
    sources = "".join(
        (backend / p).read_text(encoding="utf-8")
        for p in ("app/services/supabase_client.py", "app/services/failover/failover_repository.py")
    )
    called = set(re.findall(r'\.rpc\(\s*"([a-z_]+)"', sources))
    assert set(WORKER_REQUIRED_RPC_FUNCTIONS) <= called


def test_missing_function_fails_closed():
    client = _FakeClient(data=["claim_notification_outbox"])
    result = probe_schema_contract(client=client)
    assert result.status == "missing"
    assert result.is_violation
    assert result.missing == ["claim_notification_outbox"]
    with pytest.raises(SchemaContractViolationError) as exc_info:
        enforce_schema_contract(lambda: result)
    assert exc_info.value.missing == ["claim_notification_outbox"]


def test_alternative_group_satisfied_by_either_member():
    only_primary_missing = probe_schema_contract(client=_FakeClient(data=["claim_pending_delivery_failure_events"]))
    assert only_primary_missing.status == "ok"
    both_missing = probe_schema_contract(client=_FakeClient(
        data=["claim_pending_delivery_failure_events", "claim_received_delivery_failure_events"]
    ))
    assert both_missing.status == "missing"
    assert len(both_missing.missing) == 1


def test_probe_rpc_not_deployed_is_unknown_and_fails_open(caplog):
    result = probe_schema_contract(client=_FakeClient(exc=PROBE_MISSING_EXC))
    assert result.status == "unknown"
    assert not result.is_violation
    assert "SCHEMA_CONTRACT_UNKNOWN" in caplog.text
    assert enforce_schema_contract(lambda: result).status == "unknown"


def test_transient_probe_error_fails_open():
    result = probe_schema_contract(client=_FakeClient(exc=ConnectionError("reset")))
    assert result.status == "error"
    assert not result.is_violation


def test_malformed_probe_response_fails_open():
    assert probe_schema_contract(client=_FakeClient(data={"oops": 1})).status == "error"


def test_no_client_is_skipped():
    assert probe_schema_contract(client_factory=lambda: None).status == "skipped"


def test_is_schema_contract_error_detects_chained_pgrst202():
    try:
        try:
            raise Exception("{'code': 'PGRST202'}")
        except Exception as inner:
            raise RuntimeError("Database error claiming outbox") from inner
    except RuntimeError as outer:
        assert is_schema_contract_error(outer)
    assert not is_schema_contract_error(ConnectionError("connection refused"))
    assert is_schema_contract_error(Exception("function public.x() does not exist (42883)"))


def test_cached_result_bounds_probe_calls():
    sc.reset_schema_contract_cache()
    calls = []

    def fake_probe(*a, **k):
        calls.append(1)
        return SchemaContractResult(status="ok")

    try:
        with patch.object(sc, "probe_schema_contract", side_effect=fake_probe):
            for _ in range(5):
                sc.get_cached_schema_contract_result(ttl_seconds=60)
        assert len(calls) == 1
    finally:
        sc.reset_schema_contract_cache()


# ---------------------------------------------------------------------------
# /ready wiring
# ---------------------------------------------------------------------------
def _ready(result):
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.services.supabase_client.supabase_service.check_db_health", return_value=True), \
         patch("app.core.schema_contract.get_cached_schema_contract_result", return_value=result):
        return TestClient(app).get("/ready")


def test_ready_returns_503_without_leaking_missing_function_names(caplog):
    caplog.set_level(logging.ERROR)
    res = _ready(SchemaContractResult(status="missing", missing=["claim_notification_outbox"]))
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unavailable"
    assert body["schema_contract"] == "missing"
    assert body["dependencies"]["schema_contract"] == "missing"
    assert body["dependencies"]["database"] == "healthy"
    # REV-4: unauthenticated /ready must not enumerate internal function names...
    assert "missing_functions" not in body
    assert "claim_notification_outbox" not in res.text
    # ...but operators still get them server-side at ERROR.
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("claim_notification_outbox" in r.getMessage() for r in errors)


def test_ready_stays_200_when_probe_rpc_not_deployed():
    res = _ready(SchemaContractResult(status="unknown"))
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["dependencies"]["schema_contract"] == "unknown"


def test_ready_stays_200_when_contract_ok():
    res = _ready(SchemaContractResult(status="ok"))
    assert res.status_code == 200
    assert res.json()["dependencies"]["schema_contract"] == "ok"
