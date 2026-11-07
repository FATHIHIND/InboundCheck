"""
InboundCheck - Shopify Billing Activation & Charge Lifecycle Regression Suite
==============================================================================
BILL-3: Shopify statuses map onto the existing profiles.subscription_status CHECK
        set, and every profile write only touches columns defined by migrations.
BILL-4: The appSubscriptionCreate returnUrl targets the BACKEND callback route.
BILL-8: app_subscriptions/update only mutates entitlements for the user's
        currently bound Shopify charge (old-charge CANCELLED after upgrade is a no-op).
"""

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.shopify.shopify_billing_service import (
    ShopifyBillingService,
    build_billing_return_url,
    map_shopify_subscription_status,
    shopify_billing_service,
)
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
BILLING_MIGRATION = MIGRATIONS_DIR / "20261107000002_shopify_billing_columns.sql"
TEST_SECRET = "test_billing_lifecycle_secret_key_32b!"
ALLOWED_APP_STATUSES = {"trialing", "active", "past_due", "canceled", "expired"}

OLD_CHARGE = "gid://shopify/AppSubscription/1001"
NEW_CHARGE = "gid://shopify/AppSubscription/2002"


def _recurring(amount: str) -> list:
    return [{"plan": {"pricingDetails": {
        "__typename": "AppRecurringPricing",
        "interval": "EVERY_30_DAYS",
        "price": {"amount": amount, "currencyCode": "USD"},
    }}}]


def profile_columns_from_migrations() -> set:
    """Build the set of public.profiles columns declared across all migrations."""
    columns: set = set()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8-sig"))
        for body in re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?public\.profiles\s*\((.*?)\n\);",
            sql, flags=re.IGNORECASE | re.DOTALL,
        ):
            for line in body.splitlines():
                token = line.strip().split(" ", 1)[0].strip('",')
                if token and token.upper() not in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
                    columns.add(token.lower())
        for stmt in re.findall(r"ALTER\s+TABLE\s+(?:ONLY\s+)?public\.profiles\b(.*?);", sql, flags=re.IGNORECASE | re.DOTALL):
            columns.update(
                c.lower() for c in re.findall(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)", stmt, flags=re.IGNORECASE)
            )
    return columns


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).digest()).decode()


@pytest.fixture(autouse=True)
def _webhook_secret():
    original = shopify_service.api_secret
    shopify_service.api_secret = TEST_SECRET
    yield
    shopify_service.api_secret = original


@pytest.fixture
def merchant():
    user_id = f"bill_life_{uuid.uuid4().hex[:8]}"
    shop = f"bill-life-{uuid.uuid4().hex[:6]}.myshopify.com"
    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop,
        access_token_encrypted=shopify_service.encrypt_token("shpat_lifecycle_test_token"),
    )
    supabase_service.update_user_profile(user_id, {"subscription_tier": "starter", "subscription_status": "trialing"})
    return {"user_id": user_id, "shop": shop}


async def _post_subscription_event(shop: str, charge_id: str, status: str, name: str = "InboundCheck Growth Plan",
                                   webhook_id: str = None):
    payload = {"app_subscription": {"admin_graphql_api_id": charge_id, "name": name, "status": status}}
    body = json.dumps(payload).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(
            "/api/v1/shopify/webhooks/app_subscriptions/update",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": _sign(body),
                "X-Shopify-Shop-Domain": shop,
                "X-Shopify-Triggered-At": str(int(time.time())),
                "X-Shopify-Webhook-Id": webhook_id or f"wh-{uuid.uuid4().hex}",
            },
        )


# ---------------------------------------------------------------------------
# BILL-3: status mapping table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shopify_status,expected", [
    ("ACTIVE", "active"),
    ("active", "active"),
    ("ACCEPTED", "active"),
    ("PENDING", None),
    ("DECLINED", "canceled"),
    ("CANCELLED", "canceled"),
    ("CANCELED", "canceled"),
    ("EXPIRED", "expired"),
    ("FROZEN", "past_due"),
    ("PAUSED", "past_due"),
    ("", None),
    (None, None),
    ("SOMETHING_NEW", None),
])
def test_status_mapping_table(shopify_status, expected):
    result = map_shopify_subscription_status(shopify_status)
    assert result == expected
    assert result is None or result in ALLOWED_APP_STATUSES


