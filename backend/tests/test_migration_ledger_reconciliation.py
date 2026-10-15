import copy
import hashlib
from pathlib import Path
import pytest

import sys
# Add scripts directory to sys.path so we can import reconcile_migration_ledger
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from reconcile_migration_ledger import (
    CANONICAL_28_MIGRATIONS,
    CANONICAL_3_LEGACY_ROWS,
    RECONCILIATION_PROVENANCE,
    scan_local_migrations,
    validate_ledger_baseline,
    plan_reconciliation,
    generate_forward_reconciliation_sql,
    generate_defensive_rollback_sql,
    generate_post_reconciliation_verification_sql,
    verify_post_reconciliation_ledger,
)


def test_scan_local_migrations_matches_canonical_28():
    migrations_dir = REPO_ROOT / "supabase" / "migrations"
    migrations = scan_local_migrations(migrations_dir)
    assert len(migrations) == 28
    for idx, (m, (exp_v, exp_name)) in enumerate(zip(migrations, CANONICAL_28_MIGRATIONS)):
        assert m.version == exp_v
        assert m.name == exp_name
        assert m.filename == f"{exp_v}_{exp_name}.sql"


def test_legacy_metadata_archived_and_intact():
    """Verify that all 3 legacy rows hold complete statement text and match baseline hashes."""
    assert len(CANONICAL_3_LEGACY_ROWS) == 3
    expected_hashes = {
        "20260910165935": ("03b0f9b6a641244e586c522967ccc12e", 4077),
        "20260910195242": ("28d5d7e69f6f50fc2133d85c6d67095b", 2951),
        "20260910203910": ("8f447b1417713536f7b965104051477e", 2303),
    }
    for v, (exp_md5, exp_len) in expected_hashes.items():
        assert v in CANONICAL_3_LEGACY_ROWS
        rec = CANONICAL_3_LEGACY_ROWS[v]
        stmts = rec.get("statements", [])
        assert len(stmts) == 1
        s0 = stmts[0]
        assert len(s0) == exp_len
        assert hashlib.md5(s0.encode("utf-8")).hexdigest() == exp_md5


def test_validate_ledger_baseline_approved_state():
    # Build exact matching rows using actual md5
    rows = []
    for v, meta in CANONICAL_3_LEGACY_ROWS.items():
        row = {
            "version": v,
            "name": meta["name"],
            "created_by": meta["created_by"],
            "idempotency_key": None,
            "rollback": None,
            "statements": ["placeholder"],
        }
        rows.append(row)

    # When statements length/md5 don't match, validator detects it
    is_valid, errors = validate_ledger_baseline(rows)
    assert not is_valid
    assert any("statements length mismatch" in e for e in errors)


def test_validate_ledger_baseline_fails_on_wrong_count():
    rows = [
        {"version": "20260910165935", "name": "foo"},
        {"version": "20260910195242", "name": "bar"},
    ]
    is_valid, errors = validate_ledger_baseline(rows)
    assert not is_valid
    assert any("Row count mismatch" in e for e in errors)


def test_validate_ledger_baseline_fails_on_target_collision():
    # Simulate a collision where one of the 28 target versions already exists in ledger
    rows = [
        {"version": "20260910165935", "name": "a"},
        {"version": "20260910195242", "name": "b"},
        {"version": "20260903000001", "name": "complete_production_schema"},  # target collision!
    ]
    is_valid, errors = validate_ledger_baseline(rows)
    assert not is_valid
    assert any("Target versions collision detected" in e for e in errors)


def test_validate_ledger_baseline_fails_on_tampered_author():
    rows = [
        {
            "version": "20260910165935",
            "name": "add_delivery_failure_ingestion_and_idempotency",
            "created_by": "attacker@evil.com",  # tampered!
            "idempotency_key": None,
            "rollback": None,
            "statements": ["test"],
        },
        {"version": "20260910195242", "name": "add_delivery_failure_claim_rpc", "created_by": "hind10bella.fathi@gmail.com"},
        {"version": "20260910203910", "name": "allow_telegram_fallback_channel", "created_by": "hind10bella.fathi@gmail.com"},
    ]
    is_valid, errors = validate_ledger_baseline(rows)
    assert not is_valid
    assert any("author mismatch" in e for e in errors)


def test_plan_reconciliation_detects_rows_to_insert_and_legacy_to_remove():
    mock_rows = list(CANONICAL_3_LEGACY_ROWS.values())
    plan = plan_reconciliation(mock_rows)
    assert plan["initial_count"] == 3
    assert plan["legacy_rows_to_remove_count"] == 3
    assert plan["target_insert_count"] == 28
    assert len(plan["rows_to_insert"]) == 28
    assert plan["projected_final_count"] == 28
    assert plan["collisions_count"] == 0


