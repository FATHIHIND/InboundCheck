"""Phase 5 security boundaries, using only local ASGI transports and generated keys."""
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request

from app.core.config import settings
from app.core.encryption import EncryptionKeyMissingError, get_fernet_cipher
from app.core.request_body import read_body_with_limit
from app.core.trusted_hosts import get_allowed_hosts


@pytest.mark.parametrize('environment', ['production', 'prod', 'staging', 'stage', 'preview', ''])
@pytest.mark.parametrize('key', ['', '   ', 'not-a-valid-key'])
def test_nonlocal_encryption_requires_valid_explicit_key(monkeypatch, environment, key):
    monkeypatch.setattr(settings, 'ENVIRONMENT', environment)
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', key)
    monkeypatch.setattr(settings, 'STAGING_MODE', False)
    monkeypatch.setenv('STAGING_MODE', 'false')
    with pytest.raises(EncryptionKeyMissingError):
        get_fernet_cipher()


@pytest.mark.parametrize('setting_flag,env_flag', [(True, 'false'), (False, 'true')])
def test_staging_flags_disable_development_key(monkeypatch, setting_flag, env_flag):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'development')
    monkeypatch.setattr(settings, 'STAGING_MODE', setting_flag)
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', '')
    monkeypatch.setenv('STAGING_MODE', env_flag)
    with pytest.raises(EncryptionKeyMissingError):
        get_fernet_cipher()


def test_explicit_existing_key_remains_ciphertext_compatible_across_modes(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', key)
    monkeypatch.setattr(settings, 'STAGING_MODE', False)
    monkeypatch.setenv('STAGING_MODE', 'false')
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'production')
    ciphertext = get_fernet_cipher().encrypt(b'local-regression-credential')
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'staging')
    assert get_fernet_cipher().decrypt(ciphertext) == b'local-regression-credential'


def test_only_explicit_local_mode_keeps_existing_development_cipher(monkeypatch):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'test')
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', '')
    monkeypatch.setattr(settings, 'STAGING_MODE', False)
    monkeypatch.setenv('STAGING_MODE', 'false')
    ciphertext = get_fernet_cipher().encrypt(b'local-only')
    assert get_fernet_cipher().decrypt(ciphertext) == b'local-only'


def host_config(environment='production', hosts=None, staging=False):
    return SimpleNamespace(ENVIRONMENT=environment, ALLOWED_HOSTS=hosts or [], STAGING_MODE=staging)


@pytest.mark.parametrize('host', ['*', '*.up.railway.app', '*.vercel.app', 'https://api.example.test', 'api.example.test/path', 'api.example.test:443', ''])
def test_host_allowlist_rejects_wildcards_and_non_host_values(monkeypatch, host):
    monkeypatch.delenv('RAILWAY_PUBLIC_DOMAIN', raising=False)
    with pytest.raises(ValueError):
        get_allowed_hosts(host_config(hosts=[host]))


def test_host_allowlist_requires_explicit_deployment_hostname(monkeypatch):
    monkeypatch.delenv('RAILWAY_PUBLIC_DOMAIN', raising=False)
    with pytest.raises(ValueError):
        get_allowed_hosts(host_config())
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN', 'specific-service.up.railway.app')
    assert get_allowed_hosts(host_config()) == ['specific-service.up.railway.app']


@pytest.mark.asyncio
async def test_host_header_rejected_even_with_trusted_forwarded_host(monkeypatch):
    monkeypatch.delenv('RAILWAY_PUBLIC_DOMAIN', raising=False)
    local_app = FastAPI()
    local_app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_allowed_hosts(host_config(hosts=['api.example.test'])))
    @local_app.get('/health')
    async def health():
        return {'status': 'ok'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local_app), base_url='https://api.example.test') as client:
        assert (await client.get('/health')).status_code == 200
        rejected = await client.get('/health', headers={'host': 'attacker.invalid', 'x-forwarded-host': 'api.example.test'})
        assert rejected.status_code == 400


def request_with_chunks(chunks, headers=()):
    position = {'read': 0}
    async def receive():
        index = position['read']
        position['read'] += 1
        if index >= len(chunks):
            raise AssertionError('Reader consumed beyond the supplied body')
        return {'type': 'http.request', 'body': chunks[index], 'more_body': index < len(chunks) - 1}
    scope = {'type': 'http', 'method': 'POST', 'path': '/', 'headers': list(headers)}
    return Request(scope, receive), position


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [(), ((b'content-length', b'1'),)])
async def test_overlimit_stream_stops_before_reading_remaining_chunks(headers):
    request, position = request_with_chunks([b'abc', b'def', b'never-consume'], headers)
    with pytest.raises(HTTPException) as exc:
        await read_body_with_limit(request, max_bytes=5)
    assert exc.value.status_code == 413
    assert position['read'] == 2