# ---------------------------------------------------------------------------
# BILL-3: profile writes only touch migration-defined columns
# ---------------------------------------------------------------------------

def test_profile_column_parser_sees_new_billing_columns():
    cols = profile_columns_from_migrations()
    assert {"subscription_status", "subscription_tier", "tier", "updated_at"} <= cols
    assert {"billing_provider", "shopify_charge_id"} <= cols


@pytest.mark.asyncio
async def test_callback_writes_only_existing_profile_columns(merchant, monkeypatch):
    writes = []
    original = supabase_service.update_user_profile

    def recorder(uid, updates):
        writes.append(dict(updates))
        return original(uid, updates)

    monkeypatch.setattr(supabase_service, "update_user_profile", recorder)
    node = {"id": NEW_CHARGE, "status": "ACTIVE", "lineItems": _recurring("29.00")}
    with patch.object(shopify_billing_service, "verify_and_activate_subscription", new_callable=AsyncMock, return_value=node):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=2002&shop={merchant['shop']}&user_id={merchant['user_id']}"
            )
    assert res.status_code == 302
    assert writes, "callback must persist the activation"
    cols = profile_columns_from_migrations()
    for w in writes:
        assert set(w) <= cols, f"unknown profile columns written: {set(w) - cols}"
        assert w.get("subscription_status") in ALLOWED_APP_STATUSES
    profile = supabase_service.get_user_profile(merchant["user_id"])
    assert profile["billing_provider"] == "shopify"
    assert profile["shopify_charge_id"] == NEW_CHARGE
    assert profile["subscription_tier"] == "growth"


@pytest.mark.asyncio
async def test_callback_idempotent_for_bound_charge_numeric_or_gid(merchant):
    supabase_service.update_user_profile(merchant["user_id"], {
        "subscription_tier": "agency", "subscription_status": "active",
        "billing_provider": "shopify", "shopify_charge_id": NEW_CHARGE,
    })
    verify = AsyncMock(side_effect=AssertionError("idempotent hit must not re-verify"))
    with patch.object(shopify_billing_service, "verify_and_activate_subscription", verify):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=2002&shop={merchant['shop']}&user_id={merchant['user_id']}"
            )
    assert res.status_code == 302
    assert "plan=agency" in res.headers["location"]


@pytest.mark.asyncio
async def test_webhook_writes_only_existing_profile_columns(merchant, monkeypatch):
    supabase_service.update_user_profile(merchant["user_id"], {
        "subscription_tier": "growth", "subscription_status": "active", "shopify_charge_id": NEW_CHARGE,
    })
    writes = []
    original = supabase_service.update_user_profile

    def recorder(uid, updates):
        writes.append(dict(updates))
        return original(uid, updates)

    monkeypatch.setattr(supabase_service, "update_user_profile", recorder)
    cols = profile_columns_from_migrations()
    for status in ("FROZEN", "DECLINED", "EXPIRED", "CANCELLED"):
        node = {"id": NEW_CHARGE, "status": status, "lineItems": _recurring("29.00")}
        with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=node):
            res = await _post_subscription_event(merchant["shop"], NEW_CHARGE, status)
        assert res.status_code == 200
    assert writes
    for w in writes:
        assert set(w) <= cols, f"unknown profile columns written: {set(w) - cols}"
        assert w["subscription_status"] in ALLOWED_APP_STATUSES


