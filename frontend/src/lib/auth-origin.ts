/**
 * InboundCheck Authentication Origin & Redirect Governance
 * =========================================================
 * Provides deterministic, security-hardened origin resolution and open-redirect
 * defense for OAuth callbacks, password resets, and session redirects.
 */

// Canonical production site URL
export const DEFAULT_PRODUCTION_SITE_URL = "https://inboundcheck.com";

// Allowed production custom hostnames
export const ALLOWED_PRODUCTION_HOSTS = new Set([
  "inboundcheck.com",
  "www.inboundcheck.com",
]);

/**
 * Normalizes a raw hostname string by trimming, lowering case,
 * stripping trailing dots (DNS FQDN), and removing port if present.
 */
export function normalizeHostname(raw: string): string {
  if (!raw) return "";
  const withoutPort = raw.trim().split(":")[0];
  return withoutPort.toLowerCase().replace(/\.+$/, "");
}

/**
 * Checks whether a given hostname is a local development host.
 */
export function isLocalhost(hostname: string): boolean {
  const clean = normalizeHostname(hostname);
  return clean === "localhost" || clean === "127.0.0.1";
}

/**
 * Validates whether a forwarded host belongs to the strict production or development allow-list.
 */
export function isAllowedHost(hostWithOptionalPort: string): boolean {
  if (!hostWithOptionalPort) return false;
  const clean = normalizeHostname(hostWithOptionalPort);
  return ALLOWED_PRODUCTION_HOSTS.has(clean) || isLocalhost(clean);
}

/**
 * Returns the configured canonical site URL.
 *
 * Security rules:
 * 1. Parses NEXT_PUBLIC_SITE_URL with new URL().
 * 2. If localhost development, permits http: or https: with local host/loopback only.
 * 3. In production, accepts ONLY https: protocol and hostnames strictly in ALLOWED_PRODUCTION_HOSTS.
 * 4. Strips any credentials, subpaths, queries, fragments, or redundant default ports (returns parsed.origin).
 * 5. Fails closed to DEFAULT_PRODUCTION_SITE_URL (https://inboundcheck.com) on any violation.
 */
export function getCanonicalSiteUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_SITE_URL;
  if (envUrl && envUrl.trim() !== "" && !envUrl.includes("undefined")) {
    try {
      const parsed = new URL(envUrl.trim());
      const hostname = normalizeHostname(parsed.hostname);

      // Localhost development: allow http/https on localhost/127.0.0.1
      if (isLocalhost(hostname)) {
        if (parsed.protocol === "http:" || parsed.protocol === "https:") {
          const portPart = parsed.port ? `:${parsed.port}` : "";
          return `${parsed.protocol}//${hostname}${portPart}`;
        }
        return DEFAULT_PRODUCTION_SITE_URL;
      }

      // Production: must be https: and in approved production hosts
      if (parsed.protocol === "https:" && ALLOWED_PRODUCTION_HOSTS.has(hostname)) {
        return `https://${hostname}`;
      }
    } catch {
      // Fall through to default on invalid URL
    }
  }
  return DEFAULT_PRODUCTION_SITE_URL;
}

/**
 * Resolves the canonical public-facing origin for server-side route handlers
 * (such as /auth/callback) behind reverse proxies (Vercel, Cloudflare, etc.).
 *
 * Security rules:
 * 1. Checks x-forwarded-host header.
 * 2. Rejects ambiguous or malformed values (e.g. comma-separated multiple proxy hops).
 * 3. Normalizes hostname (stripping ports and trailing dots).
 * 4. If approved production host, returns clean HTTPS origin: https://<cleanHostname>.
 * 5. If localhost development, preserves local scheme and port.
 * 6. In all other cases (untrusted, preview *.vercel.app, spoofed), falls back strictly
 *    to getCanonicalSiteUrl() (https://inboundcheck.com).
 */
export function resolveCallbackOrigin(request: Request): string {
  const rawForwardedHost = request.headers.get("x-forwarded-host");
  const forwardedProto = request.headers.get("x-forwarded-proto") || "https";

  if (rawForwardedHost) {
    const trimmed = rawForwardedHost.trim();
    // Reject ambiguous comma-separated multi-hop values
    if (!trimmed.includes(",") && isAllowedHost(trimmed)) {
      const cleanHost = normalizeHostname(trimmed);
      if (isLocalhost(cleanHost)) {
        // Localhost development: preserve port if specified, and protocol
        const proto = forwardedProto === "https" ? "https" : "http";
        return `${proto}://${trimmed}`.replace(/\/+$/, "");
      }
      if (ALLOWED_PRODUCTION_HOSTS.has(cleanHost)) {
        // Production: strictly https and clean normalized hostname without redundant port
        return `https://${cleanHost}`;
      }
    }
  }

  // Fallback to request.url origin ONLY if it is a verified local dev host
  try {
    const parsed = new URL(request.url);
    if (isLocalhost(parsed.hostname)) {
      return parsed.origin;
    }
  } catch {
    // Ignore URL parse failures and fall back to canonical
  }

  return getCanonicalSiteUrl();
}

/**
 * Resolves the exact redirectTo URL for browser-side OAuth initiation.
 *
 * Rules:
 * 1. If running in browser on localhost or 127.0.0.1, uses window.location.origin.
 * 2. In all other environments (production apex, www, or Vercel preview/default hosts),
 *    returns the canonical production site URL to match Supabase's redirect allow-list.
 */
export function getClientAuthCallbackUrl(nextPath?: string): string {
  const safeNext = nextPath ? sanitizeInternalRedirect(nextPath) : null;
  const pathWithNext = safeNext && safeNext !== "/dashboard"
    ? `/auth/callback?next=${encodeURIComponent(safeNext)}`
    : "/auth/callback";

  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    if (isLocalhost(hostname)) {
      return `${window.location.origin}${pathWithNext}`;
    }
  }

  return `${getCanonicalSiteUrl()}${pathWithNext}`;
}

/**
 * Sanitizes internal redirect targets to prevent open-redirect vulnerabilities.
 *
 * Rules:
 * 1. Must be a relative path starting with a single "/".
 * 2. Must not start with "//" (protocol-relative URL) or "/\" (backslash evasion).
 * 3. Must not contain protocol schemes (http:, https:, javascript:, etc.).
 * 4. Disallows control characters and whitespace.
 * 5. Defaults safely to fallbackPath (default: "/dashboard").
 */
export function sanitizeInternalRedirect(
  target: string | null | undefined,
  fallbackPath: string = "/dashboard"
): string {
  if (!target || typeof target !== "string") {
    return fallbackPath;
  }

  const trimmed = target.trim();

  // Must begin with a single slash, not protocol-relative "//" or backslash "/\"
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.startsWith("/\\")) {
    return fallbackPath;
  }

  // Disallow any embedded control characters or spaces (ASCII 0x00-0x1F, 0x7F, whitespace)
  if (/[\x00-\x1f\x7f\s]/.test(trimmed)) {
    return fallbackPath;
  }

  // Parse against a dummy base origin to verify path integrity
  try {
    const dummyBase = "https://inboundcheck.internal";
    const parsed = new URL(trimmed, dummyBase);

    // If parsing changes the origin or protocol, reject
    if (parsed.origin !== dummyBase || parsed.protocol !== "https:") {
      return fallbackPath;
    }

    // Only return pathname, search, and hash
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallbackPath;
  }
}