@pytest.mark.asyncio
async def test_signature_bytes_preserved_at_exact_limit():
    request, _ = request_with_chunks([b' {"x":', b' 1}\n'])
    assert await read_body_with_limit(request, max_bytes=10) == b' {"x": 1}\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('length', [b'-1', b'garbage', b'1,2', b' 3', b'+3'])
async def test_invalid_declared_lengths_rejected_before_consumption(length):
    request, position = request_with_chunks([b'abc'], ((b'content-length', length),))
    with pytest.raises(HTTPException) as exc:
        await read_body_with_limit(request)
    assert exc.value.status_code == 400
    assert position['read'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/api/v1/billing/webhook', '/api/v1/shopify/webhooks/orders', '/api/v1/shopify/webhooks/customers/data_request', '/webhook/delivery-failure/postmark'])
async def test_provider_ingress_caps_chunked_body_before_verification(path):
    from app.main import app
    read = []
    async def chunks():
        for index in range(3):
            read.append(index)
            yield b'x' * 700_000
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(path, content=chunks())
    assert response.status_code == 413
    assert read == [0, 1]


def test_missing_agent_router_credentials_remain_disabled(monkeypatch):
    from app.services.ai.provider import DisabledLLMProvider
    from app.services.ai.content_optimizer import AIContentOptimizer
    monkeypatch.setattr(settings, 'AGENT_ROUTER_ENABLED', True)
    monkeypatch.setattr(settings, 'AGENT_ROUTER_API_KEY', '')
    monkeypatch.setattr(settings, 'LLM_API_KEY', '')
    assert isinstance(AIContentOptimizer().provider, DisabledLLMProvider)


def test_unconfigured_shopify_hmac_remains_fail_closed(monkeypatch):
    from app.services.shopify.shopify_service import shopify_service
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(shopify_service, 'api_secret', '')
    assert shopify_service.verify_webhook_hmac(b'{}', 'forged') is False


@pytest.mark.asyncio
async def test_extremely_large_declared_length_is_rejected_without_conversion_error():
    request, position = request_with_chunks([b''], ((b'content-length', b'9' * 5000),))
    with pytest.raises(HTTPException) as exc:
        await read_body_with_limit(request)
    assert exc.value.status_code == 413
    assert position['read'] == 0


def test_unknown_stripe_key_is_not_partially_logged(monkeypatch, caplog):
    from app.core.env_guard import validate_runtime_environment
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'test')
    monkeypatch.setattr(settings, 'STRIPE_SECRET_KEY', 'sensitive-prefix-regression-value')
    validate_runtime_environment()
    assert 'sensitive-prefix-regression-value' not in caplog.text
    assert 'sensiti' not in caplog.text
    assert 'UNKNOWN_KEY_PREFIX' in caplog.text


def test_container_health_probe_uses_loopback_with_exact_configured_host():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'healthcheck.py'
    spec = importlib.util.spec_from_file_location('container_healthcheck_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    request = module.health_request({'ALLOWED_HOSTS': '["api.example.test"]'})
    assert request.full_url == 'http://127.0.0.1:8000/health'
    assert request.get_header('Host') == 'api.example.test'
    assert module.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://external.invalid') is None
    fallback = module.health_request({'RAILWAY_PUBLIC_DOMAIN': 'service.up.railway.app'})
    assert fallback.get_header('Host') == 'service.up.railway.app'


def test_notification_config_read_outage_aborts_before_any_write(monkeypatch):
    from unittest.mock import Mock
    from app.services.failover.omnichannel_service import TelegramAlertService
    from app.services.supabase_client import supabase_service, DatabaseUnavailableError
    service = TelegramAlertService()
    def unavailable(_user):
        raise DatabaseUnavailableError('Local injected read outage')
    monkeypatch.setattr(service, 'get_config', unavailable)
    save = Mock()
    monkeypatch.setattr(supabase_service, 'save_failover_config', save)
    monkeypatch.setattr(supabase_service, 'save_alert_config', save)
    with pytest.raises(DatabaseUnavailableError):
        service.update_config('local-fault-test-tenant', {'is_enabled': True})
    save.assert_not_called()
