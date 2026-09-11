"""
InboundCheck - Safe Remote Asset HTTP Fetcher & SSRF Defense Unit Tests
========================================================================
Tests:
1. URL Policy validation (scheme, userinfo, fragment, IP literals, internal hosts).
2. Safe DNS resolution & Anti-SSRF private/metadata IP rejection.
3. Socket IP pinning and Anti-rebinding defense.
4. Oversized body streaming termination cutoff at 500 KB.
5. Redirect loops and HTTPS-to-HTTP downgrade rejection.
6. API endpoint POST /api/v1/dns/verify-remote-asset.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.security.url_policy import UrlPolicy, UrlPolicyViolation
from app.services.security.safe_dns_resolver import SafeDnsResolver, DnsSecurityViolation
from app.services.security.safe_http_fetcher import SafeHttpFetcher
from tests.conftest import auth_headers


def test_url_policy_validation_rules():
    """Verify strict URL validation filters out malicious or invalid schemes and hostnames."""
    # 1. Plain HTTP prohibited
    with pytest.raises(UrlPolicyViolation) as exc_http:
        UrlPolicy.validate_and_normalize("http://example.com/logo.svg")
    assert exc_http.value.code == "SCHEME_NOT_ALLOWED"

    # 2. Userinfo prohibited
    with pytest.raises(UrlPolicyViolation) as exc_user:
        UrlPolicy.validate_and_normalize("https://admin:secret@example.com/logo.svg")
    assert exc_user.value.code == "USERINFO_PROHIBITED"

    # 3. Fragment prohibited
    with pytest.raises(UrlPolicyViolation) as exc_frag:
        UrlPolicy.validate_and_normalize("https://example.com/logo.svg#section")
    assert exc_frag.value.code == "FRAGMENT_PROHIBITED"

    # 4. IP literal host prohibited
    with pytest.raises(UrlPolicyViolation) as exc_ip:
        UrlPolicy.validate_and_normalize("https://127.0.0.1/logo.svg")
    assert exc_ip.value.code == "IP_LITERAL_PROHIBITED"

    # 5. Local or internal hostnames prohibited
    with pytest.raises(UrlPolicyViolation) as exc_loc:
        UrlPolicy.validate_and_normalize("https://localhost/logo.svg")
    assert "BLOCKED" in exc_loc.value.code

    with pytest.raises(UrlPolicyViolation) as exc_tld:
        UrlPolicy.validate_and_normalize("https://corp.internal/logo.svg")
    assert exc_tld.value.code == "INTERNAL_TLD_BLOCKED"

    # 6. Valid HTTPS URL passes
    norm_url, host, port = UrlPolicy.validate_and_normalize("https://cdn.brandstore.com/assets/bimi.svg")
    assert norm_url == "https://cdn.brandstore.com/assets/bimi.svg"
    assert host == "cdn.brandstore.com"
    assert port == 443


def test_safe_dns_resolver_ssrf_rejection():
    """Verify resolver rejects private, loopback, and cloud metadata IPs."""
    # 1. Cloud metadata IP 169.254.169.254
    assert SafeDnsResolver.is_ip_restricted("169.254.169.254") is True
    # 2. Loopback 127.0.0.1
    assert SafeDnsResolver.is_ip_restricted("127.0.0.1") is True
    # 3. RFC 1918 10.0.0.5, 192.168.1.1, 172.16.0.1
    assert SafeDnsResolver.is_ip_restricted("10.0.0.5") is True
    assert SafeDnsResolver.is_ip_restricted("192.168.1.1") is True
    assert SafeDnsResolver.is_ip_restricted("172.20.10.1") is True
    # 4. Carrier Grade NAT 100.64.0.1
    assert SafeDnsResolver.is_ip_restricted("100.64.0.1") is True
    # 5. Public IP is allowed
    assert SafeDnsResolver.is_ip_restricted("93.184.216.34") is False

    # Resolution test with mock returning restricted IP
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
        with pytest.raises(DnsSecurityViolation) as exc_meta:
            SafeDnsResolver.resolve_pinned_ip("metadata.target.com")
        assert exc_meta.value.code == "RESTRICTED_IP_BLOCKED"


@pytest.mark.asyncio
async def test_safe_http_fetcher_oversized_stream_cutoff():
    """Verify streaming response aborts immediately when payload exceeds 500 KB limit."""
    fetcher = SafeHttpFetcher(max_bytes=500 * 1024)

    # Mock DNS resolution to public IP
    with patch.object(SafeDnsResolver, "resolve_pinned_ip", return_value="93.184.216.34"):
        # Mock streaming response providing 600 KB in 60KB chunks
        chunk = b"A" * 60_000

        async def mock_aiter_bytes(chunk_size=8192):
            for _ in range(10):  # 10 * 60,000 = 600,000 bytes > 512,000 bytes
                yield chunk

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/svg+xml"}
        mock_resp.aiter_bytes = mock_aiter_bytes

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            res = await fetcher.fetch("https://cdn.brandstore.com/huge-logo.svg", asset_type="bimi_logo")

    assert res.fetch_status == "rejected"
    assert res.failure_code == "PAYLOAD_TOO_LARGE"
    assert res.content_length_bytes > 500 * 1024


@pytest.mark.asyncio
async def test_safe_http_fetcher_redirect_security():
    """Verify fetcher blocks redirect loops and rejects HTTPS-to-HTTP downgrades."""
    fetcher = SafeHttpFetcher(max_redirects=3)

    # 1. HTTPS-to-HTTP Downgrade test
    with patch.object(SafeDnsResolver, "resolve_pinned_ip", return_value="93.184.216.34"):
        mock_resp_downgrade = MagicMock()
        mock_resp_downgrade.status_code = 302
        mock_resp_downgrade.headers = {"Location": "http://insecure.example.com/logo.svg"}

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp_downgrade)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            res = await fetcher.fetch("https://cdn.example.com/logo.svg")

    assert res.fetch_status == "rejected"
    assert res.failure_code == "HTTPS_DOWNGRADE_PROHIBITED"

    # 2. Redirect loop test
    with patch.object(SafeDnsResolver, "resolve_pinned_ip", return_value="93.184.216.34"):
        mock_resp_loop = MagicMock()
        mock_resp_loop.status_code = 301
        mock_resp_loop.headers = {"Location": "https://cdn.example.com/logo.svg"}  # redirects to itself

        mock_stream_loop = MagicMock()
        mock_stream_loop.__aenter__ = AsyncMock(return_value=mock_resp_loop)
        mock_stream_loop.__aexit__ = AsyncMock(return_value=None)

        mock_client_loop = AsyncMock()
        mock_client_loop.stream = MagicMock(return_value=mock_stream_loop)
        mock_client_loop.__aenter__.return_value = mock_client_loop
        mock_client_loop.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client_loop):
            res_loop = await fetcher.fetch("https://cdn.example.com/logo.svg")

    assert res_loop.fetch_status == "rejected"
    assert res_loop.failure_code == "REDIRECT_LOOP"


@pytest.mark.asyncio
async def test_verify_remote_asset_api_endpoint():
    """Verify POST /api/v1/dns/verify-remote-asset HTTP endpoint contracts."""
    transport = ASGITransport(app=app)
    headers = auth_headers("test-user-asset-api")

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        # 1. Verify with explicit valid URL (mocked fetch)
        with patch.object(SafeDnsResolver, "resolve_pinned_ip", return_value="93.184.216.34"):
            svg_content = b"<svg xmlns='http://www.w3.org/2000/svg'><circle r='10'/></svg>"

            async def mock_aiter(chunk_size=8192):
                yield svg_content

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"Content-Type": "image/svg+xml"}
            mock_resp.aiter_bytes = mock_aiter

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = AsyncMock()
            mock_client.stream = MagicMock(return_value=mock_ctx)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                res = await ac.post("/api/v1/dns/verify-remote-asset", json={
                    "domain": "shopify.com",
                    "asset_type": "bimi_logo",
                    "url": "https://cdn.shopify.com/bimi-logo.svg"
                })

            assert res.status_code == 200
            data = res.json()
            assert data["domain"] == "shopify.com"
            assert data["asset_type"] == "bimi_logo"
            assert data["fetch_status"] == "verified"
            assert data["pinned_ip"] == "93.184.216.34"
            assert data["content_length_bytes"] == len(svg_content)
            assert data["content_sha256"] is not None

        # 2. Verify SSRF rejection on restricted hostname
        res_ssrf = await ac.post("/api/v1/dns/verify-remote-asset", json={
            "domain": "127.0.0.1",
            "asset_type": "bimi_logo",
            "url": "https://127.0.0.1/logo.svg"
        })
        assert res_ssrf.status_code == 400
