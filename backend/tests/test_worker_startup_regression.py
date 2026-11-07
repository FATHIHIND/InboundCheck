"""Offline runner entrypoint coverage; execute through scripts/safe_backend_tests.py.

No new subprocess allowance: import the real entrypoint into an isolated module
namespace and replace work dispatch before calling it. The companion import
regression covers the real dependency chain in its existing approved subprocess.
"""
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def runner(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "app/workers/runner.py"
    spec = importlib.util.spec_from_file_location("offline_startup_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr("sys.argv", ["runner.py"])
    # Never permit a regression to fall through to actual queue work.
    monkeypatch.setattr(module, "run_audit_worker", AsyncMock())
    monkeypatch.setattr(module, "run_failover_worker", AsyncMock())
    return module


@pytest.mark.parametrize("mode", ["audit", "failover", "all"])
@pytest.mark.parametrize("limit_args", [["--limit=7"], ["--limit", "7"]])
def test_cli_selects_exact_mode_without_running_workers(runner, monkeypatch, mode, limit_args):
    startup = AsyncMock()
    monkeypatch.setattr(runner, "main", startup)
    assert runner.cli([mode, "--once", *limit_args]) == 0
    startup.assert_awaited_once_with(worker_type=mode, once=True, limit=7)
    runner.run_audit_worker.assert_not_called()
    runner.run_failover_worker.assert_not_called()


def test_cli_default_remains_audit(runner, monkeypatch):
    startup = AsyncMock()
    monkeypatch.setattr(runner, "main", startup)
    assert runner.cli([]) == 0
    startup.assert_awaited_once_with(worker_type="audit", once=False, limit=25)


@pytest.mark.parametrize("args", [
    ["typo"], ["audit", "failover"], ["--unknown"], ["--staging"],
    ["--limit=oops"], ["--limit=0"], ["--limit=-1"], ["--limit"],
])
def test_bad_cli_arguments_exit_before_startup(runner, monkeypatch, args):
    startup = AsyncMock()
    monkeypatch.setattr(runner, "main", startup)
    with pytest.raises(SystemExit) as exc:
        runner.cli(args)
    assert exc.value.code == 2
    startup.assert_not_called()


def test_cli_preserves_nonzero_worker_exit(runner, monkeypatch):
    monkeypatch.setattr(runner, "main", AsyncMock(side_effect=SystemExit(9)))
    with pytest.raises(SystemExit) as exc:
        runner.cli(["failover"])
    assert exc.value.code == 9


def test_cli_does_not_hide_runtime_validation_failure(runner, monkeypatch):
    monkeypatch.setattr(runner, "main", AsyncMock(side_effect=RuntimeError("invalid worker configuration")))
    with pytest.raises(RuntimeError, match="invalid worker configuration"):
        runner.cli(["failover"])


def test_staging_cli_never_loads_runtime_configuration(runner, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", " Staging ")
    startup = AsyncMock()
    monkeypatch.setattr(runner, "main", startup)
    assert runner.cli(["failover"]) == 2
    startup.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"worker_type": "typo"}, {"limit": 0}, {"limit": -1}, {"limit": True}, {"limit": "7"},
])
def test_direct_main_rejects_bad_arguments_before_environment_validation(runner, monkeypatch, kwargs):
    validator = Mock(side_effect=AssertionError("settings must not be loaded"))
    monkeypatch.setattr(runner, "validate_worker_runtime_environment", validator)
    with pytest.raises(ValueError):
        asyncio.run(runner.main(**kwargs))
    validator.assert_not_called()
    runner.run_audit_worker.assert_not_called()
    runner.run_failover_worker.assert_not_called()


@pytest.mark.parametrize("mode", ["audit", "failover", "all"])
def test_startup_failure_cannot_reach_work_dispatch(runner, monkeypatch, mode):
    monkeypatch.setattr(runner, "validate_worker_runtime_environment", Mock(side_effect=RuntimeError("missing persistence")))
    with pytest.raises(RuntimeError, match="missing persistence"):
        asyncio.run(runner.main(worker_type=mode))
    runner.run_audit_worker.assert_not_called()
    runner.run_failover_worker.assert_not_called()


def test_whitespace_cannot_disable_production_worker_guard(monkeypatch):
    from app.core.config import settings
    from app.core.env_guard import validate_worker_runtime_environment
    monkeypatch.setattr(settings, "ENVIRONMENT", " Production ")
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    with pytest.raises(RuntimeError, match="Production Worker Environment Integrity Failure"):
        validate_worker_runtime_environment()


def test_api_environment_guard_normalizes_like_host_guard(monkeypatch):
    from app.core.config import settings
    from app.core.env_guard import validate_runtime_environment
    monkeypatch.setattr(settings, "ENVIRONMENT", " Production ")
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "")
    with pytest.raises(RuntimeError, match="Production Environment Integrity Failure"):
        validate_runtime_environment()
