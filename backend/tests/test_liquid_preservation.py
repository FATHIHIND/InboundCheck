"""
InboundCheck - Liquid Tag Extraction & Preservation Safety Tests
================================================================
Phase 2.4B Step 2: Verification of Shopify Liquid tag extraction and
strict preservation validation for email template copy optimization.
"""

import pytest
from app.services.ai.content_optimizer import (
    extract_liquid_tags,
    validate_liquid_preservation,
    ai_content_service,
)


def test_extract_liquid_tags_single_output_tag():
    """Verify extraction of standard {{ ... }} variable expression."""
    text = "Thank you for your purchase! Order #{{ order.name }} is confirmed."
    tags = extract_liquid_tags(text)
    assert tags == {"{{ order.name }}"}


def test_extract_liquid_tags_control_tag():
    """Verify extraction of {% ... %} logic and control tags."""
    text = "{% if customer.has_account %}Welcome back!{% endif %}"
    tags = extract_liquid_tags(text)
    assert tags == {"{% if customer.has_account %}", "{% endif %}"}


def test_extract_liquid_tags_multiple_tags():
    """Verify extraction of multiple mixed output and control tags across text."""
    text = (
        "<h1>Hi {{ customer.first_name }}</h1>"
        "<p>Your order #{{ order.name }} totaling {{ order.total_price }} is on the way.</p>"
        "{% if order.cancelled %}<p>Note: cancelled</p>{% endif %}"
        "<a href='{{ checkout.order_status_url }}'>Track order</a>"
    )
    tags = extract_liquid_tags(text)
    expected = {
        "{{ customer.first_name }}",
        "{{ order.name }}",
        "{{ order.total_price }}",
        "{% if order.cancelled %}",
        "{% endif %}",
        "{{ checkout.order_status_url }}",
    }
    assert tags == expected


def test_extract_liquid_tags_duplicate_tags():
    """Verify duplicate occurrences of the same Liquid tag collapse into a unique set."""
    text = (
        "Order {{ order.name }} has been processed. "
        "Reference number: {{ order.name }}. "
        "Questions about {{ order.name }}? Contact us."
    )
    tags = extract_liquid_tags(text)
    assert tags == {"{{ order.name }}"}


def test_extract_liquid_tags_empty_or_no_tags():
    """Verify that templates without Liquid tags, empty strings, or None return empty set."""
    assert extract_liquid_tags("Ordinary non-Liquid email body text.") == set()
    assert extract_liquid_tags("") == set()
    assert extract_liquid_tags(None) == set()


def test_validate_liquid_preservation_exact_match_succeeds():
    """Verify that a variant containing all original Liquid tags verbatim passes validation."""
    original_tags = {"{{ order.name }}", "{{ customer.first_name }}", "{{ checkout.order_status_url }}"}
    variant_body = (
        "<p>Hello {{ customer.first_name }},</p>"
        "<p>We have shipped order #{{ order.name }}.</p>"
        "<p>Follow tracking updates at {{ checkout.order_status_url }}.</p>"
    )
    assert validate_liquid_preservation(original_tags, variant_body) is True


def test_validate_liquid_preservation_missing_tag_fails():
    """Verify that omitting even one original Liquid tag causes validation to fail."""
    original_tags = {"{{ order.name }}", "{{ customer.first_name }}", "{{ checkout.order_status_url }}"}
    # Variant is missing {{ checkout.order_status_url }}
    variant_body = (
        "<p>Hello {{ customer.first_name }},</p>"
        "<p>Your order #{{ order.name }} is ready for pickup.</p>"
    )
    assert validate_liquid_preservation(original_tags, variant_body) is False


def test_validate_liquid_preservation_modified_tag_fails():
    """Verify that altering or rewriting a Liquid tag causes validation to fail."""
    original_tags = {"{{ order.name }}"}

    # 1. Renamed tag variable
    assert validate_liquid_preservation(original_tags, "Order #{{ order.id }} confirmed") is False

    # 2. Altered whitespace inside tag
    assert validate_liquid_preservation(original_tags, "Order #{{order.name}} confirmed") is False

    # 3. Translated or substituted to placeholder
    assert validate_liquid_preservation(original_tags, "Order #[ORDER_NAME] confirmed") is False


