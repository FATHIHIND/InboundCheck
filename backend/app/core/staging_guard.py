"""
InboundCheck - Staging Isolation Guard & Bootstrap Engine (Phase 18A.5M)
======================================================================
Strict fail-closed guard preventing any worker, script, or test from connecting
to the production Supabase database.

Rules:
1. Must execute BEFORE importing any app/worker modules or initializing SupabaseClient.
2. Must validate that ENVIRONMENT is strictly 'staging'.
3. Must validate that SUPABASE_URL exactly matches 'https://<expected_staging_ref>.supabase.co'.
4. Must reject production project ref 'tbjcldcoozvuvyipeonh'.
5. Must resolve .env.staging deterministically regardless of execution working directory.
6. Must never print or leak secret tokens or connection strings.
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

PROD_PROJECT_REF = "tbjcldcoozvuvyipeonh"


class StagingIsolationError(RuntimeError):
    """Raised when staging configuration violates isolation boundaries."""
    pass


def resolve_staging_env_path(custom_path: Optional[str] = None) -> Path:
    """
    Deterministically locate the .env.staging file across execution contexts:
    - Running from repository root
    - Running from backend/
    - Running from tests/
    """
    if custom_path:
        p = Path(custom_path).resolve()
        if not p.is_file():
            raise StagingIsolationError(f"Specified staging configuration file does not exist: {custom_path}")
        return p

    # Candidate locations in priority order
    repo_anchor = Path(__file__).resolve().parents[3] # repository root
    backend_anchor = Path(__file__).resolve().parents[2] # backend dir

    candidates = [
        Path.cwd() / "backend" / ".env.staging",
        Path.cwd() / ".env.staging",
        backend_anchor / ".env.staging",
        repo_anchor / "backend" / ".env.staging",
        repo_anchor / ".env.staging",
    ]

    for cand in candidates:
        if cand.is_file():
            return cand.resolve()

    raise StagingIsolationError(
        "Could not locate .env.staging. Ensure backend/.env.staging exists with valid staging credentials."
    )


def parse_env_file(filepath: Path) -> Dict[str, str]:
    """Parse a simple key=value environment file without executing external dependencies."""
    if not filepath.is_file():
        raise StagingIsolationError(f"Configuration file not found: {filepath}")

    env_vars: Dict[str, str] = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                clean_k = k.strip()
                clean_v = v.strip().strip("'\"")
                env_vars[clean_k] = clean_v
    return env_vars


def validate_staging_config(
    config: Dict[str, str],
    expected_staging_ref: str
) -> Tuple[bool, str]:
    """
    Perform strict fail-closed validation of staging configuration.
    Returns (True, message) or raises StagingIsolationError.
    """
    if not expected_staging_ref or not expected_staging_ref.strip():
        raise StagingIsolationError("expected_staging_ref must be explicitly provided and non-empty.")

    clean_ref = expected_staging_ref.strip().lower()

    # 1. Environment Marker Validation
    env = config.get("ENVIRONMENT", "").strip().lower()
    if env != "staging":
        raise StagingIsolationError(
            f"Isolation violation: ENVIRONMENT must be strictly 'staging', got: '{env}'."
        )

    # 2. Supabase URL Presence
    supabase_url = config.get("SUPABASE_URL", "").strip().lower()
    if not supabase_url:
        raise StagingIsolationError("Isolation violation: SUPABASE_URL is missing or empty.")

    # 3. Hard-Reject Production Reference
    if PROD_PROJECT_REF in supabase_url:
        raise StagingIsolationError(
            f"CRITICAL ISOLATION BREACH: SUPABASE_URL contains production reference '{PROD_PROJECT_REF}'! "
            "Execution halted immediately."
        )

    # 4. Strict Regex Match Against Expected Staging Reference
    expected_url = f"https://{clean_ref}.supabase.co"
    staging_pattern = rf"^https://{re.escape(clean_ref)}\.supabase\.co$"
    if not re.match(staging_pattern, supabase_url):
        raise StagingIsolationError(
            f"Isolation violation: SUPABASE_URL does not match expected staging reference '{clean_ref}'. "
            f"Expected '{expected_url}', got URL targeting a different host."
        )

    # 5. Mandatory Key Verification
    service_key = config.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not service_key:
        raise StagingIsolationError("Isolation violation: SUPABASE_SERVICE_ROLE_KEY is missing or empty.")

    return True, f"Staging isolation verified for project ref '{clean_ref}'."


def bootstrap_staging_environment(
    expected_staging_ref: str,
    custom_env_path: Optional[str] = None
) -> Dict[str, str]:
    """
    Safely bootstrap staging environment before any application or Supabase modules are imported:
    1. Resolves .env.staging
    2. Parses configuration
    3. Validates against staging reference and production reject rules
    4. Injects validated keys into os.environ
    """
    env_path = resolve_staging_env_path(custom_env_path)
    config = parse_env_file(env_path)

    # Validate
    validate_staging_config(config, expected_staging_ref)

    # Inject into os.environ so BaseSettings loads staging values
    for k, v in config.items():
        os.environ[k] = v

    return {
        "status": "isolated",
        "staging_ref": expected_staging_ref,
        "env_path": str(env_path),
    }