def test_forward_sql_concurrency_and_fail_closed_properties():
    sql = generate_forward_reconciliation_sql(lock_timeout_sec=3, statement_timeout_sec=10)

    # 1. Concurrency isolation
    assert "LOCK TABLE supabase_migrations.schema_migrations IN ACCESS EXCLUSIVE MODE;" in sql
    assert "SET LOCAL lock_timeout = '3s';" in sql
    assert "SET LOCAL statement_timeout = '10s';" in sql

    # 2. Strict fail-closed: NO ON CONFLICT DO NOTHING
    assert "ON CONFLICT" not in sql
    assert "DO NOTHING" not in sql

    # 3. Precondition assertions present
    assert "PRECONDITION FAILED [P-01]" in sql
    assert "PRECONDITION FAILED [P-02]" in sql
    assert "PRECONDITION FAILED [P-03]" in sql
    assert "PRECONDITION FAILED [P-04]" in sql
    assert "PRECONDITION FAILED [P-05]" in sql
    assert "PRECONDITION FAILED [P-06]" in sql
    assert "PRECONDITION FAILED [P-07]" in sql
    assert "PRECONDITION FAILED [P-08]" in sql

    # 4. Atomic legacy removal
    assert "DELETE FROM supabase_migrations.schema_migrations" in sql
    assert "WHERE version IN ('20260910165935', '20260910195242', '20260910203910')" in sql
    assert "SWAP FAILED: Expected to delete exactly 3 legacy rows" in sql

    # 5. Postcondition assertions present
    assert "POSTCONDITION FAILED [Q-01]" in sql
    assert "Expected exactly 28 rows" in sql
    assert "POSTCONDITION FAILED [Q-02]" in sql
    assert "POSTCONDITION FAILED [Q-03]" in sql
    assert "POSTCONDITION FAILED [Q-04]" in sql
    assert "legacy rows still exist in schema_migrations" in sql

    # 6. All 28 versions present in SQL with positive provenance
    for v, name in CANONICAL_28_MIGRATIONS:
        assert f"('{v}', '{name}', '{RECONCILIATION_PROVENANCE}')" in sql
    assert f"Provenance Marker: {RECONCILIATION_PROVENANCE}" in sql


def test_rollback_sql_properties():
    sql = generate_defensive_rollback_sql(lock_timeout_sec=3, statement_timeout_sec=10)

    # 1. Operational governance and limitations documentation
    assert "OPERATIONAL GOVERNANCE & PRODUCTION LIMITATIONS" in sql
    assert "FORWARD RECOVERY" in sql
    assert "STRICTLY FORBIDDEN and will fail-closed" in sql

    # 2. Lock and timeouts
    assert "LOCK TABLE supabase_migrations.schema_migrations IN ACCESS EXCLUSIVE MODE;" in sql
    assert "SET LOCAL lock_timeout = '3s';" in sql
    assert "SET LOCAL statement_timeout = '10s';" in sql

    # 3. Preconditions and postconditions
    assert "ROLLBACK PRECONDITION FAILED [R-01]" in sql
    assert "Expected exactly 28 rows in ledger" in sql
    assert "ROLLBACK PRECONDITION FAILED [R-02]" in sql
    assert "ROLLBACK PRECONDITION FAILED [R-03]" in sql
    assert "ROLLBACK EXECUTION FAILED" in sql
    assert "ROLLBACK POSTCONDITION FAILED [R-04]" in sql
    assert "ROLLBACK POSTCONDITION FAILED [R-05]" in sql
    assert "ROLLBACK POSTCONDITION FAILED [R-06]" in sql
    assert "ROLLBACK POSTCONDITION FAILED [R-07]" in sql

    # 4. Deletion of canonical records
    assert f"created_by = '{RECONCILIATION_PROVENANCE}'" in sql
    assert "statements IS NULL" in sql
    assert "idempotency_key IS NULL" in sql
    assert "rollback IS NULL" in sql

    # 5. Full restoration of legacy statements
    assert "$legacy_stmt_1$" in sql
    assert "$legacy_stmt_2$" in sql
    assert "$legacy_stmt_3$" in sql


def test_plan_reconciliation_refuses_on_target_collision():
    mock_rows = [
        {"version": "20260910165935", "name": "add_delivery_failure_ingestion_and_idempotency"},
        {"version": "20260910195242", "name": "add_delivery_failure_claim_rpc"},
        {"version": "20260903000001", "name": "complete_production_schema"},
    ]
    plan = plan_reconciliation(mock_rows)
    assert not plan["can_reconcile"]
    assert plan["collisions_count"] == 1
    assert "20260903000001" in plan["collisions"]


