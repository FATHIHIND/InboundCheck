"""Run local backend tests without project dotenv files or external network access.

Usage: python scripts/safe_backend_tests.py [tests/test_file.py ...] [-q]
The live staging lifecycle suite is always excluded. This runner is not a
substitute for separately authorized database integration tests.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import socket
import shlex
import subprocess
import textwrap
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    # Remove every application setting inherited from the desktop environment.
    tree = ast.parse((BACKEND / "app/core/config.py").read_text(encoding="utf-8-sig"))
    settings_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    setting_names = {n.target.id for n in settings_class.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    for key in list(os.environ):
        if key in setting_names or key.startswith(("STAGING_", "STRIPE_", "SUPABASE_", "SHOPIFY_", "TELEGRAM_", "OPS_ALERT_")):
            os.environ.pop(key, None)
    os.environ.update(ENVIRONMENT="test", STAGING_MODE="false", PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"):
        os.environ.pop(key, None)
    if any("test_staging_domain_audit_lifecycle" in arg for arg in sys.argv[1:]):
        raise ValueError("Live staging lifecycle tests are prohibited by the safe runner")
    sys.dont_write_bytecode = True
    root_norm = os.path.normcase(str(ROOT.resolve()))
    worker_tree = ast.parse((BACKEND / "tests/test_worker_import_regression.py").read_text(encoding="utf-8"))
    child_source = next(n.value.args[0].value for n in ast.walk(worker_tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "script" for t in n.targets))
    worker_command = [sys.executable, "-I", "-B", "-c", textwrap.dedent(child_source), str(BACKEND)]
    allowed_worker_command = subprocess.list2cmdline(worker_command)

    def safety_audit(event: str, args: tuple) -> None:
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            absolute = os.path.normcase(str(path.resolve()))
            if path.name.lower().startswith(".env") and (absolute == root_norm or absolute.startswith(root_norm + os.sep)):
                raise PermissionError("Safe tests cannot read project dotenv files")
        if event == "socket.connect":
            address = args[1]
            # CPython on Windows uses a loopback socket pair for asyncio wakeups.
            # No remote IPv4/IPv6 endpoints (including real billing/DB APIs) allowed.
            if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
                raise PermissionError("External network is disabled by safe_backend_tests")
        if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            if args[0] not in ("localhost", "127.0.0.1", "::1", None):
                raise PermissionError("External DNS is disabled by safe_backend_tests")
        if event in {"socket.sendto", "socket.sendmsg"}:
            address = args[-1]
            if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
                raise PermissionError("External datagrams are disabled by safe_backend_tests")
        if event == "subprocess.Popen":
            command = args[1]
            isolated_import = (command == allowed_worker_command) if isinstance(command, str) else (list(command) == worker_command)
            explicit_executable = args[0]
            if explicit_executable is not None and Path(explicit_executable).resolve() != Path(sys.executable).resolve():
                raise PermissionError("Alternate subprocess executable disabled in safe tests")
            if isolated_import:
                return  # Exact reviewed script; do not tokenize embedded Python source.
            parts = [part.strip('"') for part in shlex.split(command, posix=False)] if isinstance(command, str) else list(map(str, command))
            same_executable = bool(parts) and Path(parts[0]).resolve() == Path(sys.executable).resolve()
            reviewed_dry_run = (
                same_executable and len(parts) == 9
                and Path(parts[1]).resolve() == (ROOT / "scripts/reconcile_migration_ledger.py").resolve()
                and parts[2:4] == ["--dry-run", "--output-sql"]
                and parts[5] == "--output-rollback-sql" and parts[7] == "--output-verify-sql"
                and all(Path(parts[i]).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) for i in (4, 6, 8))
            )
            if not (reviewed_dry_run or isolated_import):
                raise PermissionError("Unreviewed subprocess disabled in safe tests")

    sys.addaudithook(safety_audit)
    for audit_event, audit_args in (
        ("open", (str(ROOT / ".env"), "r", 0)),
        ("socket.connect", (None, ("203.0.113.1", 443))),
        ("socket.getaddrinfo", ("blocked.invalid", 443, 0, 0, 0)),
    ):
        try:
            sys.audit(audit_event, *audit_args)
        except PermissionError:
            pass
        else:
            raise RuntimeError("Safe-test isolation self-check failed")
    # Empty CWD ensures BaseSettings cannot discover the repository .env.
    with tempfile.TemporaryDirectory(prefix="inboundcheck-safe-tests-") as empty_cwd:
        os.chdir(empty_cwd)
        sys.path.insert(0, str(BACKEND))
        # Some legacy tests incorrectly replace not-yet-imported installed modules
        # with MagicMock. Preload real declared dependencies before collection.
        import fastapi, httpx, pydantic, pydantic_settings, pydantic_core, supabase  # noqa: F401
        import pytest
        args = []
        for arg in sys.argv[1:]:
            if not arg.startswith("-") and (BACKEND / arg.split("::", 1)[0]).exists():
                arg = str(BACKEND / arg.split("::", 1)[0]) + ("::" + arg.split("::", 1)[1] if "::" in arg else "")
            args.append(arg)
        if not any(not arg.startswith("-") for arg in args):
            args.insert(0, str(BACKEND / "tests"))
        args += ["-c", str(BACKEND / "pytest.ini"), "--rootdir", str(BACKEND), "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "--ignore", str(BACKEND / "tests/test_staging_domain_audit_lifecycle.py")]
        print("SAFE RUN: test mode; project dotenv denied; external networking denied; live staging lifecycle excluded", flush=True)
        try:
            return pytest.main(args)
        finally:
            os.chdir(ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
