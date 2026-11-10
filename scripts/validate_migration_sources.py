"""Validate migration SOURCE only. Never import the ledger script or contact a DB.

pglast==8.7 is a CI verifier, not an application runtime dependency. Parsing
checks PostgreSQL syntax, not PL/pgSQL function bodies, ACL behavior or DB state.
"""
from __future__ import annotations
import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"([0-9]{14})_([a-z0-9_]+)\.sql")


def read_manifest(source: Path) -> tuple[tuple[str, str], ...]:
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    values = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "CANONICAL_MIGRATIONS" for t in targets):
            values.append(ast.literal_eval(node.value))
    if len(values) != 1:
        raise ValueError("exactly one literal CANONICAL_MIGRATIONS is required")
    rows = values[0]
    if not isinstance(rows, (tuple, list)) or not rows:
        raise ValueError("canonical manifest must not be empty")
    if any(not isinstance(row, (tuple, list)) or len(row) != 2 or
           not all(isinstance(v, str) for v in row) or
           not NAME.fullmatch(f"{row[0]}_{row[1]}.sql") for row in rows):
        raise ValueError("invalid canonical manifest entry")
    rows = tuple(tuple(row) for row in rows)
    if len({row[0] for row in rows}) != len(rows) or list(rows) != sorted(rows):
        raise ValueError("manifest versions must be unique and ordered")
    return rows


def validate(root: Path, parse_sql) -> int:
    rows = read_manifest(root / "scripts/reconcile_migration_ledger.py")
    directory = root / "supabase/migrations"
    files = sorted(directory.iterdir())
    if any(p.is_symlink() or not p.is_file() or not NAME.fullmatch(p.name) for p in files):
        raise ValueError("migration directory must contain only regular canonical SQL files")
    physical = tuple(NAME.fullmatch(p.name).groups() for p in files)
    if physical != rows:
        raise ValueError("physical migration inventory differs from literal canonical manifest")
    for file in files:
        text = file.read_text(encoding="utf-8-sig")
        try:
            if not parse_sql(text):
                raise ValueError("empty SQL")
        except Exception:
            # Do not echo SQL or parser exception text (could include a secret).
            raise ValueError(f"PostgreSQL source parse failed: {file.name}") from None
    return len(files)


def main() -> int:
    try:
        from pglast import parse_sql
        count = validate(ROOT, parse_sql)
    except ImportError:
        print("SOURCE validation requires the explicit verifier pglast==8.7", file=sys.stderr)
        return 1
    except (ValueError, OSError, SyntaxError):
        print("Migration SOURCE validation failed; inspect inventory/manifest/syntax locally", file=sys.stderr)
        return 1
    print(f"SOURCE ONLY: {count} canonical migrations parsed; no SQL executed; no DB contacted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
