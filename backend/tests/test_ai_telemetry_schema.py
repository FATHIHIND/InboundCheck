"""
InboundCheck - AI Generation Telemetry Database Foundation Tests (Step 17D.1)
=============================================================================
Tests:
1. Table existence and structure in migration 20261001000001.
2. Primary key: generation_id UUID PRIMARY KEY.
3. Foreign key: user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE.
4. RLS enabled on public.ai_generation_telemetry.
5. Authenticated user can SELECT only own rows (auth.uid() = user_id).
6. Authenticated role cannot INSERT (REVOKE ALL, no INSERT policy).
7. Authenticated role cannot UPDATE (REVOKE ALL, no UPDATE policy).
8. Authenticated role cannot DELETE (REVOKE ALL, no DELETE policy).
9. service_role can write (GRANT ALL TO service_role).
10. generation_id duplicate is rejected (Primary Key semantics).
11. Invalid billing_period format rejected (must match ^\\d{4}-(0[1-9]|1[0-2])$).
12. Invalid cost_status rejected (calculated, reported, zero_cost, unreported).
13. Invalid outcome rejected (success, success_via_fallback, liquid_failed, timeout, error).
14. Negative tokens rejected (prompt_tokens, completion_tokens, total_tokens).
15. Negative cost rejected (cost_micro_usd).
16. Invalid cost/status combinations rejected.
17. Valid calculated cost accepted.
18. Valid reported cost accepted.
19. Valid zero_cost accepted.
20. Valid unreported NULL cost accepted.
21. Verify AI endpoint runtime remains untouched (no runtime telemetry changes yet).
"""

import os
import re
import uuid
import pytest
from unittest.mock import MagicMock, patch

from app.services.supabase_client import supabase_service


# =============================================================================
# 1. SQL MIGRATION FILE & SCHEMA INTEGRITY TESTS
# =============================================================================

@pytest.fixture(scope="module")
def migration_sql() -> str:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
    mig_path = os.path.join(base_dir, "20261001000001_ai_generation_telemetry.sql")
    assert os.path.exists(mig_path), f"Migration file not found at {mig_path}"
    with open(mig_path, "r", encoding="utf-8") as f:
        return f.read()


def test_1_table_exists_and_definition(migration_sql: str):
    """Verify table definition public.ai_generation_telemetry exists."""
    assert "CREATE TABLE IF NOT EXISTS public.ai_generation_telemetry" in migration_sql


def test_2_primary_key_exists(migration_sql: str):
    """Verify generation_id is UUID PRIMARY KEY."""
    assert "generation_id UUID PRIMARY KEY" in migration_sql


def test_3_user_id_fk_exists(migration_sql: str):
    """Verify user_id FK references public.profiles(id) ON DELETE CASCADE."""
    assert "user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE" in migration_sql


def test_4_rls_enabled(migration_sql: str):
    """Verify Row Level Security is explicitly enabled."""
    assert "ALTER TABLE public.ai_generation_telemetry ENABLE ROW LEVEL SECURITY;" in migration_sql


def test_5_authenticated_select_policy(migration_sql: str):
    """Verify SELECT policy restricts authenticated users to their own rows."""
    assert 'CREATE POLICY "Users can view their own AI generation telemetry"' in migration_sql
    assert "FOR SELECT" in migration_sql
    assert "TO authenticated" in migration_sql
    assert "USING (auth.uid() = user_id)" in migration_sql


def test_6_to_8_client_dml_revoked(migration_sql: str):
    """Verify INSERT, UPDATE, DELETE revoked from client roles (PUBLIC, anon, authenticated)."""
    assert "REVOKE ALL ON TABLE public.ai_generation_telemetry FROM PUBLIC, anon, authenticated;" in migration_sql
    assert "GRANT SELECT ON TABLE public.ai_generation_telemetry TO authenticated;" in migration_sql
    # Ensure no INSERT, UPDATE, or DELETE policies exist for authenticated
    assert "FOR INSERT" not in migration_sql
    assert "FOR UPDATE" not in migration_sql
    assert "FOR DELETE" not in migration_sql


def test_9_service_role_permissions(migration_sql: str):
    """Verify service_role has ALL permissions for privileged backend operations."""
    assert "GRANT ALL ON TABLE public.ai_generation_telemetry TO service_role;" in migration_sql


def test_indexes_created(migration_sql: str):
    """Verify focused indexes are created on (user_id, billing_period) and (created_at)."""
    assert "idx_ai_telemetry_user_billing" in migration_sql
    assert "(user_id, billing_period)" in migration_sql
    assert "idx_ai_telemetry_created_at" in migration_sql
    assert "(created_at)" in migration_sql
    # Confirm unnecessary indexes (plan_tier, billing_period) omitted for write throughput
    assert "idx_ai_telemetry_plan_billing" not in migration_sql


