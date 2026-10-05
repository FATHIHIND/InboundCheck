"""
InboundCheck - Public Claim Truthfulness & Shopify App Review Integrity Tests
=============================================================================
Enforces Phase 18B.3 Truthfulness Requirements:
1. Landing page does not contain unsupported "Automated Seed Testing" or "IMAP Probes" claims.
2. Public SEO metadata does not advertise live seed inbox testing.
3. Public FAQ/JSON-LD does not claim live Gmail/Yahoo/Outlook placement.
4. No public feature card claims real mailbox verification.
5. Existing legitimate deliverability features remain present.
6. Seed testing UI tab is safely unmounted from default public dashboard inspector.
"""

from pathlib import Path
import re
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend" / "src" / "app"


def test_landing_page_has_no_unsupported_seed_or_imap_claims():
    """Verify landing page contains zero unsupported claims of IMAP Probes or Automated Seed Testing."""
    page_file = FRONTEND_DIR / "page.tsx"
    assert page_file.exists(), f"Landing page not found at {page_file}"

    content = page_file.read_text(encoding="utf-8")

    # 1. Must NOT contain "IMAP Probes" in pricing or feature cards
    assert "IMAP Probes" not in content, "Found unsupported 'IMAP Probes' claim in landing page!"
    assert "Automated Seed Testing" not in content, "Found unsupported 'Automated Seed Testing' claim in landing page!"

    # 2. Must NOT claim live primary inbox placement measurement or seed mailbox verification
    assert "Queries Gmail, Yahoo, and Outlook IMAP" not in content
    assert "live inbox placement verification" not in content.lower()
    assert "real seed mailbox monitoring" not in content.lower()

    # 3. Dedicated 15m Sweeps must be truthful (e.g. Real-Time Radar or Reputation Sweeps)
    assert "Dedicated 15m Sweeps &amp; Real-Time Radar" in content or "Dedicated 15m Sweeps" in content


def test_public_metadata_does_not_advertise_seed_testing():
    """Verify root layout SEO and OpenGraph metadata does not claim seed testing."""
    layout_file = FRONTEND_DIR / "layout.tsx"
    assert layout_file.exists(), f"Root layout not found at {layout_file}"

    content = layout_file.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "seed" not in lower_content, "Found unexpected 'seed' in public layout metadata!"
    assert "imap" not in lower_content, "Found unexpected 'imap' in public layout metadata!"
    assert "mailbox placement" not in lower_content, "Found 'mailbox placement' in public layout metadata!"


def test_public_json_ld_and_faq_truthfulness():
    """Verify structured data JSON-LD and FAQ entries do not claim live Gmail/Yahoo/Outlook seed verification."""
    page_file = FRONTEND_DIR / "page.tsx"
    content = page_file.read_text(encoding="utf-8")

    # Extract JSON-LD / FAQ section
    assert "FAQ_ITEMS" in content
    assert "structuredData" in content

    # In FAQ answers, ensure no false claims of seed testing
    faq_match = re.search(r"const FAQ_ITEMS = \[(.*?)\];", content, re.DOTALL)
    assert faq_match, "FAQ_ITEMS array not found in landing page"
    faq_text = faq_match.group(1).lower()

    assert "seed" not in faq_text, "Found seed testing claim in FAQ!"
    assert "imap" not in faq_text, "Found IMAP claim in FAQ!"
    assert "mailbox placement" not in faq_text, "Found mailbox placement claim in FAQ!"


def test_public_feature_cards_claim_no_real_mailbox_verification():
    """Verify pricing cards and feature blocks do not promise live mailbox delivery confirmation."""
    page_file = FRONTEND_DIR / "page.tsx"
    content = page_file.read_text(encoding="utf-8")

    # Check pricing section
    pricing_idx = content.find("PRICING TIERS")
    if pricing_idx != -1:
        pricing_section = content[pricing_idx:]
        assert "seed testing" not in pricing_section.lower()
        assert "imap probe" not in pricing_section.lower()
        assert "live mailbox" not in pricing_section.lower()


def test_legitimate_deliverability_features_preserved():
    """Verify all real, verified InboundCheck features remain actively present on landing page."""
    page_file = FRONTEND_DIR / "page.tsx"
    content = page_file.read_text(encoding="utf-8")

    # Core DNS governance & SPF merge
    assert "SPF" in content
    assert "DKIM" in content
    assert "DMARC" in content
    assert "10-lookup" in content

    # 1-Click DNS remediation
    assert "Cloudflare" in content
    assert "GoDaddy" in content

    # Blacklist Radar
    assert "Spamhaus" in content
    assert "Barracuda" in content

    # 3-Day Free Trial
    assert "3-Day Free Trial" in content


def test_dashboard_inspector_hides_unsupported_seed_tab():
    """Verify Inspector UI does not expose unbacked Seed Inbox Verifier tab button to merchants."""
    inspector_file = FRONTEND_DIR / "dashboard" / "inspector" / "page.tsx"
    assert inspector_file.exists()

    content = inspector_file.read_text(encoding="utf-8")

    # Button must not exist in tab bar
    assert "Seed Inbox Verifier" not in content, "Found 'Seed Inbox Verifier' tab in dashboard inspector!"
    assert 'activeTab === "seed-testing"' not in content, "Found activeTab === 'seed-testing' in inspector!"