def test_validate_liquid_preservation_malformed_partial_tag_fails():
    """Verify that truncated or unclosed Liquid syntax does not pass validation."""
    original_tags = {"{{ order.name }}"}

    # Missing closing brace
    assert validate_liquid_preservation(original_tags, "Order #{{ order.name } confirmed") is False

    # Missing opening brace
    assert validate_liquid_preservation(original_tags, "Order #{ order.name }} confirmed") is False

    # Completely corrupted syntax
    assert validate_liquid_preservation(original_tags, "Order #% order.name % confirmed") is False


def test_validate_liquid_preservation_empty_tags_unaffected():
    """Verify that non-Liquid text with zero extracted tags returns True."""
    assert validate_liquid_preservation(set(), "Plain email text with no variables") is True
    assert validate_liquid_preservation(set(), "") is True


def test_validate_liquid_preservation_empty_or_none_variant_fails():
    """Verify that an empty or None variant fails when original tags were required."""
    original_tags = {"{{ order.name }}"}
    assert validate_liquid_preservation(original_tags, "") is False
    assert validate_liquid_preservation(original_tags, None) is False


def test_ai_content_service_static_methods():
    """Verify that AIContentOptimizer methods delegate properly to standalone helpers."""
    text = "Hi {{ customer.name }}, thanks for order {{ order.name }}."
    tags = ai_content_service.extract_liquid_tags(text)
    assert tags == {"{{ customer.name }}", "{{ order.name }}"}
    assert ai_content_service.validate_liquid_preservation(tags, text) is True
    assert ai_content_service.validate_liquid_preservation(tags, "Hi Friend, thanks.") is False


# =============================================================================
# Step 3 Pipeline Integration Regression Tests (Scenarios A through G)
# =============================================================================

@pytest.mark.asyncio
async def test_pipeline_liquid_preservation_valid_variant_accepted():
    """Scenario A: Original template with Liquid tags + valid variant containing all tags -> accepted."""
    original_body = "<p>Hi {{ customer.first_name }}, order #{{ order.name }} confirmed.</p>"
    candidates = [
        {
            "variant_id": "v1_valid",
            "variant_name": "Valid Variant",
            "subject": "Order #{{ order.name }}",
            "body_html": "<p>Greetings {{ customer.first_name }}! We have received order #{{ order.name }}.</p>",
            "estimated_spam_risk": 2,
            "rationale": "Preserves all tags."
        }
    ]
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Order #{{ order.name }}",
        body_content=original_body,
        candidate_variants=candidates
    )
    assert len(res) == 1
    assert res[0]["variant_id"] == "v1_valid"


@pytest.mark.asyncio
async def test_pipeline_liquid_preservation_missing_tag_rejected():
    """Scenario B: Variant missing even one required Liquid tag is rejected."""
    original_body = "<p>Hi {{ customer.first_name }}, order #{{ order.name }} totaling {{ order.total_price }}.</p>"
    candidates = [
        {
            "variant_id": "v_missing_total",
            "variant_name": "Incomplete Variant",
            "subject": "Order receipt",
            # Missing {{ order.total_price }}
            "body_html": "<p>Greetings {{ customer.first_name }}! Order #{{ order.name }} is confirmed.</p>",
            "estimated_spam_risk": 2,
            "rationale": "Missing total price tag."
        }
    ]
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Order receipt",
        body_content=original_body,
        candidate_variants=candidates
    )
    assert len(res) == 0


@pytest.mark.asyncio
async def test_pipeline_liquid_preservation_modified_tag_rejected():
    """Scenario C: Variant with modified or renamed Liquid tag is rejected."""
    original_body = "<p>Your order #{{ order.name }} is ready.</p>"
    candidates = [
        {
            "variant_id": "v_modified",
            "variant_name": "Renamed Tag Variant",
            "subject": "Order update",
            "body_html": "<p>Your order #{{ order.id }} is ready.</p>",
            "estimated_spam_risk": 2,
            "rationale": "Tag was altered."
        }
    ]
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Order update",
        body_content=original_body,
        candidate_variants=candidates
    )
    assert len(res) == 0


