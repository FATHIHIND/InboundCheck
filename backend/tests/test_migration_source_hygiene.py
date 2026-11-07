"""Guard against shell-escape artifacts in SQL migrations (BILL-14 / DB-7).

A PowerShell newline escape (backtick-n) was written literally into a PL/pgSQL
body in 20261106000002, which would abort the whole migration at apply time.
The existing pglast-based validator does not parse PL/pgSQL function bodies,
so this class of defect slipped past CI. PowerShell escapes have no legitimate
use in these SQL files.
"""
from pathlib import Path
import re

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
POWERSHELL_ESCAPE = re.compile(r"`[nrt0]")


def test_migrations_directory_exists():
    assert MIGRATIONS.is_dir(), MIGRATIONS


def test_no_powershell_escape_artifacts_in_migrations():
    offenders = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if POWERSHELL_ESCAPE.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()[:120]}")
    assert not offenders, "PowerShell escape artifacts found:\n" + "\n".join(offenders)
