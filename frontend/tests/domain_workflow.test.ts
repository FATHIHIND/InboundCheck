import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  resolveActiveDomainCandidate,
  formatStoreDisplay,
  canDisplayStoreFinancialMetrics,
  resolvePipelineTargetDomain,
} from "../src/lib/domain-selection";
import { formatApiErrorMessage } from "../src/lib/apiResource";

describe("PHASE 19.6.6 — Domain-First Workflow & Shopify Decoupling", () => {
  describe("1. Active Domain Candidate Resolution", () => {
    it("prioritizes explicit valid query parameter over registered domains", () => {
      const candidate = resolveActiveDomainCandidate(
        "query-store.com",
        [{ domain_name: "registered-alpha.com" }, { domain_name: "registered-beta.com" }]
      );
      assert.strictEqual(candidate.domain, "query-store.com");
      assert.strictEqual(candidate.source, "query");
    });

    it("normalizes mixed-case, protocol, userinfo, and trailing slashes in query param", () => {
      const candidate = resolveActiveDomainCandidate(
        "https://USER:PASS@WWW.QUERY-STORE.COM:8080/path?tab=radar#frag",
        ["fallback.com"]
      );
      assert.strictEqual(candidate.domain, "query-store.com");
      assert.strictEqual(candidate.source, "query");
    });

    it("falls back to the first valid registered domain when query param is absent or empty", () => {
      const candidateWithoutQuery = resolveActiveDomainCandidate(
        "",
        [{ domain_name: "registered-primary.com" }, { domain_name: "registered-secondary.com" }]
      );
      assert.strictEqual(candidateWithoutQuery.domain, "registered-primary.com");
      assert.strictEqual(candidateWithoutQuery.source, "registry");

      const candidateWithNull = resolveActiveDomainCandidate(
        null,
        ["plain-string-domain.com"]
      );
      assert.strictEqual(candidateWithNull.domain, "plain-string-domain.com");
      assert.strictEqual(candidateWithNull.source, "registry");
    });

    it("returns empty string and 'none' source when user has 0 registered domains and no query param", () => {
      const candidate = resolveActiveDomainCandidate(null, []);
      assert.strictEqual(candidate.domain, "");
      assert.strictEqual(candidate.source, "none");
    });
  });

  describe("2. Store Display & Synthetic Handle Prevention", () => {
    it("returns 'Domain Only' when shopifyStore is empty, null, or undefined", () => {
      const resNull = formatStoreDisplay("mycompany.com", null);
      assert.strictEqual(resNull.isLinkedToStore, false);
      assert.strictEqual(resNull.storeBadgeLabel, "Domain Only");
      assert.strictEqual(resNull.storeDomain, null);

      const resEmpty = formatStoreDisplay("mycompany.com", "");
      assert.strictEqual(resEmpty.isLinkedToStore, false);
      assert.strictEqual(resEmpty.storeBadgeLabel, "Domain Only");
    });

    it("detects and rejects synthetically generated ${domain}.myshopify.com handles", () => {
      const syntheticHandle = "mycompany.myshopify.com";
      const res = formatStoreDisplay("mycompany.com", syntheticHandle);
      assert.strictEqual(
        res.isLinkedToStore,
        false,
        "Must not treat synthetic domain-based handle as a verified store link"
      );
      assert.strictEqual(res.storeBadgeLabel, "Domain Only");
      assert.strictEqual(res.storeDomain, null);
    });

    it("displays authentic store handle when domain is legitimately connected to a store", () => {
      const authenticStore = "actual-apparel-store.myshopify.com";
      const res = formatStoreDisplay("differentbrand.com", authenticStore);
      assert.strictEqual(res.isLinkedToStore, true);
      assert.strictEqual(res.storeBadgeLabel, "actual-apparel-store.myshopify.com");
      assert.strictEqual(res.storeDomain, "actual-apparel-store.myshopify.com");
    });
  });

  describe("3. Financial GMV Protection Metrics Gating", () => {
    it("disallows presenting financial GMV metrics as real data when store count is 0", () => {
      const canDisplay = canDisplayStoreFinancialMetrics(0, false);
      assert.strictEqual(canDisplay, false, "Must not display real GMV metrics without a store connection");
    });

    it("disallows presenting financial GMV metrics during loading or store fetch error (0 or negative stores)", () => {
      assert.strictEqual(canDisplayStoreFinancialMetrics(0, false), false);
      assert.strictEqual(canDisplayStoreFinancialMetrics(-1, false), false);
    });

    it("permits presenting financial GMV metrics when at least one store is connected", () => {
      const canDisplay = canDisplayStoreFinancialMetrics(1, false);
      assert.strictEqual(canDisplay, true);
    });

    it("permits presenting GMV metrics when interactive demo mode is explicitly active", () => {
      const canDisplay = canDisplayStoreFinancialMetrics(0, true);
      assert.strictEqual(canDisplay, true, "Interactive simulation demo mode is permitted");
    });
  });

  describe("4. Pipeline Target Domain Resolution & Ownership Guard", () => {
    it("accepts active domain when it matches a valid domain in the authenticated registry", () => {
      const target = resolvePipelineTargetDomain("userbrand.com", [
        { domain_name: "userbrand.com" },
        { domain_name: "otherbrand.com" },
      ]);
      assert.strictEqual(target, "userbrand.com");
    });

    it("falls back to the first valid registered domain when active domain is absent from registry", () => {
      const target = resolvePipelineTargetDomain("unregistered-brand.com", [
        { domain_name: "verifiedbrand.com" },
        { domain_name: "secondarybrand.com" },
      ]);
      assert.strictEqual(
        target,
        "verifiedbrand.com",
        "Must select a valid registered domain when active domain is unverified"
      );
    });

    it("falls back to valid registered domain when active domain is invalid or empty", () => {
      const targetInvalid = resolvePipelineTargetDomain("invalid..domain", [
        { domain_name: "fallbackbrand.com" },
      ]);
      assert.strictEqual(targetInvalid, "fallbackbrand.com");

      const targetEmpty = resolvePipelineTargetDomain("", [
        { domain_name: "fallbackbrand.com" },
      ]);
      assert.strictEqual(targetEmpty, "fallbackbrand.com");
    });

    it("returns null when registry is empty, even if an active domain was supplied", () => {
      const targetWithActive = resolvePipelineTargetDomain("unowned.com", []);
      assert.strictEqual(targetWithActive, null, "Must return null when user has no registered domains");

      const targetWithNull = resolvePipelineTargetDomain(null, []);
      assert.strictEqual(targetWithNull, null);

      const targetWithUndefined = resolvePipelineTargetDomain(undefined, []);
      assert.strictEqual(targetWithUndefined, null);
    });

    it("returns null when registry contains only invalid or synthetic domains", () => {
      const targetSynthetic = resolvePipelineTargetDomain("unowned.com", [
        { domain_name: "myshopify.com" },
        { domain_name: "invalid..domain" },
      ]);
      assert.strictEqual(targetSynthetic, null, "Must reject registry containing only synthetic or malformed domains");
    });

    it("never returns 'myshopify.com' as a target under any condition", () => {
      assert.strictEqual(resolvePipelineTargetDomain("myshopify.com", []), null);
      assert.strictEqual(resolvePipelineTargetDomain("myshopify.com", [{ domain_name: "myshopify.com" }]), null);
      assert.strictEqual(resolvePipelineTargetDomain(null, [{ domain_name: "myshopify.com" }]), null);
    });

    it("normalizes case and protocols when matching active domain against registry", () => {
      const target = resolvePipelineTargetDomain("HTTPS://MYSTORE.COM/", [
        { domain_name: "mystore.com" },
      ]);
      assert.strictEqual(target, "mystore.com");
    });

    it("stops pipeline and prevents any scan request when registry has no valid domain", async () => {
      let scanCalled = false;
      let pipelineError: string | null = null;

      const mockRunPipeline = async (activeDomain: string | null, currentStores: any[]) => {
        const targetDomain = resolvePipelineTargetDomain(activeDomain, currentStores);
        if (!targetDomain) {
          pipelineError =
            "No monitored sending domain found. Please register a sending domain first before running the diagnostic pipeline.";
          return;
        }
        scanCalled = true;
      };

      await mockRunPipeline("unregistered.com", []);
      assert.strictEqual(scanCalled, false, "Scan must never be dispatched when registry is empty");
      assert.strictEqual(
        pipelineError,
        "No monitored sending domain found. Please register a sending domain first before running the diagnostic pipeline."
      );
    });
  });

  describe("5. Domain Registration Failure & Error State Handling", () => {
    it("formats API string error message correctly", () => {
      const formatted = formatApiErrorMessage("Domain already registered by another account");
      assert.strictEqual(formatted, "Domain already registered by another account");
    });

    it("formats API object error details into human-readable string", () => {
      const formatted = formatApiErrorMessage({ detail: "SSRF protection: loopback addresses prohibited" });
      assert.strictEqual(formatted, "SSRF protection: loopback addresses prohibited");
    });

    it("falls back to generic error message when error detail is empty or malformed", () => {
      const formatted = formatApiErrorMessage(null, "Failed to register domain");
      assert.strictEqual(formatted, "Failed to register domain");
    });
  });
});
