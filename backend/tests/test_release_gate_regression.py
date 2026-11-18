"""Pure-source release gate tests (S0).

Designed for scripts/safe_backend_tests.py; also collectable by plain pytest.
The Docker/uvicorn runtime contract tests live in test_dependency_runtime_contract.py (S6.2).
"""
import importlib.util
import os
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


def test_repository_migration_inventory_matches_manifest_without_sql_parsing():
    # Inventory/manifest parity on the real tree; SQL parsing (pglast) is exercised in CI.
    rows = migration.read_manifest(ROOT / "scripts/reconcile_migration_ledger.py")
    assert migration.validate(ROOT, lambda text: [object()]) == len(rows)


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
    # Frontend job / npm audit assertions are restored with the frontend slice (PR-J).
    text = (ROOT / ".github/workflows/release-gates.yml").read_text()
    for required in ["contents: read", "persist-credentials: false", "python scripts/safe_backend_tests.py -q",
                     "python scripts/check_release_safety.py", "python scripts/validate_migration_sources.py",
                     "--require-hashes"]:
        assert required in text
    for forbidden in ["pull_request_target", "secrets.", "id-token:", "contents: write", "supabase db", "vercel deploy", "railway up"]:
        assert forbidden not in text


def test_ci_checks_linux_actual_runtime_and_keeps_direct_requirements():
    text = (ROOT / ".github/workflows/release-gates.yml").read_text()
    section = text.split("  backend-linux-runtime:", 1)[1].split("  dependency-security:", 1)[0]
    assert "name: backend-linux-runtime" in section
    assert "runs-on: ubuntu-latest" in section
    assert "python-version: '3.11'" in section
    assert "--require-hashes -r backend/requirements.lock -r backend/requirements.txt" in section
    assert "python scripts/safe_backend_tests.py -q" in section


def _workflow_text():
    return (ROOT / ".github/workflows/release-gates.yml").read_text(encoding="utf-8")


def _locked_entries(path):
    """Return {name: (version, hashes)}; every non-comment entry must be pinned and hashed."""
    import re
    entries = {}
    logical = path.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in logical.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)(?:\s*;[^#]+?)?\s+((?:--hash=sha256:[a-f0-9]{64}\s*)+)(?:#.*)?", line)
        assert match, f"{path.name}: unpinned or unhashed entry"
        entries[match[1].lower().replace("_", "-")] = (match[2], set(match[3].split()))
    return entries


def _all_workflow_files():
    files = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    assert files, "no workflow files found"
    return files


def test_every_workflow_file_parses_as_yaml_and_release_gates_has_the_four_jobs():
    # Text-only checks cannot see YAML syntax errors; GitHub runs zero jobs for an unparsable file.
    import yaml
    workflows = sorted((ROOT / ".github/workflows").glob("*.yml")) + sorted((ROOT / ".github/workflows").glob("*.yaml"))
    assert workflows, "no workflow files found"
    parsed = {}
    for workflow in workflows:
        try:
            document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # report location only, not file content
            mark = getattr(exc, "problem_mark", None)
            where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "unknown position"
            pytest.fail(f"{workflow.name}: invalid YAML at {where}")
        assert isinstance(document, dict) and isinstance(document.get("jobs"), dict), f"{workflow.name}: no jobs mapping"
        parsed[workflow.name] = document
    jobs = parsed["release-gates.yml"]["jobs"]
    assert set(jobs) == {"source-safety", "backend-safe", "backend-linux-runtime", "dependency-security"}
    for name, job in jobs.items():
        assert job.get("name") == name and job.get("steps"), name
    tool_install = "python -m pip install --require-hashes --only-binary=:all: -r ci/requirements-ci-tools.lock"
    for name in ("source-safety", "dependency-security"):
        assert tool_install in [step.get("run") for step in jobs[name]["steps"]], name


def test_every_action_is_pinned_to_a_full_commit_sha_with_version_comment():
    # Any `uses` key in any workflow file (block, flow or quoted form) must be a SHA pin.
    import re
    pinned = re.compile(r"-?\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+")
    seen = 0
    for workflow in _all_workflow_files():
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if re.search(r"""\buses\b["']?\s*:""", line):
                seen += 1
                assert pinned.fullmatch(line.strip()), f"{workflow.name}: {line.strip()}"
    assert seen, "workflow must use actions"


def test_ci_tools_install_only_from_the_hash_lock():
    import re
    installer = re.compile(r"\b(?:pip3?|uv\s+pip|pipx)\s+(?:install|download|sync)\b")
    installs = [line.strip() for workflow in _all_workflow_files()
                for line in workflow.read_text(encoding="utf-8").splitlines() if installer.search(line)]
    assert installs
    for line in installs:
        assert "--require-hashes" in line, line
        assert re.search(r"\s-r\s+\S+\.(?:lock|txt)\b", line), line  # never a bare `pip install name==version`
    tool_installs = [line for line in installs if "ci/requirements-ci-tools.lock" in line]
    # Exactly the source-safety and dependency-security jobs; update deliberately if a tool job is added.
    assert len(tool_installs) == 2
    for line in tool_installs:
        assert "--only-binary=:all:" in line
        assert "backend/requirements" not in line


def test_ci_tools_lock_is_fully_hashed_and_separate_from_runtime():
    import re
    lock = _locked_entries(ROOT / "ci/requirements-ci-tools.lock")
    direct = {}
    for line in (ROOT / "ci/requirements-ci-tools.in").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, version = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+)", line).groups()
            direct[name.lower()] = version
    assert direct == {"pglast": "8.7", "pip-audit": "2.9.0", "bandit": "1.8.6"}
    for name, version in direct.items():
        assert lock[name][0] == version
    assert all(hashes for _, hashes in lock.values())

    def normalize(name):  # PEP 503
        return re.sub(r"[-_.]+", "-", name).lower()

    runtime_direct = set()
    for line in (ROOT / "backend/requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            runtime_direct.add(normalize(re.match(r"[A-Za-z0-9_.-]+", line).group(0)))
    runtime_lock = {normalize(name) for name in _locked_entries(ROOT / "backend/requirements.lock")}
    for tool in map(normalize, direct):
        assert tool not in runtime_direct
        assert tool not in runtime_lock


@pytest.mark.skipif(os.environ.get("INBOUNDCHECK_SAFE_TEST_RUNNER") != "1",
                    reason="audit-hook isolation is installed only by scripts/safe_backend_tests.py")
def test_safe_runner_denies_native_udp_socket_creation_before_io():
    import socket
    for family in (socket.AF_INET, socket.AF_INET6):
        with pytest.raises(PermissionError, match="Datagram socket creation is disabled"):
            socket.socket(family, socket.SOCK_DGRAM)