# ---------------------------------------------------------------------------
# BILL-8: charge lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_old_charge_cancelled_after_new_active_leaves_user_active(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {
        "subscription_tier": "starter", "subscription_status": "active",
        "billing_provider": "shopify", "shopify_charge_id": OLD_CHARGE,
    })
    # Upgrade: new charge becomes ACTIVE (authoritatively verified, agency pricing).
    new_node = {"id": NEW_CHARGE, "status": "ACTIVE", "name": "InboundCheck Agency Plan", "lineItems": _recurring("79.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=new_node):
        res = await _post_subscription_event(shop, NEW_CHARGE, "ACTIVE", "InboundCheck Agency Plan")
    assert res.status_code == 200
    prof = supabase_service.get_user_profile(uid)
    assert prof["shopify_charge_id"] == NEW_CHARGE
    assert prof["subscription_tier"] == "agency"
    assert prof["subscription_status"] == "active"

    # Shopify then cancels the replaced (old) charge.
    old_node = {"id": OLD_CHARGE, "status": "CANCELLED", "lineItems": _recurring("9.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=old_node):
        res = await _post_subscription_event(shop, OLD_CHARGE, "CANCELLED", "InboundCheck Starter Plan")
    assert res.status_code == 200
    assert res.json()["action"] == "stale_charge_ignored"
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "active"
    assert prof["subscription_tier"] == "agency"
    assert prof["shopify_charge_id"] == NEW_CHARGE


@pytest.mark.asyncio
async def test_same_charge_cancelled_downgrades(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {
        "subscription_tier": "growth", "subscription_status": "active",
        "billing_provider": "shopify", "shopify_charge_id": NEW_CHARGE,
    })
    node = {"id": NEW_CHARGE, "status": "CANCELLED", "lineItems": _recurring("29.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=node):
        res = await _post_subscription_event(shop, "2002", "CANCELLED")  # numeric id still matches
    assert res.status_code == 200
    assert res.json()["action"] == "subscription_canceled"
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "canceled"
    assert prof["subscription_tier"] == "starter"


@pytest.mark.asyncio
async def test_frozen_same_charge_maps_to_past_due(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {
        "subscription_tier": "growth", "subscription_status": "active", "shopify_charge_id": NEW_CHARGE,
    })
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=None):
        res = await _post_subscription_event(shop, NEW_CHARGE, "FROZEN")
    assert res.status_code == 200
    assert supabase_service.get_user_profile(uid)["subscription_status"] == "past_due"


@pytest.mark.asyncio
async def test_unknown_or_other_charge_event_ignored(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {
        "subscription_tier": "growth", "subscription_status": "active", "shopify_charge_id": NEW_CHARGE,
    })
    other = "gid://shopify/AppSubscription/3003"
    for status in ("CANCELLED", "EXPIRED", "DECLINED", "FROZEN"):
        with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=None):
            res = await _post_subscription_event(shop, other, status)
        assert res.status_code == 200
        assert res.json()["action"] == "stale_charge_ignored"
    # Unverifiable ACTIVE for a different charge must not rebind or upgrade.
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=None):
        res = await _post_subscription_event(shop, other, "ACTIVE", "InboundCheck Agency Plan")
    assert res.status_code == 200
    assert res.json()["action"] != "subscription_activated"
    # Malformed identity is ignored, never 500.
    res = await _post_subscription_event(shop, "not-a-charge-id", "CANCELLED")
    assert res.status_code == 200
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "active"
    assert prof["subscription_tier"] == "growth"
    assert prof["shopify_charge_id"] == NEW_CHARGE


@pytest.mark.asyncio
async def test_active_event_tier_comes_from_pricing_not_name(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    # Name claims Agency, verified price is the Starter price.
    node = {"id": NEW_CHARGE, "status": "ACTIVE", "name": "InboundCheck Agency Plan", "lineItems": _recurring("9.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=node):
        res = await _post_subscription_event(shop, NEW_CHARGE, "ACTIVE", "InboundCheck Agency Plan")
    assert res.status_code == 200
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_tier"] == "starter"
    assert prof["shopify_charge_id"] == NEW_CHARGE

    # Unsupported pricing never falls back to a 'growth' default.
    uid2 = f"bill_life_{uuid.uuid4().hex[:8]}"
    shop2 = f"bill-life-{uuid.uuid4().hex[:6]}.myshopify.com"
    supabase_service.save_monitored_store(user_id=uid2, shop_domain=shop2,
                                          access_token_encrypted=shopify_service.encrypt_token("shpat_x"))
    supabase_service.update_user_profile(uid2, {"subscription_tier": "starter", "subscription_status": "trialing"})
    bad = {"id": NEW_CHARGE.replace("2002", "4004"), "status": "ACTIVE", "name": "InboundCheck Growth Plan",
           "lineItems": _recurring("123.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=bad):
        res = await _post_subscription_event(shop2, bad["id"], "ACTIVE")
    assert res.status_code == 200
    prof2 = supabase_service.get_user_profile(uid2)
    assert prof2["subscription_tier"] == "starter"
    assert prof2["subscription_status"] == "trialing"


# ---------------------------------------------------------------------------
# REV-1: a failed authoritative lookup must not consume the webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_failure_returns_503_and_retry_activates(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    wid = f"wh-rev1-{uuid.uuid4().hex}"
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock,
                      side_effect=httpx.ReadTimeout("timed out")):
        res = await _post_subscription_event(shop, NEW_CHARGE, "ACTIVE", webhook_id=wid)
    assert res.status_code == 503
    assert not shopify_service.is_webhook_processed(wid)
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "trialing"
    assert not prof.get("shopify_charge_id")

    # Shopify retries the same delivery once the lookup works again.
    node = {"id": NEW_CHARGE, "status": "ACTIVE", "lineItems": _recurring("29.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=node):
        res = await _post_subscription_event(shop, NEW_CHARGE, "ACTIVE", webhook_id=wid)
    assert res.status_code == 200
    assert res.json()["action"] == "subscription_activated"
    assert shopify_service.is_webhook_processed(wid)
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "active"
    assert prof["subscription_tier"] == "growth"
    assert prof["shopify_charge_id"] == NEW_CHARGE


@pytest.mark.asyncio
async def test_token_decrypt_failure_returns_503_not_processed(merchant):
    wid = f"wh-rev1-{uuid.uuid4().hex}"
    with patch.object(shopify_service, "decrypt_token", side_effect=ValueError("bad token")):
        res = await _post_subscription_event(merchant["shop"], NEW_CHARGE, "ACTIVE", webhook_id=wid)
    assert res.status_code == 503
    assert not shopify_service.is_webhook_processed(wid)


@pytest.mark.asyncio
async def test_lookup_success_without_node_still_acks(merchant):
    wid = f"wh-rev1-{uuid.uuid4().hex}"
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=None):
        res = await _post_subscription_event(merchant["shop"], NEW_CHARGE, "ACTIVE", webhook_id=wid)
    assert res.status_code == 200
    assert res.json()["action"] == "unverified_activation_ignored"
    assert shopify_service.is_webhook_processed(wid)


def _gql_client(response):
    client = MagicMock()
    if isinstance(response, Exception):
        client.post = AsyncMock(side_effect=response)
    else:
        client.post = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    httpx.ConnectTimeout("timeout"),
    MagicMock(status_code=502),
    MagicMock(status_code=401),
])
async def test_get_app_subscription_raises_on_transport_or_http_failure(failure):
    with patch("app.services.shopify.shopify_billing_service.httpx.AsyncClient", return_value=_gql_client(failure)):
        with pytest.raises(Exception):
            await ShopifyBillingService().get_app_subscription("t.myshopify.com", "tok", "123")


@pytest.mark.asyncio
async def test_get_app_subscription_returns_none_when_node_absent():
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": {"node": None}}
    with patch("app.services.shopify.shopify_billing_service.httpx.AsyncClient", return_value=_gql_client(response)):
        assert await ShopifyBillingService().get_app_subscription("t.myshopify.com", "tok", "123") is None


# ---------------------------------------------------------------------------
# REV-2: NULL charge binding (pre-migration profiles) can still be downgraded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("shopify_status,expected", [
    ("CANCELLED", "canceled"),
    ("EXPIRED", "expired"),
    ("FROZEN", "past_due"),
])
async def test_null_binding_downgrade_applies_when_shopify_confirms(merchant, shopify_status, expected):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {"subscription_tier": "growth", "subscription_status": "active"})
    assert not supabase_service.get_user_profile(uid).get("shopify_charge_id")
    node = {"id": NEW_CHARGE, "status": shopify_status, "lineItems": _recurring("29.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=node):
        res = await _post_subscription_event(shop, NEW_CHARGE, shopify_status)
    assert res.status_code == 200
    assert res.json()["action"] == f"subscription_{expected}"
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == expected
    assert prof["subscription_tier"] == "starter"


@pytest.mark.asyncio
async def test_null_binding_downgrade_never_applies_to_stripe_profile(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {
        "subscription_tier": "growth", "subscription_status": "active", "billing_provider": "stripe",
    })
    node = {"id": NEW_CHARGE, "status": "CANCELLED", "lineItems": _recurring("29.00")}
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=node):
        res = await _post_subscription_event(shop, NEW_CHARGE, "CANCELLED")
    assert res.status_code == 200
    assert res.json()["action"] == "stale_charge_ignored"
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "active"
    assert prof["subscription_tier"] == "growth"


@pytest.mark.asyncio
async def test_null_binding_downgrade_ignored_when_unconfirmed(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {"subscription_tier": "growth", "subscription_status": "active"})
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock, return_value=None):
        res = await _post_subscription_event(shop, NEW_CHARGE, "CANCELLED")
    assert res.status_code == 200
    assert res.json()["action"] == "stale_charge_ignored"
    prof = supabase_service.get_user_profile(uid)
    assert prof["subscription_status"] == "active"
    assert prof["subscription_tier"] == "growth"


@pytest.mark.asyncio
async def test_null_binding_downgrade_lookup_failure_returns_503(merchant):
    uid, shop = merchant["user_id"], merchant["shop"]
    supabase_service.update_user_profile(uid, {"subscription_tier": "growth", "subscription_status": "active"})
    wid = f"wh-rev2-{uuid.uuid4().hex}"
    with patch.object(shopify_billing_service, "get_app_subscription", new_callable=AsyncMock,
                      side_effect=RuntimeError("Shopify 503")):
        res = await _post_subscription_event(shop, NEW_CHARGE, "CANCELLED", webhook_id=wid)
    assert res.status_code == 503
    assert not shopify_service.is_webhook_processed(wid)
    assert supabase_service.get_user_profile(uid)["subscription_tier"] == "growth"


# ---------------------------------------------------------------------------
# BILL-4: return URL targets the backend callback route
# ---------------------------------------------------------------------------

def _registered_callback_path() -> str:
    # Use the generated OpenAPI paths rather than walking app.routes: FastAPI
    # >= 0.16x keeps included routers as nested `_IncludedRouter` entries
    # instead of flattening them, so a top-level app.routes scan finds nothing
    # on the locked runtime (it only worked on older local FastAPI versions).
    paths = set(app.openapi()["paths"])
    matches = [p for p in paths if p.endswith("/shopify/billing/callback")]
    assert len(matches) == 1, matches
    return matches[0]


def test_return_url_targets_backend_callback(monkeypatch):
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://api.inboundcheck.example/")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.inboundcheck.example")
    url = build_billing_return_url("shop-a.myshopify.com", user_id="u-1", plan_tier="growth")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}" == "https://api.inboundcheck.example"
    assert parsed.path == _registered_callback_path() == "/api/v1/shopify/billing/callback"
    assert "app.inboundcheck.example" not in url
    qs = parse_qs(parsed.query)
    assert qs["shop"] == ["shop-a.myshopify.com"] and qs["user_id"] == ["u-1"] and qs["plan_tier"] == ["growth"]


def test_return_url_fails_closed_in_production_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="BACKEND_PUBLIC_URL"):
        build_billing_return_url("shop-a.myshopify.com")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "http://api.inboundcheck.example")
    with pytest.raises(RuntimeError, match="https"):
        build_billing_return_url("shop-a.myshopify.com")


