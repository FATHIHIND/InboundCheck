"""
Regression tests: the backend must never use the public anon key
(SUPABASE_KEY) as a database service credential.

Root cause: SUPABASE_SERVICE_ROLE_KEY was resolved as
`SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY` in the API runtime guard
(app/core/env_guard.py) and in the Supabase client initialiser
(app/services/supabase_client.py). In production, a missing service-role key
therefore passed validation and built a client with the public anon key.
The worker guard already requires SUPABASE_SERVICE_ROLE_KEY specifically.
"""

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.env_guard import validate_runtime_environment
from app.services import supabase_client as sc

ANON_KEY = "public-anon-key-0123456789abcdef"
SERVICE_KEY = "service-role-key-0123456789abcdef"
PROJECT_URL = "https://secureproject.supabase.co"


def test_api_guard_rejects_anon_key_used_as_service_key():
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(settings, "SUPABASE_JWT_SECRET", "jwt-secret-0123456789abcdef0123456789"), \
         patch.object(settings, "STRIPE_SECRET_KEY", ""):
        with pytest.raises(RuntimeError) as exc_info:
            validate_runtime_environment()
        assert "SUPABASE_SERVICE_ROLE_KEY is unconfigured or placeholder" in str(exc_info.value)


def test_client_init_refuses_anon_key_in_production():
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(sc, "create_client") as create_client_mock:
        with pytest.raises(sc.DatabaseUnavailableError):
            sc.SupabaseService()
        create_client_mock.assert_not_called()


def test_client_init_in_development_never_uses_anon_key():
    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", ""), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(sc, "create_client") as create_client_mock:
        sc.SupabaseService()  # development falls back to in-memory persistence
        create_client_mock.assert_not_called()


def test_client_init_uses_service_role_key_when_configured():
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(sc, "create_client") as create_client_mock:
        sc.SupabaseService()
        create_client_mock.assert_called_once()
        assert create_client_mock.call_args.args[1] == SERVICE_KEY


PLACEHOLDER_KEY = "your_service_role_key_dummy"


def test_t1_api_guard_rejects_placeholder_service_key_in_production():
    """T1: the startup guard fails closed on a placeholder service-role key in production."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", PLACEHOLDER_KEY), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(settings, "SUPABASE_JWT_SECRET", "jwt-secret-0123456789abcdef0123456789"), \
         patch.object(settings, "STRIPE_SECRET_KEY", ""):
        with pytest.raises(RuntimeError) as exc_info:
            validate_runtime_environment()
        assert "SUPABASE_SERVICE_ROLE_KEY is unconfigured or placeholder" in str(exc_info.value)


def test_t2_client_refuses_placeholder_service_key_in_production():
    """T2: the database client never initialises with a placeholder key in production."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", PLACEHOLDER_KEY), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(sc, "create_client") as create_client_mock:
        with pytest.raises(sc.DatabaseUnavailableError):
            sc.SupabaseService()
        create_client_mock.assert_not_called()


def test_t3_client_never_initialises_with_placeholder_key_in_development():
    """T3: in development a placeholder key selects in-memory persistence, never a client."""
    with patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "STAGING_MODE", False), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", PLACEHOLDER_KEY), \
         patch.object(settings, "SUPABASE_KEY", ANON_KEY), \
         patch.object(sc, "create_client") as create_client_mock:
        svc = sc.SupabaseService()
        create_client_mock.assert_not_called()
        assert svc._client is None


def test_t4_positive_control_real_key_still_initialises_client():
    """T4: a real, non-placeholder service-role key still initialises the client."""
    real_key = "eyJhbGciOi-real-service-role-0123456789abcdef"
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "SUPABASE_URL", PROJECT_URL), \
         patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", real_key), \
         patch.object(sc, "create_client") as create_client_mock:
        sc.SupabaseService()
        create_client_mock.assert_called_once()
        assert create_client_mock.call_args.args[1] == real_key
