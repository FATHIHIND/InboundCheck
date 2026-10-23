"""
InboundCheck - Isolated Unit Tests for Staging Bootstrap & Isolation Guard
==========================================================================
Tests the fail-closed behavior of StagingIsolationGuard using mock/fake credentials.
Zero network calls or database connections are made during these tests.
"""

import os
import pytest
import tempfile
from pathlib import Path

from app.core.staging_guard import (
    StagingIsolationError,
    validate_staging_config,
    resolve_staging_env_path,
    parse_env_file,
    bootstrap_staging_environment,
    PROD_PROJECT_REF,
)


def test_rejects_empty_expected_ref():
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": "https://teststagingref12345.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "fake_service_key_for_unit_tests",
    }
    with pytest.raises(StagingIsolationError, match="expected_staging_ref must be explicitly provided"):
        validate_staging_config(config, "")


def test_rejects_non_staging_environment():
    config = {
        "ENVIRONMENT": "production",
        "SUPABASE_URL": "https://teststagingref12345.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "fake_service_key_for_unit_tests",
    }
    with pytest.raises(StagingIsolationError, match="ENVIRONMENT must be strictly 'staging'"):
        validate_staging_config(config, "teststagingref12345")


def test_rejects_production_project_ref():
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": f"https://{PROD_PROJECT_REF}.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "fake_service_key_for_unit_tests",
    }
    with pytest.raises(StagingIsolationError, match="CRITICAL ISOLATION BREACH"):
        validate_staging_config(config, PROD_PROJECT_REF)


def test_rejects_staging_ref_mismatch():
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": "https://anotherstagingref99.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "fake_service_key_for_unit_tests",
    }
    with pytest.raises(StagingIsolationError, match="does not match expected staging reference"):
        validate_staging_config(config, "expectedstagingref11")


def test_rejects_malformed_supabase_url():
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": "http://insecure-staging.example.com",
        "SUPABASE_SERVICE_ROLE_KEY": "fake_service_key_for_unit_tests",
    }
    with pytest.raises(StagingIsolationError, match="does not match expected staging reference"):
        validate_staging_config(config, "insecure-staging")


def test_rejects_missing_service_role_key():
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": "https://validstagingref1234.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "",
    }
    with pytest.raises(StagingIsolationError, match="SUPABASE_SERVICE_ROLE_KEY is missing"):
        validate_staging_config(config, "validstagingref1234")


def test_accepts_valid_staging_configuration():
    valid_ref = "validstagingref1234"
    config = {
        "ENVIRONMENT": "staging",
        "SUPABASE_URL": f"https://{valid_ref}.supabase.co",
        "SUPABASE_KEY": "fake_anon_key",
        "SUPABASE_SERVICE_ROLE_KEY": "fake_service_key",
    }
    is_valid, msg = validate_staging_config(config, valid_ref)
    assert is_valid is True
    assert valid_ref in msg


def test_bootstrap_staging_environment_loads_and_injects_safely(monkeypatch):
    valid_ref = "isolatedtestref7777"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".staging") as tmp:
        tmp.write(f"ENVIRONMENT=staging\n")
        tmp.write(f"SUPABASE_URL=https://{valid_ref}.supabase.co\n")
        tmp.write(f"SUPABASE_SERVICE_ROLE_KEY=fake_mock_service_role_key\n")
        tmp.write(f"SUPABASE_KEY=fake_mock_anon_key\n")
        tmp_path = tmp.name

    orig_env = dict(os.environ)
    try:
        # Clear any prior env var
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        res = bootstrap_staging_environment(
            expected_staging_ref=valid_ref,
            custom_env_path=tmp_path
        )
        assert res["status"] == "isolated"
        assert res["staging_ref"] == valid_ref
        assert Path(res["env_path"]).resolve() == Path(tmp_path).resolve()

        # Verify os.environ was populated
        assert os.environ["ENVIRONMENT"] == "staging"
        assert os.environ["SUPABASE_URL"] == f"https://{valid_ref}.supabase.co"
    finally:
        os.environ.clear()
        os.environ.update(orig_env)
        Path(tmp_path).unlink(missing_ok=True)
