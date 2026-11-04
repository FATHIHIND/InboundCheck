"""Pure-source release gate tests; run ONLY through scripts/safe_backend_tests.py."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_script("validate_migration_sources")
safety = load_script("check_release_safety")


def fixture_repo(tmp_path, manifest='(("20260101000001", "one"),)'):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "supabase/migrations").mkdir(parents=True)
    (tmp_path / "scripts/reconcile_migration_ledger.py").write_text(
        f"raise RuntimeError('must never execute')\nCANONICAL_MIGRATIONS = {manifest}\n", encoding="utf-8")
    (tmp_path / "supabase/migrations/20260101000001_one.sql").write_text("SELECT 1;", encoding="utf-8")
    return tmp_path


def test_manifest_read_never_executes_module(tmp_path):
    root = fixture_repo(tmp_path)
    assert migration.validate(root, lambda text: [object()]) == 1


def test_manifest_computed_value_rejected_without_execution(tmp_path):
    root = fixture_repo(tmp_path, "__import__('os').getcwd()")
    with pytest.raises(ValueError):
        migration.read_manifest(root / "scripts/reconcile_migration_ledger.py")


@pytest.mark.parametrize("manifest", ['()', '(("20260101000001", "one"), ("20260101000001", "two"))', '(("20260101000002", "two"), ("20260101000001", "one"))'])
def test_invalid_manifest_rejected(tmp_path, manifest):
    root = fixture_repo(tmp_path, manifest)
    with pytest.raises(ValueError):
        migration.read_manifest(root / "scripts/reconcile_migration_ledger.py")


def test_unmanifested_migration_fails_before_parser(tmp_path):
    root = fixture_repo(tmp_path)
    (root / "supabase/migrations/20260101000002_two.sql").write_text("SELECT 2;")
    with pytest.raises(ValueError, match="inventory"):
        migration.validate(root, lambda text: pytest.fail("parser must not run on drift"))


def test_sql_parser_failure_does_not_echo_sql(tmp_path):
    root = fixture_repo(tmp_path)
    def bad_parser(text):
        raise ValueError("sensitive fixture SQL")
    with pytest.raises(ValueError) as exc:
        migration.validate(root, bad_parser)
    assert "sensitive fixture" not in str(exc.value)


@pytest.mark.parametrize("name", [".env", "backend/.env.production", ".env.local", "keys/service.key", "credentials.json", ".npmrc"])
def test_tracked_credentials_are_forbidden_without_reading(tmp_path, name):
    assert safety.forbidden_path(name)
    assert safety.inspect_files(tmp_path, [name]) == [f"{name}: forbidden credential/dotenv path"]


def test_example_and_env_source_names_allowed():
    for name in [".env.example", "backend/.env.example", "backend/app/core/env_guard.py", "frontend/next-env.d.ts"]:
        assert not safety.forbidden_path(name)


def test_secret_content_redacted(tmp_path):
    token = "sk_" + "live_" + "A" * 30
    (tmp_path / "source.txt").write_text(token)
    errors = safety.inspect_files(tmp_path, ["source.txt"])
    assert errors == ["source.txt: stripe-secret"]
    assert token not in repr(errors)


def test_hash_lock_matches_direct_requirements():
    assert safety.lock_errors(ROOT) == []


def test_missing_and_unhashed_lock_fail_closed(tmp_path):
    (tmp_path / "backend").mkdir()
    assert safety.lock_errors(tmp_path)
    (tmp_path / "backend/requirements.txt").write_text("demo==1.0\n")
    (tmp_path / "backend/requirements.lock").write_text("demo==1.0\n")
    assert safety.lock_errors(tmp_path)


def test_workflow_contract_no_live_environment_or_deployment():
    text = (ROOT / ".github/workflows/release-gates.yml").read_text()
    for required in ["contents: read", "python scripts/safe_backend_tests.py -q", "python scripts/validate_migration_sources.py", "--require-hashes", "node-version: '24'"]:
        assert required in text
    for script in ["lint", "typecheck", "test", "build"]:
        assert f"npm run {script} --workspace frontend" in text
    for forbidden in ["pull_request_target", "secrets.", "id-token:", "contents: write", "supabase db", "vercel deploy", "railway up"]:
        assert forbidden not in text


def test_docker_keeps_runtime_and_hashes_without_dropping_direct_extras():
    text = (ROOT / "backend/Dockerfile").read_text()
    assert "FROM python:3.11-slim" in text
    assert "COPY requirements.txt requirements.lock ./" in text
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock -r requirements.txt" in text
    assert "pip install --no-cache-dir -r requirements.txt" not in text


def test_ci_checks_linux_actual_runtime_and_keeps_direct_requirements():
    text = (ROOT / ".github/workflows/release-gates.yml").read_text()
    section = text.split("  backend-linux-runtime:", 1)[1].split("  frontend-checks:", 1)[0]
    assert "name: backend-linux-runtime" in section
    assert "runs-on: ubuntu-latest" in section
    assert "python-version: '3.11'" in section
    assert "--require-hashes -r backend/requirements.lock -r backend/requirements.txt" in section
    assert "python scripts/safe_backend_tests.py -q" in section


def test_portable_uvicorn_docker_command_and_direct_requirement():
    import json
    docker = (ROOT / "backend/Dockerfile").read_text()
    command = json.loads(next(line[4:] for line in docker.splitlines() if line.startswith("CMD ")))
    assert command[0:2] == ["uvicorn", "app.main:app"]
    assert command[command.index("--loop") + 1] == "asyncio"
    assert command[command.index("--http") + 1] == "h11"
    requirements = (ROOT / "backend/requirements.txt").read_text().splitlines()
    assert "uvicorn==0.30.1" in requirements
    assert not any(line.startswith("uvicorn[") for line in requirements)


def test_uvicorn_cli_supports_portable_runtime_without_importing_application():
    from click.testing import CliRunner
    from uvicorn.main import main
    result = CliRunner().invoke(main, ["--loop", "asyncio", "--http", "h11", "--help"])
    assert result.exit_code == 0, result.output
    assert "asyncio" in result.output
    assert "h11" in result.output


def test_uvicorn_config_loads_standard_library_loop_and_h11_protocol():
    from uvicorn import Config
    from uvicorn.protocols.http.h11_impl import H11Protocol
    async def isolated_asgi(scope, receive, send):
        pass
    config = Config(isolated_asgi, loop="asyncio", http="h11", lifespan="off", log_config=None)
    config.load()
    assert config.loop == "asyncio"
    assert config.http_protocol_class is H11Protocol