@pytest.mark.asyncio
async def test_pipeline_liquid_preservation_corrupted_syntax_rejected():
    """Scenario D: Variant with partially corrupted Liquid syntax is rejected."""
    original_body = "<p>Your order #{{ order.name }} is confirmed.</p>"
    candidates = [
        {
            "variant_id": "v_corrupted",
            "variant_name": "Corrupted Tag Variant",
            "subject": "Order update",
            "body_html": "<p>Your order #{{ order.name } is confirmed.</p>",
            "estimated_spam_risk": 2,
            "rationale": "Missing closing brace."
        }
    ]
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Order update",
        body_content=original_body,
        candidate_variants=candidates
    )
    assert len(res) == 0


@pytest.mark.asyncio
async def test_pipeline_no_liquid_tags_preserves_all_variants():
    """Scenario E: Template with no Liquid tags preserves all candidate variants."""
    original_body = "<p>Thank you for purchasing from our store. We appreciate your business!</p>"
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Thank you for your purchase!",
        body_content=original_body
    )
    # Default pipeline produces 3 candidates; all 3 must pass when no Liquid tags are in input
    assert len(res) == 3
    assert [v["variant_id"] for v in res] == ["v1_professional", "v2_conversational", "v3_vip"]


@pytest.mark.asyncio
async def test_pipeline_multiple_variants_partial_pass():
    """Scenario F: When some candidates pass and some fail, only valid variants are returned."""
    original_body = "<p>Hello {{ customer.first_name }}, order #{{ order.name }} is on the way.</p>"
    candidates = [
        {
            "variant_id": "v1_pass",
            "variant_name": "Preserved Variant",
            "subject": "Order update",
            "body_html": "<p>Hello {{ customer.first_name }}! Order #{{ order.name }} has shipped.</p>",
            "estimated_spam_risk": 2,
            "rationale": "All tags present."
        },
        {
            "variant_id": "v2_fail_missing",
            "variant_name": "Missing Tag Variant",
            "subject": "Order update",
            "body_html": "<p>Hello {{ customer.first_name }}! Your order has shipped.</p>",
            "estimated_spam_risk": 1,
            "rationale": "Missing order.name."
        },
        {
            "variant_id": "v3_pass",
            "variant_name": "Another Preserved Variant",
            "subject": "Order receipt",
            "body_html": "<p>Hi {{ customer.first_name }}, tracking for #{{ order.name }} is active.</p>",
            "estimated_spam_risk": 3,
            "rationale": "All tags present."
        },
        {
            "variant_id": "v4_fail_corrupt",
            "variant_name": "Corrupt Tag Variant",
            "subject": "Order update",
            "body_html": "<p>Hi { customer.first_name }}, order #{{ order.name }}.</p>",
            "estimated_spam_risk": 2,
            "rationale": "Single brace corruption."
        },
    ]
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Order update",
        body_content=original_body,
        candidate_variants=candidates
    )
    assert len(res) == 2
    assert [v["variant_id"] for v in res] == ["v1_pass", "v3_pass"]


@pytest.mark.asyncio
async def test_pipeline_all_variants_failing_preservation_returns_empty_list():
    """Scenario G: When all candidate variants fail preservation, an empty list is returned safely."""
    original_body = "<p>Tracking: {{ fulfillment.tracking_url }} | Custom: {{ proprietary.tag }}</p>"
    candidates = [
        {
            "variant_id": "v1_bad",
            "body_html": "<p>Tracking: {{ fulfillment.tracking_url }}</p>",
        },
        {
            "variant_id": "v2_bad",
            "body_html": "<p>Plain text without tags.</p>",
        }
    ]
    res = await ai_content_service.generate_polymorphic_variants(
        subject="Tracking Info",
        body_content=original_body,
        candidate_variants=candidates
    )
    assert res == []


def test_api_endpoint_liquid_preservation_empty_fallback():
    """Verify that calling the API with Liquid tags not present in candidates returns safe empty list."""
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.conftest import auth_headers

    client = TestClient(app, headers=auth_headers("test-liquid-user"))
    # Default candidates contain only {{ customer.first_name }}, {{ order.name }}, {{ checkout.order_status_url }}
    # Passing an unrepresented Liquid tag like {{ unknown.unsupported_tag }} causes fail-closed rejection of all candidates
    res = client.post(
        "/api/v1/ai/generate-variants",
        json={
            "subject": "Order Update",
            "body": "<p>Your order contains {{ unknown.unsupported_tag }}</p>"
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["variants"] == []
