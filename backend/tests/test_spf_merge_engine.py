"""
InboundCheck - SPF Conflict Resolution & Merge Engine Unit Tests
=================================================================
Tests:
1. Single SPF record no-op merge.
2. Multiple v=spf1 records deduplication (shops.shopify.com + sendgrid.net).
3. Lookup budget evaluation (10 vs 11 lookups boundary).
4. Cyclic include handling without infinite recursion.
5. Safety flags (safe_to_apply is False on lookup overflow, PTR, redirect, macro).
6. API endpoint POST /api/v1/dns/spf-merge-plan.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.dns.spf_merge_engine import SpfMergeEngine, spf_merge_engine
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_single_spf_record_merge():
    """Verify single clean SPF record produces an equivalent canonical proposed record."""
    engine = SpfMergeEngine()
    source = ["v=spf1 include:shops.shopify.com ip4:198.51.100.1 ~all"]

    with patch.object(engine, "_calculate_recursive_lookups", new_callable=AsyncMock) as mock_lookups:
        mock_lookups.return_value = (0, [], [])
        plan = await engine.create_plan(
            domain="brandstore.com",
            user_id="test-user-1",
            preferred_qualifier="~all",
            source_records=source,
        )

    assert plan.domain == "brandstore.com"
    assert len(plan.source_records) == 1
    assert "include:shops.shopify.com" in plan.proposed_record
    assert "ip4:198.51.100.1/32" in plan.proposed_record or "ip4:198.51.100.1" in plan.proposed_record
    assert plan.proposed_record.endswith("~all")
    assert plan.removed_duplicates == []
    assert plan.safe_to_apply is True
    assert plan.requires_manual_review is False
    assert plan.lookup_budget.status == "within_limit"


@pytest.mark.asyncio
async def test_multiple_spf_records_deduplication():
    """Verify deduplication of conflicting v=spf1 records (Shopify + SendGrid)."""
    engine = SpfMergeEngine()
    sources = [
        "v=spf1 include:shops.shopify.com ip4:192.0.2.1 ~all",
        "v=spf1 include:shops.shopify.com include:sendgrid.net ip4:192.0.2.1/32 -all",
    ]

    with patch.object(engine, "_calculate_recursive_lookups", new_callable=AsyncMock) as mock_lookups:
        mock_lookups.return_value = (0, [], [])
        plan = await engine.create_plan(
            domain="conflictedbrand.com",
            user_id="test-user-2",
            preferred_qualifier="~all",
            source_records=sources,
        )

    # Must detect multiple source records
    assert len(plan.source_records) == 2
    assert any(w.code == "RFC7208_MULTIPLE_RECORDS" for w in plan.warnings)

    # Must deduplicate include:shops.shopify.com and ip4
    assert len(plan.removed_duplicates) >= 1
    assert "include:shops.shopify.com" in plan.proposed_record
    assert "include:sendgrid.net" in plan.proposed_record
    # Only 1 occurrence of include:shops.shopify.com in proposed record
    assert plan.proposed_record.count("include:shops.shopify.com") == 1
    assert plan.proposed_record.endswith("~all")


@pytest.mark.asyncio
async def test_lookup_budget_boundary():
    """Verify lookup budget status: <= 10 is within_limit, >= 11 is over_limit."""
    engine = SpfMergeEngine()

    # 1. Exactly 10 lookups (10 includes)
    ten_includes = " ".join([f"include:provider{i}.com" for i in range(10)])
    source_10 = [f"v=spf1 {ten_includes} ~all"]

    with patch.object(engine, "_calculate_recursive_lookups", new_callable=AsyncMock) as mock_lookups:
        mock_lookups.return_value = (0, [], [])
        plan_10 = await engine.create_plan(
            domain="ten-lookups.com",
            user_id="test-user-3",
            source_records=source_10,
        )
    assert plan_10.lookup_budget.static_terms == 10
    assert plan_10.lookup_budget.status == "within_limit"
    assert plan_10.safe_to_apply is True

    # 2. 11 lookups (exceeding limit)
    eleven_includes = " ".join([f"include:provider{i}.com" for i in range(11)])
    source_11 = [f"v=spf1 {eleven_includes} ~all"]

    with patch.object(engine, "_calculate_recursive_lookups", new_callable=AsyncMock) as mock_lookups:
        mock_lookups.return_value = (0, [], [])
        plan_11 = await engine.create_plan(
            domain="eleven-lookups.com",
            user_id="test-user-3",
            source_records=source_11,
        )
    assert plan_11.lookup_budget.static_terms == 11
    assert plan_11.lookup_budget.status == "over_limit"
    assert plan_11.safe_to_apply is False
    assert plan_11.requires_manual_review is True
    assert any(w.code == "RFC7208_LOOKUP_LIMIT_EXCEEDED" for w in plan_11.warnings)


@pytest.mark.asyncio
async def test_cyclic_include_detection():
    """Verify circular SPF includes do not cause infinite recursion."""
    engine = SpfMergeEngine()

    # Mock resolver returning circular include: domainA -> domainB -> domainA
    def mock_resolve_side_effect(resolver, domain_name):
        d = domain_name.lower().rstrip(".")
        if d == "domaina.com":
            return ["v=spf1 include:domainb.com ~all"]
        elif d == "domainb.com":
            return ["v=spf1 include:domaina.com ~all"]
        return []

    with patch.object(engine.diagnostic_engine, "_resolve_txt", side_effect=mock_resolve_side_effect):
        plan = await engine.create_plan(
            domain="domaina.com",
            user_id="test-user-cyclic",
            source_records=["v=spf1 include:domainb.com ~all"],
        )

    # Should detect cycle without freezing or recursion error
    assert any(w.code == "SPF_CIRCULAR_INCLUDE" for w in plan.warnings)


@pytest.mark.asyncio
async def test_safety_flags_for_ptr_redirect_and_macros():
    """Verify safe_to_apply is False and requires_manual_review is True when PTR or redirect or macro is present."""
    engine = SpfMergeEngine()

    # 1. PTR mechanism
    plan_ptr = await engine.create_plan(
        domain="ptr-test.com",
        user_id="test-user-ptr",
        source_records=["v=spf1 ptr:mail.server.com ~all"],
    )
    assert plan_ptr.safe_to_apply is False
    assert plan_ptr.requires_manual_review is True
    assert any(w.code == "SPF_PTR_DEPRECATED" for w in plan_ptr.warnings)

    # 2. Redirect modifier
    plan_redirect = await engine.create_plan(
        domain="redirect-test.com",
        user_id="test-user-red",
        source_records=["v=spf1 redirect=_spf.example.com"],
    )
    assert plan_redirect.safe_to_apply is False
    assert plan_redirect.requires_manual_review is True
    assert any(w.code == "SPF_REDIRECT_MODIFIER" for w in plan_redirect.warnings)

    # 3. Macro syntax
    plan_macro = await engine.create_plan(
        domain="macro-test.com",
        user_id="test-user-macro",
        source_records=["v=spf1 exists:%{i}._spf.example.com ~all"],
    )
    assert plan_macro.safe_to_apply is False
    assert plan_macro.requires_manual_review is True
    assert any(w.code == "SPF_MACRO_DETECTED" for w in plan_macro.warnings)


@pytest.mark.asyncio
async def test_spf_merge_plan_api_endpoint():
    """Verify POST /api/v1/dns/spf-merge-plan HTTP API contract."""
    transport = ASGITransport(app=app)
    headers = auth_headers("test-user-merge-api")

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        res = await ac.post("/api/v1/dns/spf-merge-plan", json={
            "domain": "shopify.com",
            "preferred_qualifier": "~all"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["domain"] == "shopify.com"
        assert "plan_id" in data
        assert "source_records" in data
        assert "proposed_record" in data
        assert "lookup_budget" in data
        assert "safe_to_apply" in data
        assert "requires_manual_review" in data
        assert "warnings" in data
