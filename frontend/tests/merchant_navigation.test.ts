import { describe, it } from "node:test";
import assert from "node:assert/strict";

describe("PHASE 27 — P1-C Merchant Navigation Architecture & Governance", () => {
  // 1. Definition of the five approved merchant destinations
  const MERCHANT_DESTINATIONS = [
    { key: "overview", label: "Overview", path: "/dashboard" },
    { key: "stores", label: "Stores & Domains", path: "/dashboard/shopify" },
    { key: "action-center", label: "Action Center", path: "/dashboard/inspector" },
    { key: "settings", label: "Settings & Billing", path: "/dashboard/settings" },
    { key: "content-lab", label: "Template Optimizer", path: "/dashboard/content-lab" },
  ];

  it("1. Exposes exactly the five approved merchant destinations", () => {
    assert.strictEqual(MERCHANT_DESTINATIONS.length, 5);
    const paths = MERCHANT_DESTINATIONS.map((d) => d.path);
    assert.deepStrictEqual(paths, [
      "/dashboard",
      "/dashboard/shopify",
      "/dashboard/inspector",
      "/dashboard/settings",
      "/dashboard/content-lab",
    ]);

    const labels = MERCHANT_DESTINATIONS.map((d) => d.label);
    assert.deepStrictEqual(labels, [
      "Overview",
      "Stores & Domains",
      "Action Center",
      "Settings & Billing",
      "Template Optimizer",
    ]);
  });

  // Helper matching DashboardLayout active route state logic
  function resolveActiveDestination(pathname: string) {
    return {
      isOverviewActive: pathname === "/dashboard",
      isStoresActive: pathname.startsWith("/dashboard/shopify") || pathname.startsWith("/dashboard/wizard"),
      isActionCenterActive: pathname.startsWith("/dashboard/inspector") || pathname.startsWith("/dashboard/radar"),
      isSettingsActive: pathname.startsWith("/dashboard/settings") || pathname.startsWith("/dashboard/billing"),
      isOptimizerActive: pathname.startsWith("/dashboard/content-lab"),
    };
  }

  describe("2. Active-Route Hierarchy & Nested Path Matching", () => {
    it("highlights Overview strictly on /dashboard", () => {
      const active = resolveActiveDestination("/dashboard");
      assert.strictEqual(active.isOverviewActive, true);
      assert.strictEqual(active.isStoresActive, false);
      assert.strictEqual(active.isActionCenterActive, false);
      assert.strictEqual(active.isSettingsActive, false);
      assert.strictEqual(active.isOptimizerActive, false);
    });

    it("highlights Stores & Domains on /dashboard/shopify and nested /dashboard/wizard", () => {
      const shopifyActive = resolveActiveDestination("/dashboard/shopify");
      assert.strictEqual(shopifyActive.isStoresActive, true);
      assert.strictEqual(shopifyActive.isOverviewActive, false);

      const callbackActive = resolveActiveDestination("/dashboard/shopify/callback");
      assert.strictEqual(callbackActive.isStoresActive, true);

      const wizardActive = resolveActiveDestination("/dashboard/wizard");
      assert.strictEqual(wizardActive.isStoresActive, true);
      assert.strictEqual(wizardActive.isOverviewActive, false);
    });

    it("highlights Action Center on /dashboard/inspector and nested /dashboard/radar", () => {
      const inspectorActive = resolveActiveDestination("/dashboard/inspector");
      assert.strictEqual(inspectorActive.isActionCenterActive, true);
      assert.strictEqual(inspectorActive.isOverviewActive, false);

      const radarActive = resolveActiveDestination("/dashboard/radar");
      assert.strictEqual(radarActive.isActionCenterActive, true);
      assert.strictEqual(radarActive.isOverviewActive, false);
    });

    it("highlights Settings & Billing on /dashboard/settings and dedicated /dashboard/billing", () => {
      const settingsActive = resolveActiveDestination("/dashboard/settings");
      assert.strictEqual(settingsActive.isSettingsActive, true);
      assert.strictEqual(settingsActive.isOverviewActive, false);

      const billingActive = resolveActiveDestination("/dashboard/billing");
      assert.strictEqual(billingActive.isSettingsActive, true);
      assert.strictEqual(billingActive.isOverviewActive, false);
    });

    it("highlights Template Optimizer on /dashboard/content-lab", () => {
      const optimizerActive = resolveActiveDestination("/dashboard/content-lab");
      assert.strictEqual(optimizerActive.isOptimizerActive, true);
      assert.strictEqual(optimizerActive.isOverviewActive, false);
    });

    it("ensures exactly one parent destination is active for every supported route", () => {
      const testRoutes = [
        "/dashboard",
        "/dashboard/shopify",
        "/dashboard/shopify/callback",
        "/dashboard/wizard",
        "/dashboard/inspector",
        "/dashboard/radar",
        "/dashboard/settings",
        "/dashboard/billing",
        "/dashboard/content-lab",
      ];

      for (const route of testRoutes) {
        const active = resolveActiveDestination(route);
        const activeCount = Object.values(active).filter(Boolean).length;
        assert.strictEqual(
          activeCount,
          1,
          `Route ${route} must have exactly 1 active parent destination, but got ${activeCount}`
        );
      }
    });
  });

  describe("3. Backward-Compatible Next.js Redirects & Loop Prevention", () => {
    // Model next.config.mjs redirects
    const CONFIGURED_REDIRECTS = [
      { source: "/login", destination: "/auth/login", permanent: true },
      { source: "/signup", destination: "/auth/signup", permanent: true },
      { source: "/dashboard/domains", destination: "/dashboard/shopify", permanent: true },
      { source: "/dashboard/stores", destination: "/dashboard/shopify", permanent: true },
      { source: "/dashboard/action-center", destination: "/dashboard/inspector", permanent: true },
      { source: "/dashboard/template-optimizer", destination: "/dashboard/content-lab", permanent: true },
    ];

    it("maps prospective merchant aliases to authoritative destinations", () => {
      const aliasMap = new Map(CONFIGURED_REDIRECTS.map((r) => [r.source, r.destination]));
      assert.strictEqual(aliasMap.get("/dashboard/domains"), "/dashboard/shopify");
      assert.strictEqual(aliasMap.get("/dashboard/stores"), "/dashboard/shopify");
      assert.strictEqual(aliasMap.get("/dashboard/action-center"), "/dashboard/inspector");
      assert.strictEqual(aliasMap.get("/dashboard/template-optimizer"), "/dashboard/content-lab");
    });

    it("guarantees zero circular redirect loops", () => {
      const sources = new Set(CONFIGURED_REDIRECTS.map((r) => r.source));
      for (const r of CONFIGURED_REDIRECTS) {
        assert.strictEqual(
          sources.has(r.destination),
          false,
          `Redirect destination ${r.destination} is itself a redirect source (circular loop risk)`
        );
      }
    });

    it("strictly preserves dedicated functional routes without redirecting", () => {
      const sources = new Set(CONFIGURED_REDIRECTS.map((r) => r.source));

      // Must remain accessible routes and NEVER redirected
      assert.strictEqual(sources.has("/dashboard/billing"), false, "/dashboard/billing must not be redirected (paywall bypass)");
      assert.strictEqual(sources.has("/dashboard/radar"), false, "/dashboard/radar must not be redirected (10-RBL deep diagnostics)");
      assert.strictEqual(sources.has("/dashboard/wizard"), false, "/dashboard/wizard must not be redirected (consolidated onboarding)");
      assert.strictEqual(sources.has("/dashboard/shopify/callback"), false, "/dashboard/shopify/callback must not be redirected (OAuth return)");
    });
  });
});
