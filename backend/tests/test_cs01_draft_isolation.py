"""
Guards for the CS-01 security-grants draft.

The draft must stay outside supabase/migrations/ so migration tooling cannot
execute it, and it must cover every SECURITY DEFINER function and mutable
search_path finding recorded by the Supabase advisors.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT = REPO_ROOT / "docs" / "remediation" / "drafts" / "CS01_security_grants_search_path_DRAFT.sql"
MIGRATIONS = REPO_ROOT / "supabase" / "migrations"


def _draft_text() -> str:
    return DRAFT.read_text(encoding="utf-8")


def test_draft_exists_outside_migrations_directory():
    assert DRAFT.is_file(), "CS-01 draft is missing"
    assert MIGRATIONS not in DRAFT.parents, "CS-01 draft must not live under supabase/migrations/"


def test_no_cs01_draft_file_is_placed_in_migrations():
    names = [p.name.lower() for p in MIGRATIONS.glob("*.sql")]
    assert not any("cs01" in n or "draft" in n for n in names), (
        "A CS-01 draft or placeholder must not be placed where migration tooling runs it"
    )


def test_draft_is_marked_as_not_a_migration():
    text = _draft_text()
    assert "DRAFT — NOT A MIGRATION. DO NOT APPLY." in text


def test_draft_revokes_definer_execute_for_anon_and_authenticated():
    text = _draft_text()
    for fn in ("handle_new_user", "protect_profile_billing_columns"):
        assert (
            f"REVOKE EXECUTE ON FUNCTION public.{fn}() FROM PUBLIC, anon, authenticated;" in text
        ), f"draft does not revoke EXECUTE for {fn}"


def test_draft_sets_explicit_search_path_for_mutable_functions():
    text = _draft_text()
    assert "SET search_path = public, pg_temp" in text
    for fn in ("update_updated_at_column", "set_updated_at", "increment_upload_count"):
        assert f"'{fn}'" in text, f"draft does not cover search_path for {fn}"


def test_draft_leaves_increment_upload_count_grant_as_explicit_decision():
    text = _draft_text()
    assert "DECISION REQUIRED" in text
    assert "REVOKE EXECUTE ON FUNCTION public.increment_upload_count()" not in text


def test_draft_includes_rollback_and_verification():
    text = _draft_text()
    assert "ROLLBACK" in text
    assert "VERIFICATION" in text
    assert "GRANT EXECUTE ON FUNCTION public.handle_new_user() TO PUBLIC;" in text