@pytest.mark.asyncio
async def test_default_return_url_in_charge_create_targets_backend(monkeypatch):
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://api.inboundcheck.example")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.inboundcheck.example")
    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"data": {"appSubscriptionCreate": {"confirmationUrl": "https://admin.shopify.com/c", "userErrors": []}}}

    async def fake_post(self, url, json=None, headers=None):
        captured.update(json["variables"])
        return _Resp()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await ShopifyBillingService().create_shopify_recurring_charge("shop-a.myshopify.com", "tok", "growth")
    assert captured["returnUrl"].startswith("https://api.inboundcheck.example/api/v1/shopify/billing/callback?")


@pytest.mark.asyncio
async def test_checkout_session_passes_backend_return_url(monkeypatch):
    from tests.conftest import auth_headers

    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://api.inboundcheck.example")
    uid = f"bill_life_{uuid.uuid4().hex[:8]}"
    shop = f"bill-life-{uuid.uuid4().hex[:6]}.myshopify.com"
    supabase_service.save_monitored_store(user_id=uid, shop_domain=shop,
                                          access_token_encrypted=shopify_service.encrypt_token("shpat_x"))
    with patch.object(shopify_billing_service, "create_shopify_recurring_charge", new_callable=AsyncMock,
                      return_value="https://admin.shopify.com/confirm") as create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=auth_headers(uid)) as ac:
            res = await ac.post("/api/v1/billing/checkout-session", json={"plan_tier": "growth", "shop_domain": shop})
    assert res.status_code == 200
    return_url = create.call_args.kwargs["return_url"]
    assert return_url.startswith("https://api.inboundcheck.example/api/v1/shopify/billing/callback?")


