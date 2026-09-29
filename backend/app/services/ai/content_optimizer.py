"""
InboundCheck - AI Content Intelligence & Polymorphic Engine (Bloc A)
=====================================================================
Low-cost, open-weights compatible LLM engine for auditing Shopify transactional
email templates, identifying spam triggers, and generating polymorphic variants.
"""

import re
import httpx
import logging
from typing import Dict, Any, List, Optional, Set
from app.core.config import settings
from app.services.ai.provider import (
    BaseLLMProvider,
    HeuristicFallbackProvider,
    LLMProviderNotConfiguredError,
    LLMGenerationError,
    get_llm_provider,
    LLMProviderConfig,
)

logger = logging.getLogger("AIContentOptimizer")

# Liquid tag pattern: matches {{ ... }} output expressions and {% ... %} control tags non-greedily
LIQUID_TAG_PATTERN = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", re.DOTALL)


def extract_liquid_tags(text: str) -> Set[str]:
    """
    Extract all Shopify Liquid constructs from template text.
    Captures both output tags ({{ ... }}) and logic/control tags ({% ... %}).
    Preserves exact whitespace and tag contents.
    """
    if not text or not isinstance(text, str):
        return set()

    matches = LIQUID_TAG_PATTERN.findall(text)
    return set(matches)


def validate_liquid_preservation(original_tags: Set[str], variant_body: str) -> bool:
    """
    Validate that every Liquid tag extracted from the original template
    is preserved exactly in the synthesized variant body.

    Security Invariant:
    A generated variant must NEVER be considered valid if it removes,
    changes, corrupts, or partially rewrites an original Liquid tag.
    Fails closed (returns False) on any missing, corrupted, or altered tag.
    """
    if not original_tags:
        return True

    if not variant_body or not isinstance(variant_body, str):
        return False

    for tag in original_tags:
        if tag not in variant_body:
            return False

    return True

SPAM_TRIGGER_PATTERNS = [
    r"\b(100% free|completely free|risk free|risk-free)\b",
    r"\b(act now|buy now|click here|order now|immediate action)\b",
    r"\b(guaranteed|guarantee|100% satisfied|satisfaction guaranteed)\b",
    r"\b(congratulations|winner|you have been selected|claim now)\b",
    r"\b(make money|fast cash|earn \$|double your income)\b",
    r"\b(urgent|important notice|account suspended|verify now)\b",
    r"\b(no cost|no hidden fees|lowest price|cheap)\b",
]

DEFAULT_SAMPLE_TEMPLATES = {
    "order_confirmation": {
        "name": "Shopify Order Confirmation",
        "subject": "Thank you for your purchase! Order #{{ order.name }} is confirmed",
        "body_html": "<p>Hi {{ customer.first_name }},</p><p>Thank you for buying from our store! ACT NOW to claim 100% FREE shipping on your next purchase. Click here to confirm!</p>"
    },
    "shipping_update": {
        "name": "Shipping Update",
        "subject": "Your order #{{ order.name }} is on the way!",
        "body_html": "<p>Hi {{ customer.first_name }},</p><p>Great news! Your package has been dispatched. Track your delivery here: {{ fulfillment.tracking_url }}.</p>"
    },
    "abandoned_checkout": {
        "name": "Abandoned Cart Recovery",
        "subject": "Did you forget something? Claim your items now!",
        "body_html": "<p>Hi {{ customer.first_name }},</p><p>You left items in your cart! URGENT: 100% FREE discount expires in 2 hours. Click here to complete checkout!</p>"
    }
}


