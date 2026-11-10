"""Local source checks: no application imports, dotenv loading or SQL execution.

Inspects only Git-tracked content; reports filenames/rule names, never values.
Not a replacement for credential rotation, history scanning or dependency audits.
"""
from __future__ import annotations
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SECRET_RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "stripe-secret": re.compile(rb"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "aws-access-id": re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
}


def forbidden_path(name: str) -> bool:
    p = PurePosixPath(name.lower())
    return (any(part == ".env" or (part.startswith(".env.") and part != ".env.example") for part in p.parts)
            or p.suffix in {".pem", ".key", ".pfx", ".p12", ".keystore"}
            or p.name in {"credentials.json", "service-account.json", "service_account.json", "id_rsa", "id_ed25519", ".npmrc", ".pypirc"})


def inspect_files(root: Path, names: list[str]) -> list[str]:
    errors = []
    for name in names:
        if forbidden_path(name):
            errors.append(f"{name}: forbidden credential/dotenv path")
            continue  # Never read dotenv or private-key files.
        file = root / name
        if file.is_symlink():
            errors.append(f"{name}: tracked symlink requires review")
            continue
        if not file.is_file():
            continue
        data = file.read_bytes()
        for rule, pattern in SECRET_RULES.items():
            if pattern.search(data):
                errors.append(f"{name}: {rule}")
    return errors


def lock_errors(root: Path) -> list[str]:
    errors = []
    lock = root / "backend/requirements.lock"
    if not lock.is_file():
        return ["backend/requirements.lock: missing hash lock"]
    entries = {}
    logical = lock.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in logical.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)(?:\s*;[^#]+?)?\s+((?:--hash=sha256:[a-f0-9]{64}\s*)+)", line)
        if not match:
            errors.append("backend/requirements.lock: every dependency must be pinned and SHA256-hashed")
        else:
            entries[match[1].lower().replace("_", "-")] = match[2]
    for line in (root / "backend/requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)", line)
        if not match or entries.get(match[1].lower().replace("_", "-")) != match[2]:
            errors.append("backend/requirements.txt: direct requirements must match the hash lock")
    return errors


def main() -> int:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    names = tracked.decode("utf-8").split("\0")
    errors = inspect_files(ROOT, [n for n in names if n]) + lock_errors(ROOT)
    if errors:
        print("Release source safety checks failed:", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release source safety passed: tracked credential paths/content and backend hash pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
