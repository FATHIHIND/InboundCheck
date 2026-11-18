"""
Dependency regression test for GHSA-vvf4-9x63-8xvv (CVE-2026-128089):
dnspython < 2.9.2 allows excessive memory and CPU use.

The backend resolves user-supplied domains with dnspython, so the pinned version in
both requirements.txt and the hash lock must be at or above the fixed version, the
two files must agree, and the lock must carry exactly the verified PyPI digests.

This test reads the declaration files only; it does not depend on what is installed.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Minimum fixed versions for advisories that affected locked packages.
FIXED_MINIMUMS = {
    "dnspython": ("2.9.2", "GHSA-vvf4-9x63-8xvv"),
}

# SHA-256 digests published by PyPI for dnspython 2.9.2 (wheel and sdist),
# independently confirmed by hashing the downloaded files.
DNSPYTHON_2_9_2_DIGESTS = {
    "af15f7d385a6ae2fb35a796fde2138004c8c42c7389090e2addc83e3b3340fd8",  # dnspython-2.9.2-py3-none-any.whl
    "8d4d39a513e649d634004ce4d39ade2352efcea472a0247535a5c2d18a9d7ba9",  # dnspython-2.9.2.tar.gz
}


def _version_tuple(version: str):
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _requirements_pins():
    pins = {}
    for raw in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)", line)
        if match:
            pins[match[1].lower().replace("_", "-")] = match[2]
    return pins


def _lock_entries():
    entries = {}
    logical = (BACKEND / "requirements.lock").read_text(encoding="utf-8").replace("\\\r\n", " ").replace("\\\n", " ")
    for raw in logical.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)", line)
        if match:
            entries[match[1].lower().replace("_", "-")] = (match[2], set(re.findall(r"--hash=sha256:([a-f0-9]{64})", line)))
    return entries


def test_requirements_txt_pins_dnspython_at_or_above_the_fixed_version():
    pins = _requirements_pins()
    fixed, advisory = FIXED_MINIMUMS["dnspython"]
    assert "dnspython" in pins
    assert _version_tuple(pins["dnspython"]) >= _version_tuple(fixed), (
        f"dnspython {pins['dnspython']} is affected by {advisory}; require >= {fixed}"
    )


def test_hash_lock_pins_dnspython_at_or_above_the_fixed_version():
    entries = _lock_entries()
    fixed, advisory = FIXED_MINIMUMS["dnspython"]
    assert "dnspython" in entries
    version, _ = entries["dnspython"]
    assert _version_tuple(version) >= _version_tuple(fixed), (
        f"dnspython {version} in requirements.lock is affected by {advisory}; require >= {fixed}"
    )


def test_requirements_and_lock_agree_on_dnspython_version():
    assert _requirements_pins()["dnspython"] == _lock_entries()["dnspython"][0]


def test_lock_carries_exactly_the_verified_dnspython_2_9_2_digests():
    version, hashes = _lock_entries()["dnspython"]
    assert version == "2.9.2"
    assert hashes == DNSPYTHON_2_9_2_DIGESTS


def test_no_locked_package_is_below_its_recorded_fixed_minimum():
    entries = _lock_entries()
    for name, (fixed, advisory) in FIXED_MINIMUMS.items():
        assert name in entries, f"{name} missing from lock"
        assert _version_tuple(entries[name][0]) >= _version_tuple(fixed), f"{name} affected by {advisory}"
