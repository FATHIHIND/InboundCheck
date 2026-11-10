"""Runtime contract for the hash-locked dependency upgrade (slice S6.2).

These four tests are taken verbatim from PR #1's
backend/tests/test_release_gate_regression.py (the S6.2 part of that split file).
They are moved into this module because the original file loads the S0 release
scripts (scripts/validate_migration_sources.py, scripts/check_release_safety.py)
at import time, and those scripts arrive with the separate S0 slice. The S0 tests
stay in test_release_gate_regression.py and ship with S0.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docker_keeps_runtime_and_hashes_without_dropping_direct_extras():
    text = (ROOT / "backend/Dockerfile").read_text()
    assert "FROM python:3.11-slim" in text
    assert "COPY requirements.txt requirements.lock ./" in text
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock -r requirements.txt" in text
    assert "pip install --no-cache-dir -r requirements.txt" not in text


def test_portable_uvicorn_docker_command_and_direct_requirement():
    import json
    docker = (ROOT / "backend/Dockerfile").read_text()
    command = json.loads(next(line[4:] for line in docker.splitlines() if line.startswith("CMD ")))
    assert command[0:2] == ["uvicorn", "app.main:app"]
    assert command[command.index("--loop") + 1] == "asyncio"
    assert command[command.index("--http") + 1] == "h11"
    requirements = (ROOT / "backend/requirements.txt").read_text().splitlines()
    from packaging.requirements import Requirement
    uvicorn = next(Requirement(line) for line in requirements
                   if line.startswith("uvicorn"))
    assert str(uvicorn.specifier) == "==0.30.1"
    assert uvicorn.extras == {"standard"}
    assert sum(line.startswith("uvicorn") for line in requirements) == 1


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
