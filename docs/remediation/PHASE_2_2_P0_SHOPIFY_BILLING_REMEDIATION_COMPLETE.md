# InboundCheck Enterprise — P0 Shopify Billing Security Remediation Report

> **Document Type:** Production Security Remediation & Cryptographic Audit  
> **Classification:** Institutional SaaS Security (P0 Verification)  
> **Target:** InboundCheck Transactional Email Deliverability & DNS Governance Platform  
> **Date:** September 23, 2026  
> **Status:** **P0 REMEDIATION COMPLETE & VERIFIED**

---

## 1. Executive Summary

During the Phase 2.2 independent production readiness audit, Finding **BIL-01 (P0)** identified a catastrophic billing bypass in `backend/app/api/v1/shopify.py::shopify_billing_callback`.

The callback endpoint caught and swallowed exceptions during Shopify subscription verification, allowing execution to fall through into `supabase_service.update_user_profile()` and unconditionally upgrade the store owner to `subscription_tier = "enterprise"` with `$0` payment.

This remediation completely closes the bypass, establishes a strict fail-closed state machine, enforces server-side GraphQL subscription verification against the Shopify Admin API, binds plan tiers to verified subscription names, guarantees idempotency, and proves through 17 adversarial security tests that Enterprise access is never granted upon verification failure.

---

## 2. Original Vulnerability