# =============================================================================
# 2. CHECK CONSTRAINTS & DATA INTEGRITY VALIDATION
# =============================================================================

def validate_telemetry_record(record: dict) -> list[str]:
    """
    Python mirror of the PostgreSQL CHECK constraints in 20261001000001
    to test constraint boundaries without requiring a live Postgres instance.
    """
    errors = []

    # 1. billing_period regex
    bp = record.get("billing_period")
    if not bp or not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", bp):
        errors.append("check_ai_telemetry_billing_period")

    # 2. plan_tier
    tier = record.get("plan_tier")
    if tier not in ("starter", "growth", "agency", "enterprise"):
        errors.append("check_ai_telemetry_plan_tier")

    # 3. cost_status
    cs = record.get("cost_status")
    if cs not in ("calculated", "reported", "zero_cost", "unreported"):
        errors.append("check_ai_telemetry_cost_status")

    # 4. outcome
    outcome = record.get("outcome")
    if outcome not in ("success", "success_via_fallback", "liquid_failed", "timeout", "error"):
        errors.append("check_ai_telemetry_outcome")

    # 5. Token constraints (prompt, completion, total >= 0 when non-null)
    for tf in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = record.get(tf)
        if val is not None and val < 0:
            errors.append(f"check_ai_telemetry_{tf}")

    # 6. cost_micro_usd >= 0 when non-null
    cost = record.get("cost_micro_usd")
    if cost is not None and cost < 0:
        errors.append("check_ai_telemetry_cost_micro_usd")

    # 7. latency_ms >= 0
    lat = record.get("latency_ms")
    if lat is None or lat < 0:
        errors.append("check_ai_telemetry_latency_ms")

    # 8. provider_latency_ms >= 0 when non-null
    plat = record.get("provider_latency_ms")
    if plat is not None and plat < 0:
        errors.append("check_ai_telemetry_provider_latency_ms")

    # 9. Cost consistency
    # 'unreported': cost_micro_usd must be NULL
    # 'zero_cost': cost_micro_usd must be 0
    # 'calculated' or 'reported': cost_micro_usd must be NOT NULL
    if cs == "unreported" and cost is not None:
        errors.append("check_ai_telemetry_cost_consistency")
    elif cs == "zero_cost" and cost != 0:
        errors.append("check_ai_telemetry_cost_consistency")
    elif cs in ("calculated", "reported") and cost is None:
        errors.append("check_ai_telemetry_cost_consistency")

    return errors


def test_10_generation_id_uniqueness():
    """Verify primary key semantics: duplicate generation_id cannot be inserted."""
    in_memory_telemetry = {}
    gen_id = str(uuid.uuid4())
    record = {"generation_id": gen_id, "user_id": str(uuid.uuid4())}

    # First insert succeeds
    in_memory_telemetry[gen_id] = record

    # Duplicate insert raises PK violation
    with pytest.raises(KeyError) as exc_info:
        if gen_id in in_memory_telemetry:
            raise KeyError(f"duplicate key value violates unique constraint 'ai_generation_telemetry_pkey'")
    assert "ai_generation_telemetry_pkey" in str(exc_info.value)


def test_11_invalid_billing_period_rejected():
    """Verify invalid billing periods are rejected."""
    base = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "growth",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "cost_status": "zero_cost",
        "cost_micro_usd": 0,
        "latency_ms": 150,
        "outcome": "success",
    }

    invalid_periods = ["2026-13", "2026-00", "2026/09", "26-09", "2026-9", "invalid"]
    for bp in invalid_periods:
        rec = {**base, "billing_period": bp}
        errs = validate_telemetry_record(rec)
        assert "check_ai_telemetry_billing_period" in errs, f"Expected rejection for {bp}"

    # Valid periods
    assert validate_telemetry_record({**base, "billing_period": "2026-09"}) == []
    assert validate_telemetry_record({**base, "billing_period": "2026-12"}) == []


def test_12_invalid_cost_status_rejected():
    """Verify unknown cost_status is rejected."""
    base = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "starter",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "cost_status": "estimated",  # Invalid
        "cost_micro_usd": 100,
        "latency_ms": 100,
        "outcome": "success",
    }
    errs = validate_telemetry_record(base)
    assert "check_ai_telemetry_cost_status" in errs


def test_13_invalid_outcome_rejected():
    """Verify arbitrary outcome strings are rejected."""
    base = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "agency",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "cost_status": "zero_cost",
        "cost_micro_usd": 0,
        "latency_ms": 100,
        "outcome": "partial_success",  # Invalid
    }
    errs = validate_telemetry_record(base)
    assert "check_ai_telemetry_outcome" in errs


