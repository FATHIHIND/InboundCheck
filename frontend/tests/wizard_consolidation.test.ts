import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { resolveWizardRoute } from "../src/lib/domain-selection";

describe("PHASE 26 — Zero-Spam Wizard Consolidation & Unified Route Governance", () => {
  describe("1. Centralized Wizard Route Resolution (resolveWizardRoute)", () => {
    it("resolves to base /dashboard/wizard when no parameters provided", () => {
      assert.strictEqual(resolveWizardRoute(), "/dashboard/wizard");
      assert.strictEqual(resolveWizardRoute({}), "/dashboard/wizard");
      assert.strictEqual(resolveWizardRoute({ domain: null, shop: null }), "/dashboard/wizard");
    });

    it("normalizes and sets ?domain= for explicit domain inputs", () => {
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com" }),
        "/dashboard/wizard?domain=brand.com"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "HTTPS://WWW.Brand.COM/checkout" }),
        "/dashboard/wizard?domain=brand.com"
      );
    });

    it("resolves ?shop= to ?domain= ensuring Shopify OAuth callback compatibility", () => {
      assert.strictEqual(
        resolveWizardRoute({ shop: "my-store.myshopify.com" }),
        "/dashboard/wizard?domain=my-store.myshopify.com"
      );
      assert.strictEqual(
        resolveWizardRoute({ shop: "https://my-store.myshopify.com/" }),
        "/dashboard/wizard?domain=my-store.myshopify.com"
      );
    });

    it("preserves valid step query parameters within [0, 7] boundary", () => {
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", step: 0 }),
        "/dashboard/wizard?domain=brand.com&step=0"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", step: 4 }),
        "/dashboard/wizard?domain=brand.com&step=4"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", step: 7 }),
        "/dashboard/wizard?domain=brand.com&step=7"
      );
    });

    it("ignores out-of-boundary or invalid step numbers", () => {
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", step: -1 }),
        "/dashboard/wizard?domain=brand.com"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", step: 8 }),
        "/dashboard/wizard?domain=brand.com"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", step: NaN }),
        "/dashboard/wizard?domain=brand.com"
      );
    });

    it("preserves safe relative return URLs while defeating open redirects", () => {
      // Safe internal paths
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", returnUrl: "/dashboard" }),
        "/dashboard/wizard?domain=brand.com&return_url=%2Fdashboard"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", returnUrl: "/dashboard/shopify" }),
        "/dashboard/wizard?domain=brand.com&return_url=%2Fdashboard%2Fshopify"
      );

      // Dangerous open-redirect attempts must be rejected
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", returnUrl: "https://evil.com" }),
        "/dashboard/wizard?domain=brand.com"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", returnUrl: "//evil.com" }),
        "/dashboard/wizard?domain=brand.com"
      );
      assert.strictEqual(
        resolveWizardRoute({ domain: "brand.com", returnUrl: "/\\evil.com" }),
        "/dashboard/wizard?domain=brand.com"
      );
    });
  });

  describe("2. Setup Wizard State Machine & Step Navigation", () => {
    // Model step transition boundaries
    function transitionStep(current: number, direction: "next" | "prev"): number {
      if (direction === "next") {
        return Math.min(7, current + 1);
      }
      return Math.max(0, current - 1);
    }

    it("navigates forward through all checks to activation (step 7)", () => {
      let step = 0; // Overview
      step = transitionStep(step, "next"); // Step 1: custom_sending_domain
      assert.strictEqual(step, 1);
      step = transitionStep(step, "next"); // Step 2: shopify_dkim
      assert.strictEqual(step, 2);
      step = transitionStep(step, "next"); // Step 3: spf_alignment
      assert.strictEqual(step, 3);
      step = transitionStep(step, "next"); // Step 4: dmarc_policy
      assert.strictEqual(step, 4);
      step = transitionStep(step, "next"); // Step 5: spf_conflict
      assert.strictEqual(step, 5);
      step = transitionStep(step, "next"); // Step 6: shared_pool_exposure
      assert.strictEqual(step, 6);
      step = transitionStep(step, "next"); // Step 7: activation
      assert.strictEqual(step, 7);

      // Clamps at step 7
      step = transitionStep(step, "next");
      assert.strictEqual(step, 7);
    });

    it("navigates backward to overview (step 0) and clamps at 0", () => {
      let step = 7;
      step = transitionStep(step, "prev");
      assert.strictEqual(step, 6);
      step = transitionStep(step, "prev");
      assert.strictEqual(step, 5);
      step = 1;
      step = transitionStep(step, "prev");
      assert.strictEqual(step, 0);

      // Clamps at step 0
      step = transitionStep(step, "prev");
      assert.strictEqual(step, 0);
    });
  });

  describe("3. Dynamic Return Destination and Label Resolution", () => {
    function resolveReturnDestination(returnUrlParam?: string | null) {
      const returnUrl = (returnUrlParam && returnUrlParam.startsWith("/") && !returnUrlParam.startsWith("//") && !returnUrlParam.includes("\\"))
        ? returnUrlParam
        : "/dashboard/shopify";

      const label = returnUrl === "/dashboard" ? "Dashboard" : "Store Fleet";
      return { returnUrl, label };
    }

    it("defaults return destination to Store Fleet (/dashboard/shopify) when unspecified", () => {
      const res = resolveReturnDestination(null);
      assert.strictEqual(res.returnUrl, "/dashboard/shopify");
      assert.strictEqual(res.label, "Store Fleet");
    });

    it("resolves to Dashboard (/dashboard) when return_url=/dashboard", () => {
      const res = resolveReturnDestination("/dashboard");
      assert.strictEqual(res.returnUrl, "/dashboard");
      assert.strictEqual(res.label, "Dashboard");
    });

    it("rejects protocol-relative open-redirect attempts and falls back safely", () => {
      const res = resolveReturnDestination("//attacker.com");
      assert.strictEqual(res.returnUrl, "/dashboard/shopify");
      assert.strictEqual(res.label, "Store Fleet");
    });
  });
});
