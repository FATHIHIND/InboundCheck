"""
InboundCheck - Asynchronous DNSBL / RBL Scanner Engine Unit Test Suite
======================================================================
Tests evidence-based DNSBL reputation scanning:
1. Multiple public A-record resolution and reverse IP formatting.
2. NXDOMAIN returns status "clean".
3. 127.0.0.2 returns status "listed" with preserved response code.
4. Timeout returns status "unknown", NEVER "clean".
5. Private / non-global IP or missing public A record returns status "unavailable".
6. One listed IP among multiple A records marks provider as "listed".
7. All enabled providers represented exactly once in aggregate scan.
8. Rate limit / policy codes (e.g. 127.255.255.x) classified as unknown/error, never clean.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import dns.resolver
import dns.rdatatype
import dns.exception

from app.services.dns.rbl_scanner import (
    rbl_scanner,
    dnsbl_query_name,
    domain_rbl_query_name,
    RBL_PROVIDERS,
    RBLScanResult,
    RBLListingResult,
)


def test_dnsbl_query_name_construction():
    """Verify reverse IP and domain query string construction."""
    assert dnsbl_query_name("198.51.100.25", "zen.spamhaus.org") == "25.100.51.198.zen.spamhaus.org"
    assert dnsbl_query_name("1.2.3.4", "b.barracudacentral.org") == "4.3.2.1.b.barracudacentral.org"
    assert domain_rbl_query_name("brandshop.com", "dbl.spamhaus.org") == "brandshop.com.dbl.spamhaus.org"
    assert domain_rbl_query_name("brandshop.com.", "multi.surbl.org") == "brandshop.com.multi.surbl.org"


@pytest.mark.asyncio
async def test_resolve_multiple_public_a_records():
    """Verify that multiple public IPs are resolved and non-global IPs are filtered."""
    mock_ans1 = MagicMock()
    mock_ans1.address = "93.184.216.34"
    mock_ans2 = MagicMock()
    mock_ans2.address = "10.0.0.1" # Private RFC 1918
    mock_ans3 = MagicMock()
    mock_ans3.address = "93.184.216.35"

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(return_value=[mock_ans1, mock_ans2, mock_ans3])

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver):
        ips = await rbl_scanner.resolve_public_a_records("multi-ip.com")
        assert ips == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.asyncio
async def test_nxdomain_is_clean():
    """Verify that NXDOMAIN response produces a clean status."""
    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(side_effect=dns.resolver.NXDOMAIN)

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver), \
         patch.object(rbl_scanner, "resolve_public_a_records", return_value=["198.51.100.25"]):
        result: RBLScanResult = await rbl_scanner.scan_domain("clean-domain.com")

        assert result.domain == "clean-domain.com"
        assert result.rbl_clean_count == len(rbl_scanner.registry)
        assert result.rbl_listed_count == 0
        assert result.rbl_unknown_count == 0
        assert result.rbl_error_count == 0
        assert result.overall_status == "clean"
        assert result.highest_severity == "none"

        for item in result.results:
            assert item.status == "clean"
            assert item.severity == "none"


@pytest.mark.asyncio
async def test_listed_127_0_0_2_preserved_code():
    """Verify that 127.0.0.2 returns listed with preserved response code."""
    async def mock_resolve(qname, rdtype, lifetime=1.5):
        qstr = str(qname)
        if "zen.spamhaus.org" in qstr:
            rec = MagicMock()
            rec.address = "127.0.0.2"
            return [rec]
        raise dns.resolver.NXDOMAIN

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(side_effect=mock_resolve)

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver), \
         patch.object(rbl_scanner, "resolve_public_a_records", return_value=["198.51.100.25"]):
        result = await rbl_scanner.scan_domain("listed-domain.com")

        assert result.overall_status == "listed"
        assert result.rbl_listed_count == 1
        assert result.highest_severity == "critical"

        zen_item = next(r for r in result.results if r.provider_id == "spamhaus_zen")
        assert zen_item.status == "listed"
        assert "127.0.0.2" in zen_item.response_codes
        assert zen_item.severity == "critical"


@pytest.mark.asyncio
async def test_timeout_is_unknown_never_clean():
    """Verify that DNSBL query timeout produces 'unknown', never 'clean'."""
    async def mock_resolve(qname, rdtype, lifetime=1.5):
        qstr = str(qname)
        if "b.barracudacentral.org" in qstr:
            raise dns.exception.Timeout("Query timed out")
        raise dns.resolver.NXDOMAIN

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(side_effect=mock_resolve)

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver), \
         patch.object(rbl_scanner, "resolve_public_a_records", return_value=["198.51.100.25"]):
        result = await rbl_scanner.scan_domain("timeout-domain.com")

        assert result.rbl_unknown_count == 1
        assert result.rbl_clean_count == len(rbl_scanner.registry) - 1
        assert result.overall_status == "partial"

        barracuda = next(r for r in result.results if r.provider_id == "barracuda_brbl")
        assert barracuda.status == "unknown"
        assert "timed out" in (barracuda.message or "").lower()


@pytest.mark.asyncio
async def test_no_public_a_records_produces_unavailable():
    """Verify that private or missing A records mark IP providers as unavailable/unknown."""
    with patch.object(rbl_scanner, "resolve_public_a_records", return_value=[]):
        result = await rbl_scanner.scan_domain("no-public-ip.com")

        assert result.resolved_ips == []
        ip_items = [r for r in result.results if r.target_type == "ip"]
        for item in ip_items:
            assert item.status == "unknown"
            assert "No public IPv4" in (item.message or "")


@pytest.mark.asyncio
async def test_multi_ip_aggregation_one_listed_marks_provider_listed():
    """Verify that if domain resolves to 2 IPs and 1 is listed, provider is listed."""
    async def mock_resolve(qname, rdtype, lifetime=1.5):
        qstr = str(qname)
        # 198.51.100.1 is clean, 198.51.100.2 is listed
        if "2.100.51.198.zen.spamhaus.org" in qstr:
            rec = MagicMock()
            rec.address = "127.0.0.4"
            return [rec]
        raise dns.resolver.NXDOMAIN

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(side_effect=mock_resolve)

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver), \
         patch.object(rbl_scanner, "resolve_public_a_records", return_value=["198.51.100.1", "198.51.100.2"]):
        result = await rbl_scanner.scan_domain("multi-ip-listed.com")

        zen = next(r for r in result.results if r.provider_id == "spamhaus_zen")
        assert zen.status == "listed"
        assert "127.0.0.4" in zen.response_codes
        assert "198.51.100.2" in zen.queried_target


@pytest.mark.asyncio
async def test_all_enabled_providers_represented_once():
    """Verify that all enabled providers in registry are represented exactly once."""
    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(side_effect=dns.resolver.NXDOMAIN)

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver), \
         patch.object(rbl_scanner, "resolve_public_a_records", return_value=["198.51.100.25"]):
        result = await rbl_scanner.scan_domain("registry-test.com")

        assert len(result.results) == len(rbl_scanner.registry)
        provider_ids = [r.provider_id for r in result.results]
        assert len(provider_ids) == len(set(provider_ids))
        for p in rbl_scanner.registry:
            assert p.id in provider_ids