In [`backend/app/api/v1/shopify.py:276-297`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/shopify.py#L276-L297):
```python
    # If store has encrypted token, verify charge node with Shopify Admin API
    if store.get("access_token_encrypted"):
        try:
            from app.services.shopify.shopify_billing_service import shopify_billing_service
            token = shopify_service.decrypt_token(store["access_token_encrypted"])
            await shopify_billing_service.verify_and_activate_subscription(
                shop_domain=clean_shop,
                access_token=token,
                charge_id=charge_id
            )
        except Exception as err:
            logger.warning(f"Could not verify subscription node with Shopify: {err}")

    # Activate subscription tier in Supabase profile
    tier = (plan_tier or "growth").lower()
    supabase_service.update_user_profile(resolved_user_id, {
        "subscription_tier": tier,
        "subscription_status": "active",
        "billing_provider": "shopify",
        "shopify_charge_id": charge_id,
    })
```

---

## 3. Root Cause

1. **Exception Swallowing & Control-Flow Fallthrough:** When `verify_and_activate_subscription()` failed (e.g. invalid charge ID, network timeout, Shopify GraphQL 500, non-existent subscription), the `except Exception as err:` block merely logged a warning and did not abort or return.
2. **Missing Token Fallthrough:** If the store record lacked an `access_token_encrypted`, verification was bypassed completely without raising an error.
3. **Absence of Status Gate:** The callback never validated that the Shopify subscription node had `status == "ACTIVE"` or `"ACCEPTED"`. Declined, pending, or cancelled charges were accepted.
4. **Client-Controlled Plan Tier:** The subscription tier was determined by the raw query parameter `plan_tier` (`tier = (plan_tier or "growth").lower()`). An attacker could supply `?plan_tier=enterprise` to elevate privilege at will.

---

## 4. Attack Scenario

1. **Attacker Reconnaissance:** An attacker registers a free/starter store on InboundCheck.
2. **Bypass Invocation:** Without paying or initiating a legitimate charge, the attacker invokes the callback URL directly:
   ```http
   GET /api/v1/shopify/billing/callback?charge_id=fake_charge_9999&plan_tier=enterprise&shop=attacker-store.myshopify.com&user_id=<attacker_uuid> HTTP/1.1
   Host: api.inboundcheck.com
   ```
3. **Execution Path:**
   - The endpoint verified that `attacker-store.myshopify.com` belonged to `<attacker_uuid>`.
   - `verify_and_activate_subscription` failed because `fake_charge_9999` did not exist in Shopify.
   - The exception was caught and logged as a warning.
   - Execution continued to line 291.
   - `supabase_service.update_user_profile` updated the attacker's profile to `subscription_tier = "enterprise"` and `subscription_status = "active"`.
4. **Impact:** Unlimited Enterprise tier capabilities (unlimited domains, high-frequency RBL scans, AI lab usage) granted for $0.

---

## 5. Trust Boundaries

| Entity | Trust Level | Values Provided | Verification Rule |
|---|---|---|---|
| **Shopify Admin API** | **Authoritative External Source** | `AppSubscription` GraphQL node (`id`, `status`, `name`) | Must be queried server-side using merchant's decrypted token. Status must be `"ACTIVE"` or `"ACCEPTED"`. |
| **Browser / Client Query Params** | **Untrusted Input** | `charge_id`, `plan_tier`, `shop`, `user_id` | **NEVER TRUST DIRECTLY.** `charge_id` must be validated via Shopify API. `plan_tier` cannot override the verified plan tier from Shopify. |
| **Merchant Store DB** | **Internal Secure Storage** | `access_token_encrypted`, `shop_domain` | Store must belong to the tenant. Token must exist and be decryptable. |
| **User Profile DB** | **Authoritative Tenant State** | `subscription_tier`, `subscription_status` | Updated **ONLY AFTER** all server-side verification gates succeed. |

---

## 6. Security Fix

### 1. Hardened Verification in `backend/app/services/shopify/shopify_billing_service.py`
- Added explicit inspection for top-level GraphQL errors in query responses (`"errors" in data`).
- Validated that `node` is non-null and possesses an active status (`status in ["ACTIVE", "ACCEPTED"]`).
- Explicitly raises `RuntimeError` on missing nodes or unapproved statuses (`DECLINED`, `PENDING`, `EXPIRED`, `CANCELLED`).

### 2. Zero-Fallthrough Callback Gate in `backend/app/api/v1/shopify.py`
- **Idempotency Gate:** Checks if the merchant profile is already active with the identical `charge_id`. If so, returns a success redirect without re-executing state transitions.
- **Access Token Requirement:** Rejects callbacks immediately with HTTP 400 if the store lacks an `access_token_encrypted`.
- **Zero Exception Fallthrough:** Wrapped verification in a strict try/except block where any error or exception immediately raises `HTTPException(400, "Shopify billing verification failed")`. Profile persistence is never reached on error.
- **Status Validation:** Confirms `sub_node.status in ["ACTIVE", "ACCEPTED"]` or raises HTTP 402 Payment Required (`"Shopify subscription is not active or was declined"`).
- **Plan Tier Binding:** Extracts the plan tier directly from the verified subscription name (`sub_node.get("name")`). If a merchant purchased a Growth plan, `verified_tier` is locked to `"growth"` regardless of whether the client query parameter requested `plan_tier=enterprise`.

---

## 7. Files Modified

1. [`backend/app/api/v1/shopify.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/shopify.py):
   - Overhauled `shopify_billing_callback()`: eliminated exception fallthrough, enforced access tokens, enforced active status, derived tier from verified subscription name, and added idempotency check.
2. [`backend/app/services/shopify/shopify_billing_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/shopify/shopify_billing_service.py):
   - Hardened `verify_and_activate_subscription()`: added GraphQL error checking and status validation.

---

## 8. Files Created

1. [`backend/tests/test_shopify_billing_security.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/tests/test_shopify_billing_security.py):
   - 17 adversarial security tests verifying all failure modes, exception containment, status validation, plan tier spoofing defense, idempotency, and error hygiene.

---

## 9. Database Changes

**None.**
The PostgreSQL schema and RLS policies already enforce `profiles.subscription_tier` and `auth.uid() = user_id`. No database migration was required.

---

## 10. Adversarial Test Results

```powershell
py -m pytest tests/test_shopify_billing_security.py -v
```

| Test Case | Scenario Tested | Result |
|---|---|---|
| `test_billing_verification_failure_does_not_upgrade_to_enterprise` | Shopify verification raises RuntimeError; asserts profile remains `starter` | **PASSED** |
| `test_shopify_api_exception_does_not_upgrade_to_enterprise` | Shopify GraphQL 503 outage; asserts profile remains `starter` | **PASSED** |
| `test_missing_billing_record_does_not_upgrade_to_enterprise` | Shopify returns `node: null`; asserts HTTP 400 and profile remains `starter` | **PASSED** |
| `test_invalid_billing_status_does_not_upgrade_to_enterprise[DECLINED]` | Charge status DECLINED; asserts HTTP 402 and profile remains `starter` | **PASSED** |
| `test_invalid_billing_status_does_not_upgrade_to_enterprise[PENDING]` | Charge status PENDING; asserts HTTP 402 and profile remains `starter` | **PASSED** |
| `test_invalid_billing_status_does_not_upgrade_to_enterprise[EXPIRED]` | Charge status EXPIRED; asserts HTTP 402 and profile remains `starter` | **PASSED** |
| `test_invalid_billing_status_does_not_upgrade_to_enterprise[FROZEN]` | Charge status FROZEN; asserts HTTP 402 and profile remains `starter` | **PASSED** |
| `test_invalid_billing_status_does_not_upgrade_to_enterprise[CANCELLED]` | Charge status CANCELLED; asserts HTTP 402 and profile remains `starter` | **PASSED** |
| `test_invalid_callback_does_not_upgrade_to_enterprise` | Missing `charge_id` or missing `shop`; asserts cancellation or HTTP 400 | **PASSED** |
| `test_wrong_merchant_cannot_activate_enterprise` | Attacker passing another tenant's store; asserts HTTP 403 | **PASSED** |
| `test_store_missing_access_token_cannot_upgrade` | Store without encrypted token; asserts HTTP 400 and profile remains `starter` | **PASSED** |
| `test_client_cannot_select_enterprise_tier` | Client buys Growth plan but passes `?plan_tier=enterprise`; asserts tier locked to `growth` | **PASSED** |
| `test_unverified_subscription_id_cannot_activate_enterprise` | Fabricated charge ID; asserts HTTP 400 and profile remains `starter` | **PASSED** |
| `test_successful_verified_billing_activates_correct_plan` | Legitimate verified charge; activates Enterprise and redirects to success | **PASSED** |
| `test_repeated_callback_is_idempotent` | Re-executing callback for active charge succeeds idempotently | **PASSED** |
| `test_billing_exception_returns_safe_error` | Sensitive database crash in billing service does not leak in response | **PASSED** |
| `test_no_sensitive_billing_data_in_error_response` | Access tokens (`shpat_`) never appear in error responses | **PASSED** |

**Total:** **17 passed in 17.11s (100% green)**

---

## 11. Full Regression Results

```powershell
py -m pytest tests/
```
**Result:** **216 passed in 101.28s (100% green, 0 failures, 0 regressions across all 216 test cases).**

---

## 12. Frontend Build Results

```powershell
cd frontend
npm run build
```
**Result:** **Compiled successfully; 25 of 25 static and dynamic pages generated with 0 errors.**

---

## 13. Repository-Wide Enterprise Upgrade Audit

A complete audit of all code paths modifying `subscription_tier` was conducted across `backend/app/`:

1. `backend/app/api/v1/shopify.py`: Hardened with multi-gate verification; zero fallthrough.
2. `backend/app/services/billing/stripe_service.py`: Modifies tier only upon cryptographically verified Stripe webhook events (`checkout.session.completed`, `customer.subscription.updated`) with HMAC-SHA256 signature verification.
3. `backend/app/api/v1/settings.py`: `update_user_profile()` strictly updates `full_name`, `email`, and `company_name`; rejects `subscription_tier` modifications.
4. `backend/app/core/tier_guards.py`: Only modifies status to `"expired"`; never grants privileged tiers.

**Audit Conclusion:** There are **zero** remaining unverified or client-controlled paths to `subscription_tier = "enterprise"`.

---

## 14. Before → After Control-Flow Diagram

### Before (Vulnerable)
```
[ Incoming Callback ]
         │
         ▼
[ Verify with Shopify ] ──(Throws Exception)──► [ Warning Logged ]
                                                        │
                                                        ▼ (FALLTHROUGH!)
                                                [ Update Profile: Enterprise ]
```

### After (Hardened)
```
[ Incoming Callback ]
         │
         ▼
[ Verify Shop & Tenant ] ──(Mismatch)──► HTTP 403 (Aborted)
         │
         ▼
[ Check Access Token ] ──(Missing)──► HTTP 400 (Aborted)
         │
         ▼
[ Verify with Shopify ] ──(Throws Exception / Net Error)──► HTTP 400 (Aborted)
         │
         ▼
[ Validate Node Status ] ──(Not ACTIVE / ACCEPTED)──► HTTP 402 (Aborted)
         │
         ▼
[ Extract Verified Tier from Node Name ] (Ignores client ?plan_tier=enterprise)
         │
         ▼
[ Update Profile with Verified Tier ]
         │
         ▼
[ Redirect: /dashboard/billing?billing=success ]
```

---

## 15. Remaining Phase 2.2 Risks & Monitoring

1. **Shopify Webhook Redundancy:** Shopify also sends `app_subscriptions/update` webhooks. Ongoing subscription lifecycle changes (cancellations/renewals) are handled via webhooks; the callback provides immediate synchronous onboarding.
2. **GraphQL Rate Limits:** Shopify GraphQL API costs 10 points per `node()` query with a bucket of 1,000 points. Callback volume is bounded by human merchant checkouts, well within Shopify thresholds.
