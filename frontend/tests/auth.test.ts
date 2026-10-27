import test from "node:test";
import assert from "node:assert/strict";
import {
  getCanonicalSiteUrl,
  isAllowedHost,
  isLocalhost,
  normalizeHostname,
  resolveCallbackOrigin,
  getClientAuthCallbackUrl,
  sanitizeInternalRedirect,
  DEFAULT_PRODUCTION_SITE_URL,
} from "../src/lib/auth-origin.ts";

test("PHASE 19.5.5 — Hardened Authentication Origin & Canonical URL Governance", async (t) => {
  const originalEnv = { ...process.env };

  t.afterEach(() => {
    process.env = { ...originalEnv };
    if (typeof globalThis.window !== "undefined") {
      delete (globalThis as any).window;
    }
  });

  await t.test("1. Canonical site URL defaults to https://inboundcheck.com when unconfigured or empty", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);

    process.env.NEXT_PUBLIC_SITE_URL = "";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);

    process.env.NEXT_PUBLIC_SITE_URL = "   ";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);

    process.env.NEXT_PUBLIC_SITE_URL = "undefined";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);
  });

  await t.test("2. Canonical site URL rejects arbitrary hostnames and falls back to default", () => {
    // Malicious or unapproved external domains
    process.env.NEXT_PUBLIC_SITE_URL = "https://evil-attacker.com";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);

    process.env.NEXT_PUBLIC_SITE_URL = "https://inboundcheck.com.attacker.com";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);

    process.env.NEXT_PUBLIC_SITE_URL = "https://inbound-check-theta.vercel.app";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);
  });

  await t.test("3. Canonical site URL rejects plaintext HTTP production URLs", () => {
    // Plaintext HTTP downgrade on production domains must be rejected
    process.env.NEXT_PUBLIC_SITE_URL = "http://inboundcheck.com";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);

    process.env.NEXT_PUBLIC_SITE_URL = "http://www.inboundcheck.com";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);
  });

  await t.test("4. Canonical site URL strips credentials, subpaths, queries, and fragments", () => {
    // URL with basic auth credentials, path, query, and hash
    process.env.NEXT_PUBLIC_SITE_URL = "https://user:password@inboundcheck.com:443/nested/path?tab=settings#hash";
    assert.equal(getCanonicalSiteUrl(), "https://inboundcheck.com");

    process.env.NEXT_PUBLIC_SITE_URL = "https://www.inboundcheck.com/app/";
    assert.equal(getCanonicalSiteUrl(), "https://www.inboundcheck.com");
  });

  await t.test("5. Canonical site URL normalizes mixed-case and trailing-dot hostnames", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://INBOUNDCHECK.COM/";
    assert.equal(getCanonicalSiteUrl(), "https://inboundcheck.com");

    process.env.NEXT_PUBLIC_SITE_URL = "https://inboundcheck.com./";
    assert.equal(getCanonicalSiteUrl(), "https://inboundcheck.com");

    process.env.NEXT_PUBLIC_SITE_URL = "https://WwW.InboundCheck.Com:443/";
    assert.equal(getCanonicalSiteUrl(), "https://www.inboundcheck.com");
  });

  await t.test("6. Canonical site URL preserves localhost development while rejecting arbitrary HTTP origins", () => {
    // Legitimate local development
    process.env.NEXT_PUBLIC_SITE_URL = "http://localhost:3000";
    assert.equal(getCanonicalSiteUrl(), "http://localhost:3000");

    process.env.NEXT_PUBLIC_SITE_URL = "http://127.0.0.1:8000/";
    assert.equal(getCanonicalSiteUrl(), "http://127.0.0.1:8000");

    process.env.NEXT_PUBLIC_SITE_URL = "https://localhost:3443";
    assert.equal(getCanonicalSiteUrl(), "https://localhost:3443");

    // Arbitrary non-local HTTP must fail closed
    process.env.NEXT_PUBLIC_SITE_URL = "http://evil-site.com";
    assert.equal(getCanonicalSiteUrl(), DEFAULT_PRODUCTION_SITE_URL);
  });

  await t.test("7. Host allow-list strictly permits production domains and localhost only", () => {
    assert.equal(isAllowedHost("inboundcheck.com"), true);
    assert.equal(isAllowedHost("www.inboundcheck.com"), true);
    assert.equal(isAllowedHost("INBOUNDCHECK.COM"), true);
    assert.equal(isAllowedHost("inboundcheck.com."), true);
    assert.equal(isAllowedHost("inboundcheck.com:443"), true);
    assert.equal(isAllowedHost("localhost"), true);
    assert.equal(isAllowedHost("localhost:3000"), true);
    assert.equal(isAllowedHost("127.0.0.1:8000"), true);

    // Untrusted or internal deployment hosts must be rejected
    assert.equal(isAllowedHost("inbound-check-theta.vercel.app"), false);
    assert.equal(isAllowedHost("attacker.com"), false);
    assert.equal(isAllowedHost("evil.inboundcheck.com"), false);
    assert.equal(isAllowedHost("inboundcheck.com.attacker.com"), false);
  });

  await t.test("8. resolveCallbackOrigin normalizes production hosts and strips redundant port 443", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    // Port 443 on production domain must be stripped to match Supabase redirect whitelist
    const reqPort443 = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "inboundcheck.com:443",
        "x-forwarded-proto": "https",
      },
    });
    assert.equal(resolveCallbackOrigin(reqPort443), "https://inboundcheck.com");

    // Mixed case and trailing dot in header
    const reqMixedDot = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "InboundCheck.Com.:443",
        "x-forwarded-proto": "https",
      },
    });
    assert.equal(resolveCallbackOrigin(reqMixedDot), "https://inboundcheck.com");

    // Attempted plaintext downgrade on production host must be forced to https
    const reqDowngrade = new Request("http://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "inboundcheck.com",
        "x-forwarded-proto": "http",
      },
    });
    assert.equal(resolveCallbackOrigin(reqDowngrade), "https://inboundcheck.com");
  });

  await t.test("9. resolveCallbackOrigin rejects ambiguous comma-separated forwarded-host values", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    // Multi-hop comma-separated value (ambiguous/untrusted) must safely fall back to canonical URL
    const reqComma = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "inboundcheck.com, proxy.example.com",
        "x-forwarded-proto": "https",
      },
    });
    assert.equal(resolveCallbackOrigin(reqComma), "https://inboundcheck.com");

    const reqCommaAttacker = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "attacker.com, inboundcheck.com",
        "x-forwarded-proto": "https",
      },
    });
    assert.equal(resolveCallbackOrigin(reqCommaAttacker), "https://inboundcheck.com");
  });

  await t.test("10. resolveCallbackOrigin rejects untrusted hosts and preview domains", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    // Internal Vercel deployment hostname
    const reqVercel = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "inbound-check-theta.vercel.app",
        "x-forwarded-proto": "https",
      },
    });
    assert.equal(resolveCallbackOrigin(reqVercel), "https://inboundcheck.com");

    // Spoofed attacker host
    const reqEvil = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "evil-phishing-site.com",
        "x-forwarded-proto": "https",
      },
    });
    assert.equal(resolveCallbackOrigin(reqEvil), "https://inboundcheck.com");

    // Missing forwarded headers on Vercel deployment
    const reqNoHeader = new Request("https://inbound-check-theta.vercel.app/auth/callback?code=123");
    assert.equal(resolveCallbackOrigin(reqNoHeader), "https://inboundcheck.com");
  });

  await t.test("11. resolveCallbackOrigin preserves localhost development with and without headers", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    // Localhost with port in header
    const reqLocalHeader = new Request("http://localhost:3000/auth/callback?code=123", {
      headers: {
        "x-forwarded-host": "localhost:3000",
        "x-forwarded-proto": "http",
      },
    });
    assert.equal(resolveCallbackOrigin(reqLocalHeader), "http://localhost:3000");

    // Direct localhost request without headers
    const reqDirectLocal = new Request("http://localhost:3000/auth/callback?code=123");
    assert.equal(resolveCallbackOrigin(reqDirectLocal), "http://localhost:3000");

    // Loopback 127.0.0.1 without headers
    const reqLoopback = new Request("http://127.0.0.1:8000/auth/callback?code=123");
    assert.equal(resolveCallbackOrigin(reqLoopback), "http://127.0.0.1:8000");
  });

  await t.test("12. getClientAuthCallbackUrl resolves correctly across environments", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    // Node / SSR environment without window
    assert.equal(getClientAuthCallbackUrl(), "https://inboundcheck.com/auth/callback");
    assert.equal(
      getClientAuthCallbackUrl("/auth/reset-password"),
      "https://inboundcheck.com/auth/callback?next=%2Fauth%2Freset-password"
    );

    // Browser on localhost
    (globalThis as any).window = {
      location: {
        origin: "http://localhost:3000",
        hostname: "localhost",
      },
    };
    assert.equal(getClientAuthCallbackUrl(), "http://localhost:3000/auth/callback");

    // Browser on Vercel preview domain
    (globalThis as any).window = {
      location: {
        origin: "https://inbound-check-theta.vercel.app",
        hostname: "inbound-check-theta.vercel.app",
      },
    };
    // Must strictly route to canonical production site to match Supabase allow-list
    assert.equal(getClientAuthCallbackUrl(), "https://inboundcheck.com/auth/callback");
  });

  await t.test("13. sanitizeInternalRedirect enforces strict internal path safety and defeats open redirects", () => {
    // Valid internal paths
    assert.equal(sanitizeInternalRedirect("/dashboard"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("/dashboard/inspector"), "/dashboard/inspector");
    assert.equal(sanitizeInternalRedirect("/dashboard?tab=billing#invoices"), "/dashboard?tab=billing#invoices");
    assert.equal(sanitizeInternalRedirect(null), "/dashboard");
    assert.equal(sanitizeInternalRedirect(""), "/dashboard");

    // Protocol-relative evasion (//evil.com)
    assert.equal(sanitizeInternalRedirect("//evil.com"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("//inboundcheck.com.attacker.com"), "/dashboard");

    // Backslash evasion (/\\evil.com and /\\evil.com)
    assert.equal(sanitizeInternalRedirect("/\\evil.com"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("/\\\\evil.com"), "/dashboard");

    // Absolute URLs
    assert.equal(sanitizeInternalRedirect("https://evil.com"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("http://evil.com/dashboard"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("javascript:alert(1)"), "/dashboard");

    // Control characters or CRLF injection
    assert.equal(sanitizeInternalRedirect("/dashboard\r\nSet-Cookie: evil=1"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("/dashboard\x00"), "/dashboard");
    assert.equal(sanitizeInternalRedirect("/dashboard with space"), "/dashboard");
  });

  await t.test("14. Signup confirmation emailRedirectTo matches canonical auth callback contract", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    // Node / SSR environment without window
    const ssrCallback = getClientAuthCallbackUrl();
    assert.equal(ssrCallback, "https://inboundcheck.com/auth/callback");

    // Localhost browser development environment
    (globalThis as any).window = {
      location: {
        origin: "http://localhost:3000",
        hostname: "localhost",
      },
    };
    const localCallback = getClientAuthCallbackUrl();
    assert.equal(localCallback, "http://localhost:3000/auth/callback");

    // Production custom domain
    (globalThis as any).window = {
      location: {
        origin: "https://inboundcheck.com",
        hostname: "inboundcheck.com",
      },
    };
    const prodCallback = getClientAuthCallbackUrl();
    assert.equal(prodCallback, "https://inboundcheck.com/auth/callback");

    // Untrusted or preview environment strictly falls back to canonical production callback
    (globalThis as any).window = {
      location: {
        origin: "https://inboundcheck-preview-pr-42.vercel.app",
        hostname: "inboundcheck-preview-pr-42.vercel.app",
      },
    };
    const previewCallback = getClientAuthCallbackUrl();
    assert.equal(previewCallback, "https://inboundcheck.com/auth/callback");
  });
});