# ---------------------------------------------------------------------------
# BILL-3: migration contract
# ---------------------------------------------------------------------------

def test_migration_adds_columns_unique_index_and_no_client_grants():
    assert BILLING_MIGRATION.exists()
    raw = BILLING_MIGRATION.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", raw)
    norm = re.sub(r"\s+", " ", sql).lower()
    assert norm.strip().startswith("begin;") and norm.strip().endswith("commit;")
    assert "add column if not exists billing_provider text" in norm
    assert "add column if not exists shopify_charge_id text" in norm
    assert "billing_provider in ('stripe','shopify')" in norm.replace(", ", ",")
    assert re.search(
        r"create unique index if not exists \w+ on public\.profiles ?\(shopify_charge_id\) where shopify_charge_id is not null",
        norm,
    )
    assert "subscription_status" not in norm, "must not widen subscription_status"
    for grant in re.findall(r"grant [^;]*;", norm):
        assert "authenticated" not in grant and "anon" not in grant and "public" not in grant.split(" to ")[-1]
    # REV-5: the trigger is the real control. A column-level REVOKE cannot remove a
    # table-level UPDATE grant, so the REVOKE is defense-in-depth only.
    assert re.search(
        r"create trigger trg_protect_profile_shopify_billing_columns before insert or update on public\.profiles "
        r"for each row execute function public\.protect_profile_shopify_billing_columns\(\)",
        norm,
    )
    fn = re.search(
        r"create or replace function public\.protect_profile_shopify_billing_columns\(\)(.*?)\$guard\$;",
        norm,
    )
    assert fn, "trigger function must be defined in this migration"
    body = fn.group(1)
    assert "security invoker" in body
    # INSERT: both columns guarded
    assert "new.billing_provider is not null or new.shopify_charge_id is not null" in body
    # UPDATE: both columns guarded
    assert "new.billing_provider is distinct from old.billing_provider" in body
    assert "new.shopify_charge_id is distinct from old.shopify_charge_id" in body
    assert "raise exception 'billing_write_requires_trusted_sql_role'" in body
    # The comment must not present the column REVOKE as the protection.
    comments = re.sub(r"\s+", " ", " ".join(re.findall(r"--([^\n]*)", raw))).lower()
    assert "defense-in-depth" in comments
    assert "does not remove a table-level update grant" in comments
    for header in ("Purpose", "Verification", "Rollback"):
        assert header.lower() in raw.lower()
