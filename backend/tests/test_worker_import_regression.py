"""Regression coverage for the real failover worker lazy-import path (INV-01)."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_runner_can_import_real_failover_worker_without_live_configuration(tmp_path):
    """Import real dependencies in a fresh interpreter, never repository .env files.

    A pre-set stop event exercises the runner's lazy delegation without claiming
    work, querying a database, or dispatching notifications. No app modules are
    stubbed: the missing sanitizer import must fail this test before the fix.
    """
    backend_root = Path(__file__).resolve().parents[1]
    # Allow only platform/runtime essentials; never inherit application credentials,
    # PYTHONPATH, or pytest's process-global module/configuration modifications.
    platform_keys = {
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
        "TMPDIR", "LANG", "LC_ALL",
    }
    child_env = {
        key: value for key, value in os.environ.items()
        if key.upper() in platform_keys
    }
    child_env.update({"ENVIRONMENT": "test", "STAGING_MODE": "false"})
    script = textwrap.dedent(
        r'''
        import asyncio
        import ipaddress
        import os
        from pathlib import Path
        import sys

        sys.dont_write_bytecode = True
        sys.path.insert(0, sys.argv[1])

        # Windows asyncio may implement its internal socketpair over loopback.
        # Preserve the real socket APIs and permit only numeric loopback endpoints;
        # localhost DNS is safe here because the subsequent connect is checked too.
        def is_loopback_host(host, allow_localhost=False):
            if isinstance(host, bytes):
                try:
                    host = host.decode("ascii")
                except UnicodeDecodeError:
                    return False
            if not isinstance(host, str):
                return False
            if allow_localhost and host.lower().rstrip(".") == "localhost":
                return True
            try:
                return ipaddress.ip_address(host).is_loopback
            except ValueError:
                return False

        def guard_network(event, args):
            if event in {"socket.connect", "socket.sendto", "socket.sendmsg"}:
                address = args[1] if len(args) > 1 else None
                if not (
                    isinstance(address, tuple) and address
                    and is_loopback_host(address[0])
                ):
                    raise AssertionError("Non-loopback socket access is forbidden in worker import regression")
            elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
                host = args[0] if args else None
                if not is_loopback_host(host, allow_localhost=True):
                    raise AssertionError("Non-loopback DNS is forbidden in worker import regression")

        sys.addaudithook(guard_network)

        # The empty temporary cwd prevents Settings(env_file=".env") from finding
        # repository secrets. Also reject explicit dotenv file reads fail-closed.
        def deny_dotenv_reads(event, args):
            if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
                name = Path(os.fsdecode(args[0])).name.lower()
                if name == ".env" or name.startswith(".env."):
                    raise AssertionError("Dotenv reads are forbidden in worker import regression")

        sys.addaudithook(deny_dotenv_reads)

        from app.workers import runner
        assert "app.workers.failover_worker" not in sys.modules
        stop_event = asyncio.Event()
        stop_event.set()
        asyncio.run(runner.run_failover_worker(stop_event=stop_event))

        from app.workers import failover_worker
        from app.core.config import settings
        from app.services.failover.omnichannel_service import sanitize_log_message
        from app.services.supabase_client import supabase_service

        assert settings.ENVIRONMENT == "test"
        assert settings.SUPABASE_URL == ""
        assert settings.SUPABASE_SERVICE_ROLE_KEY == ""
        assert settings.SUPABASE_KEY == ""
        assert settings.TELEGRAM_BOT_TOKEN == ""
        assert settings.STRIPE_SECRET_KEY == ""
        assert supabase_service._client is None
        assert failover_worker.sanitize_log_message is sanitize_log_message
        assert failover_worker.canonicalize_event_type("hard-bounce") == "hard_bounce"

        # Preserve the existing Telegram sanitizer rather than a weaker replacement.
        raw = "bot123456:regression_token whsec_testsecret shpat_testsecret Bearer test.jwt.token"
        cleaned = failover_worker.sanitize_log_message(raw)
        for secret in ("123456:regression_token", "whsec_testsecret", "shpat_testsecret", "test.jwt.token"):
            assert secret not in cleaned
        assert "[REDACTED" in cleaned
        assert failover_worker.sanitize_log_message("Shop #42") == "Shop #42"
        print("worker-import-regression-ok")
        '''
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(backend_root)],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, (
        f"Real worker import failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "worker-import-regression-ok" in result.stdout
