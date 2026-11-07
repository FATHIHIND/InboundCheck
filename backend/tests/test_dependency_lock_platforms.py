"""Platform-lock source regressions; execute through scripts/safe_backend_tests.py."""
from importlib.metadata import requires
from pathlib import Path
import re

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]


def lock_entries():
    text = (ROOT / 'backend/requirements.lock').read_text(encoding='utf-8')
    result = {}
    for raw in text.replace('\\\n', ' ').splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        requirement = Requirement(raw.split('--hash=', 1)[0].strip())
        hashes = re.findall(r'--hash=sha256:([a-f0-9]{64})', raw)
        assert hashes, requirement.name
        assert len(requirement.specifier) == 1
        assert next(iter(requirement.specifier)).operator == '=='
        result[canonicalize_name(requirement.name)] = (requirement, set(hashes))
    return result


def environment(system, python, implementation='CPython'):
    env = default_environment()
    env.update(sys_platform=system, python_version=python,
               python_full_version=python + '.0',
               platform_python_implementation=implementation,
               implementation_name='pypy' if implementation == 'PyPy' else 'cpython',
               extra='standard')
    return env


@pytest.mark.parametrize('system,implementation,expected', [
    ('linux', 'CPython', True), ('darwin', 'CPython', True),
    ('win32', 'CPython', False), ('cygwin', 'CPython', False),
    ('linux', 'PyPy', False),
])
@pytest.mark.parametrize('python', ['3.11', '3.12'])
def test_uvloop_pin_matches_uvicorn_platform_marker(system, implementation, expected, python):
    entry, _ = lock_entries()['uvloop']
    assert str(entry.specifier) == '==0.23.0'
    assert entry.marker is not None
    assert entry.marker.evaluate(environment(system, python, implementation)) is expected


def test_uvloop_has_verified_linux_and_macos_wheel_and_sdist_hashes():
    # Downloaded bytes were SHA256-checked against official PyPI 0.23.0 metadata.
    # CPython 3.11/3.12 Linux glibc x86_64/aarch64; macOS universal2/x86_64; sdist.
    expected = {
        'ab17b3a8aa754be0de0e397f7b95f13b14e56f077a4c6ae295e3d4afd199b325',
        '8fcd721113260ffb5e38bf14a8725b17d431f34209f7d1c7005b667946e630b3',
        '090865d8ce7a03986755a3ce711b7dd0d4b44eb14ab74368b717f3fad1180208',
        'f7548ede3ee908cfabc0d068106e303a9a2d811af959cdf6ab85676344cedcda',
        '24c58ae4a83e93a04c504bcc678125e36a0bfc44af928ad69444880c60f187a5',
        '0efdd55bddbd36bb2fcb842d64c0d5f6407c6958c68088cc25df8c09edc5b5fd',
        '93935ab27b6eaef4c3e5489aebc84284f0644592f7ab516df60ee1b27eaf5eb3',
        '4448e9124537620f9c25d004c227bb5104440b58955c19bbd312d910af919a63',
        '28d160f51ab4da3b187063652e643dea6831072add4adc1e6d62afbe73b6be27',
    }
    assert expected <= lock_entries()['uvloop'][1]


@pytest.mark.parametrize('python', ['3.11', '3.12'])
@pytest.mark.parametrize('system', ['linux', 'darwin', 'win32'])
def test_every_active_uvicorn_standard_dependency_is_pinned_and_hashed(system, python):
    entries = lock_entries()
    env = environment(system, python)
    for raw in requires('uvicorn') or []:
        dependency = Requirement(raw)
        if dependency.marker and not dependency.marker.evaluate(env):
            continue
        locked, hashes = entries[canonicalize_name(dependency.name)]
        assert hashes
        version = next(iter(locked.specifier)).version
        assert version in dependency.specifier
        assert locked.marker is None or locked.marker.evaluate(env)


def test_uvicorn_standard_extras_are_explicit_and_complete():
    # Modern FastAPI no longer implicitly installs uvicorn[standard]. Keep the
    # runtime extras explicit, rather than losing uvloop on Linux on upgrade.
    direct = [Requirement(line) for line in
              (ROOT / 'backend/requirements.txt').read_text().splitlines()
              if line.strip() and not line.startswith('#')]
    uvicorn_direct = next(item for item in direct
                          if canonicalize_name(item.name) == 'uvicorn')
    assert uvicorn_direct.extras == {'standard'}
    uvicorn, _ = lock_entries()['uvicorn']
    assert str(uvicorn.specifier) == '==0.30.1'
    docker = (ROOT / 'backend/Dockerfile').read_text()
    assert 'pip install --no-cache-dir --require-hashes -r requirements.lock -r requirements.txt' in docker