class AIContentOptimizer:
    """
    OpenAI-compatible LLM service adapter for email content spam diagnostics
    and polymorphic text transformation.
    """

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        self.api_base = settings.LLM_API_BASE
        self.api_key = settings.LLM_API_KEY
        self.model_name = settings.LLM_MODEL_NAME
        self._explicit_provider: Optional[BaseLLMProvider] = provider

    @property
    def provider(self) -> BaseLLMProvider:
        """
        Return explicitly injected provider if present, otherwise dynamically resolve
        the default provider from server configuration.
        """
        if self._explicit_provider is not None:
            return self._explicit_provider

        target = "agent_router" if getattr(settings, "AGENT_ROUTER_ENABLED", False) else "heuristic_fallback"
        return get_llm_provider(target)

    @provider.setter
    def provider(self, value: Optional[BaseLLMProvider]) -> None:
        self._explicit_provider = value

    @provider.deleter
    def provider(self) -> None:
        self._explicit_provider = None

    @staticmethod
    def extract_liquid_tags(text: str) -> Set[str]:
        return extract_liquid_tags(text)

    @staticmethod
    def validate_liquid_preservation(original_tags: Set[str], variant_body: str) -> bool:
        return validate_liquid_preservation(original_tags, variant_body)

    def _rule_based_audit(self, text: str) -> Dict[str, Any]:
        """Perform instant deterministic rule-based analysis of spam triggers."""
        lower_text = text.lower()
        flagged = []

        for pattern in SPAM_TRIGGER_PATTERNS:
            matches = re.findall(pattern, lower_text, flags=re.IGNORECASE)
            if matches:
                flagged.extend(matches)

        flagged_unique = list(set(flagged))

        # Check ALL CAPS ratio
        uppercase_chars = sum(1 for c in text if c.isupper())
        total_chars = max(1, len(text))
        caps_ratio = round((uppercase_chars / total_chars) * 100, 1)

        # Exclamation density
        exclamations = text.count("!") + text.count("$$$")
        
        # Calculate spam score (0 = clean, 100 = heavy spam)
        raw_score = (len(flagged_unique) * 20) + (15 if caps_ratio > 20 else 0) + (exclamations * 5)
        spam_score = min(100, max(0, raw_score))

        if spam_score >= 60:
            risk_level = "high"
        elif spam_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        recommendations = []
        if flagged_unique:
            recommendations.append(f"Remove or replace high-friction promotional words: {', '.join(flagged_unique[:4])}")
        if caps_ratio > 20:
            recommendations.append("Reduce ALL-CAPS text ratio below 10% to prevent spam filter triggers.")
        if exclamations > 2:
            recommendations.append("Limit consecutive exclamation marks and dollar symbols.")
        if "click here" in lower_text:
            recommendations.append("Replace generic 'click here' anchor text with descriptive link labels.")

        if not recommendations:
            recommendations.append("Template follows optimal transactional deliverability guidelines.")

        return {
            "spam_score": spam_score,
            "risk_level": risk_level,
            "promotional_density": min(100.0, round(len(flagged_unique) * 12.5 + caps_ratio * 0.5, 1)),
            "flagged_triggers": flagged_unique,
            "recommendations": recommendations
        }

    async def analyze_template(self, subject: str, body_content: str) -> Dict[str, Any]:
        """
        Analyze email subject line and body content for deliverability risks.
        Uses low-cost LLM endpoint if configured, else falls back to heuristic engine.
        """
        full_text = f"{subject}\n{body_content}"
        audit_result = self._rule_based_audit(full_text)

        if self.api_key and self.api_base:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    res = await client.post(
                        f"{self.api_base}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model_name,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "You are a deliverability audit assistant. Analyze the email copy for spam triggers and return concise recommendations."
                                },
                                {
                                    "role": "user",
                                    "content": f"Subject: {subject}\nBody: {body_content}"
                                }
                            ],
                            "max_tokens": 200,
                            "temperature": 0.3
                        }
                    )
                    if res.status_code == 200:
                        llm_out = res.json()
                        content = llm_out.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if content:
                            audit_result["recommendations"].append(f"AI Insights: {content[:150]}...")
            except Exception as e:
                logger.debug(f"LLM API call skipped/failed: {e}")

        return audit_result

    async def generate_polymorphic_variants(
        self,
        subject: str,
        body_content: str,
        candidate_variants: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate deliverability-optimized polymorphic content variations
        that strictly preserve Liquid template variables (e.g. {{ order.name }}).

        Security Invariant:
        Every candidate variant body is validated against all Liquid tags extracted
        from the original body_content. Any variant missing, modifying, or corrupting
        an original Liquid tag is rejected and excluded from the returned variants.
        """
        # 1. Extract original Liquid tags from source body
        original_tags = extract_liquid_tags(body_content)

        # 2. Determine candidate variants via provider abstraction
        if candidate_variants is not None:
            candidates = candidate_variants
        else:
            try:
                candidates = await self.provider.generate_variants(
                    subject,
                    body_content,
                    liquid_tags=original_tags,
                )
            except (LLMProviderNotConfiguredError, LLMGenerationError) as e:
                logger.warning(
                    f"Configured provider '{self.provider.provider_name}' unavailable or failed ({e}); "
                    "falling back safely to deterministic heuristic synthesis."
                )
                fallback_provider = HeuristicFallbackProvider()
                candidates = await fallback_provider.generate_variants(subject, body_content)

        # 3. Fail-closed validation gate: each candidate variant must preserve all original Liquid tags verbatim
        valid_variants: List[Dict[str, Any]] = []
        for variant in candidates:
            # Check all candidate body fields present in the variant
            candidate_bodies = [
                variant[key]
                for key in ("body_html", "body", "body_content")
                if key in variant
            ]
            if not candidate_bodies:
                if original_tags:
                    logger.warning(
                        f"Variant '{variant.get('variant_id')}' rejected: "
                        f"Empty generated body when Liquid tags are required."
                    )
                    continue
                else:
                    valid_variants.append(variant)
                    continue

            if all(validate_liquid_preservation(original_tags, cb) for cb in candidate_bodies):
                valid_variants.append(variant)
            else:
                logger.warning(
                    f"Variant '{variant.get('variant_id')}' rejected: "
                    f"Failed Liquid tag preservation safety check."
                )

        return valid_variants


ai_content_service = AIContentOptimizer()