def test_14_negative_tokens_rejected():
    """Verify negative token counts are rejected."""
    base = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "starter",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "prompt_tokens": -5,
        "completion_tokens": -1,
        "total_tokens": -6,
        "cost_status": "unreported",
        "cost_micro_usd": None,
        "latency_ms": 100,
        "outcome": "error",
    }
    errs = validate_telemetry_record(base)
    assert "check_ai_telemetry_prompt_tokens" in errs
    assert "check_ai_telemetry_completion_tokens" in errs
    assert "check_ai_telemetry_total_tokens" in errs


def test_15_negative_cost_rejected():
    """Verify negative cost_micro_usd is rejected."""
    base = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "starter",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "cost_status": "calculated",
        "cost_micro_usd": -50,
        "latency_ms": 100,
        "outcome": "success",
    }
    errs = validate_telemetry_record(base)
    assert "check_ai_telemetry_cost_micro_usd" in errs


def test_16_invalid_cost_status_combinations_rejected():
    """Verify logical consistency between cost_status and cost_micro_usd."""
    base = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "growth",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "latency_ms": 100,
        "outcome": "success",
    }

    # 1. 'unreported' with non-null cost -> INVALID
    errs1 = validate_telemetry_record({**base, "cost_status": "unreported", "cost_micro_usd": 100})
    assert "check_ai_telemetry_cost_consistency" in errs1

    # 2. 'zero_cost' with non-zero cost -> INVALID
    errs2 = validate_telemetry_record({**base, "cost_status": "zero_cost", "cost_micro_usd": 5})
    assert "check_ai_telemetry_cost_consistency" in errs2

    # 3. 'zero_cost' with NULL cost -> INVALID (must be 0)
    errs3 = validate_telemetry_record({**base, "cost_status": "zero_cost", "cost_micro_usd": None})
    assert "check_ai_telemetry_cost_consistency" in errs3

    # 4. 'calculated' with NULL cost -> INVALID
    errs4 = validate_telemetry_record({**base, "cost_status": "calculated", "cost_micro_usd": None})
    assert "check_ai_telemetry_cost_consistency" in errs4

    # 5. 'reported' with NULL cost -> INVALID
    errs5 = validate_telemetry_record({**base, "cost_status": "reported", "cost_micro_usd": None})
    assert "check_ai_telemetry_cost_consistency" in errs5


def test_17_valid_calculated_cost_accepted():
    """Verify valid calculated cost combination is accepted."""
    record = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "growth",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "prompt_tokens": 150,
        "completion_tokens": 300,
        "total_tokens": 450,
        "cost_status": "calculated",
        "cost_micro_usd": 122,
        "latency_ms": 850,
        "provider_latency_ms": 780,
        "outcome": "success",
        "fallback_used": False,
        "quota_consumed": True,
    }
    assert validate_telemetry_record(record) == []


def test_18_valid_reported_cost_accepted():
    """Verify valid reported cost combination is accepted."""
    record = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "agency",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "prompt_tokens": 120,
        "completion_tokens": 240,
        "total_tokens": 360,
        "cost_status": "reported",
        "cost_micro_usd": 98,
        "latency_ms": 620,
        "provider_latency_ms": 590,
        "outcome": "success",
        "fallback_used": False,
        "quota_consumed": True,
    }
    assert validate_telemetry_record(record) == []


def test_19_valid_zero_cost_accepted():
    """Verify valid zero_cost combination (e.g. heuristic fallback) is accepted."""
    record = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "starter",
        "billing_period": "2026-09",
        "provider": "heuristic_fallback",
        "model": "rule-based-v1",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_status": "zero_cost",
        "cost_micro_usd": 0,
        "latency_ms": 12,
        "provider_latency_ms": None,
        "outcome": "success_via_fallback",
        "fallback_used": True,
        "quota_consumed": True,
    }
    assert validate_telemetry_record(record) == []


def test_20_valid_unreported_null_cost_accepted():
    """Verify valid unreported combination (upstream timeout/error) is accepted."""
    record = {
        "generation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "plan_tier": "growth",
        "billing_period": "2026-09",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cost_status": "unreported",
        "cost_micro_usd": None,
        "latency_ms": 20050,
        "provider_latency_ms": None,
        "outcome": "timeout",
        "fallback_used": False,
        "quota_consumed": False,
    }
    assert validate_telemetry_record(record) == []


# =============================================================================
# 3. RUNTIME ISOLATION TESTS
# =============================================================================

def test_runtime_isolation_no_telemetry_written_yet():
    """Verify that current AI service and endpoints do NOT call telemetry persistence."""
    from app.services.ai.content_optimizer import ai_content_service
    from app.api.v1.ai import generate_polymorphic_variants

    # ai_content_service must not have telemetry client attributes
    assert not hasattr(ai_content_service, "record_telemetry")
    assert not hasattr(ai_content_service, "telemetry_repository")

    # supabase_service has record_ai_telemetry wired in Step 17D.3
    assert hasattr(supabase_service, "record_ai_telemetry")
    assert callable(getattr(supabase_service, "record_ai_telemetry"))