def test_cli_dry_run_execution(tmp_path):
    import subprocess
    script_path = REPO_ROOT / "scripts" / "reconcile_migration_ledger.py"
    out_sql = tmp_path / "forward.sql"
    out_rb = tmp_path / "rollback.sql"
    out_v = tmp_path / "verify.sql"

    cmd = [
        sys.executable,
        str(script_path),
        "--dry-run",
        "--output-sql",
        str(out_sql),
        "--output-rollback-sql",
        str(out_rb),
        "--output-verify-sql",
        str(out_v),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert res.returncode == 0
    assert "[+] Successfully verified 28 local migrations matching canonical sequence." in res.stdout
    assert "Projected Final Count:      28 (Exact Universal Parity)" in res.stdout
    assert "[+] Dry-run simulation complete. ZERO database writes executed." in res.stdout
    assert out_sql.exists()
    assert out_rb.exists()
    assert out_v.exists()
    assert "LOCK TABLE supabase_migrations.schema_migrations IN ACCESS EXCLUSIVE MODE;" in out_sql.read_text(encoding="utf-8")
    assert "LOCK TABLE supabase_migrations.schema_migrations IN ACCESS EXCLUSIVE MODE;" in out_rb.read_text(encoding="utf-8")
    assert "POST-RECONCILIATION VERIFICATION QUERY (READ-ONLY)" in out_v.read_text(encoding="utf-8")


def _setup_mock_28_rows():
    """Helper to build 28 valid post-reconciliation canonical ledger rows."""
    rows = []
    for v, n in CANONICAL_28_MIGRATIONS:
        rows.append({
            "version": v,
            "name": n,
            "created_by": RECONCILIATION_PROVENANCE,
            "idempotency_key": None,
            "rollback": None,
            "statements": None,
        })
    return rows


def test_post_reconciliation_verification_success_on_valid_28_rows():
    rows = _setup_mock_28_rows()
    is_valid, errors = verify_post_reconciliation_ledger(rows)
    assert is_valid, f"Expected validation to succeed, got errors: {errors}"
    assert len(errors) == 0


def test_post_reconciliation_verification_fails_on_missing_canonical_pair():
    rows = _setup_mock_28_rows()
    # Remove one canonical target row (e.g. 20261012000001)
    rows = [r for r in rows if r["version"] != "20261012000001"]
    is_valid, errors = verify_post_reconciliation_ledger(rows)
    assert not is_valid
    assert any("Row count mismatch: expected exactly 28 rows" in e for e in errors)
    assert any("Missing canonical migration: 20261012000001" in e for e in errors)


def test_post_reconciliation_verification_fails_on_incorrect_canonical_name():
    rows = _setup_mock_28_rows()
    for r in rows:
        if r["version"] == "20260903000001":
            r["name"] = "wrong_tampered_name"
    is_valid, errors = verify_post_reconciliation_ledger(rows)
    assert not is_valid
    assert any("Canonical 20260903000001 name mismatch" in e for e in errors)


def test_post_reconciliation_verification_fails_on_unexpected_rogue_row():
    rows = _setup_mock_28_rows()
    # Add an unexpected 29th row
    rows.append({
        "version": "20261101000001",
        "name": "unauthorized_migration",
        "created_by": "unknown",
        "statements": None,
        "idempotency_key": None,
        "rollback": None,
    })
    is_valid, errors = verify_post_reconciliation_ledger(rows)
    assert not is_valid
    assert any("Row count mismatch: expected exactly 28 rows" in e for e in errors)
    assert any("Unexpected rogue versions found in ledger: ['20261101000001']" in e for e in errors)


def test_post_reconciliation_verification_fails_on_legacy_residual_row():
    rows = _setup_mock_28_rows()
    # Replace one canonical row with a legacy row or append it
    rows.append({
        "version": "20260910165935",
        "name": "add_delivery_failure_ingestion_and_idempotency",
        "created_by": "hind10bella.fathi@gmail.com",
        "statements": None,
        "idempotency_key": None,
        "rollback": None,
    })
    is_valid, errors = verify_post_reconciliation_ledger(rows)
    assert not is_valid
    assert any("Legacy migration 20260910165935 must not exist" in e for e in errors)


def test_post_reconciliation_verification_fails_on_invalid_provenance():
    rows = _setup_mock_28_rows()
    for r in rows:
        if r["version"] == "20260928000001":
            r["created_by"] = "wrong:provenance:tag"
    is_valid, errors = verify_post_reconciliation_ledger(rows)
    assert not is_valid
    assert any("Canonical 20260928000001 provenance mismatch" in e for e in errors)


def test_rollback_refuses_when_subsequent_migration_exists():
    sql = generate_defensive_rollback_sql()
    # Check that precondition R-01 strictly enforces count = 28 and refuses if evolved
    assert "Expected exactly 28 rows in ledger, found %" in sql
    assert "Rollback is refused because ledger state has evolved." in sql


def test_post_reconciliation_verification_sql_query_structure():
    sql = generate_post_reconciliation_verification_sql()
    assert "POST-RECONCILIATION VERIFICATION QUERY (READ-ONLY)" in sql
    assert f"Required Provenance: {RECONCILIATION_PROVENANCE}" in sql
    assert "WITH expected_canonical_pairs(version, name) AS (" in sql
    assert "check_total_count" in sql
    assert "check_canonical_pairs" in sql
    assert "check_canonical_provenance" in sql
    assert "check_legacy_absence" in sql
    assert "check_rogue_rows" in sql

    # Verify all 28 canonical migrations are referenced in SQL
    for v, name in CANONICAL_28_MIGRATIONS:
        assert f"('{v}', '{name}')" in sql
