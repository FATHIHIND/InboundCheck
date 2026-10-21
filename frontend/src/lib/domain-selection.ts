import { normalizeDomainInput } from "./domain";

export interface ActiveDomainCandidate {
  domain: string;
  source: "query" | "registry" | "none";
}

export interface StoreDisplayResolution {
  isLinkedToStore: boolean;
  storeBadgeLabel: string;
  storeDomain: string | null;
}

/**
 * Resolves the primary active domain candidate for diagnostic and monitoring views.
 *
 * Priority order:
 * 1. Explicit, non-empty, normalized query parameter (?domain=...).
 * 2. First registered monitored domain from the authenticated user's registry.
 * 3. None (empty string) indicating true empty state.
 */
export function resolveActiveDomainCandidate(
  queryParam?: string | null,
  registeredDomains: Array<{ domain_name?: string; domain?: string } | string> = []
): ActiveDomainCandidate {
  if (queryParam && typeof queryParam === "string") {
    const cleanQuery = normalizeDomainInput(queryParam);
    if (cleanQuery) {
      return { domain: cleanQuery, source: "query" };
    }
  }

  if (Array.isArray(registeredDomains) && registeredDomains.length > 0) {
    for (const item of registeredDomains) {
      const raw = typeof item === "string" ? item : item.domain_name || item.domain || "";
      const clean = normalizeDomainInput(raw);
      if (clean) {
        return { domain: clean, source: "registry" };
      }
    }
  }

  return { domain: "", source: "none" };
}

/**
 * Formats store connection status for a monitored domain.
 * Strictly avoids generating synthetic or assumed `${domain}.myshopify.com` handles
 * when no authentic Shopify store connection exists.
 */
export function formatStoreDisplay(
  domainName: string,
  shopifyStore?: string | null
): StoreDisplayResolution {
  const cleanDomain = normalizeDomainInput(domainName);
  const rawStore = (shopifyStore || "").trim().toLowerCase();

  // If no store handle provided, or if handle was synthetically derived
  const syntheticMatch = cleanDomain ? `${cleanDomain.replace(/\.[^/.]+$/, "")}.myshopify.com` : "";
  const isSyntheticOrEmpty = !rawStore || rawStore === "null" || rawStore === "undefined" || rawStore === syntheticMatch;

  if (isSyntheticOrEmpty) {
    return {
      isLinkedToStore: false,
      storeBadgeLabel: "Domain Only",
      storeDomain: null,
    };
  }

  return {
    isLinkedToStore: true,
    storeBadgeLabel: rawStore,
    storeDomain: rawStore,
  };
}

/**
 * Determines whether financial GMV protection metrics can be legitimately calculated.
 * Prohibits displaying simulated or default GMV numbers as real metrics when no store is connected.
 */
export function canDisplayStoreFinancialMetrics(
  connectedShopifyStoreCount: number,
  isDemoActive: boolean = false
): boolean {
  if (isDemoActive) return true;
  return connectedShopifyStoreCount > 0;
}

/**
 * Validates that a candidate domain conforms to valid DNS domain structure
 * and is not a synthetic handle like "myshopify.com".
 */
export function isValidSendingDomain(domain: string): boolean {
  if (!domain || typeof domain !== "string") return false;
  const clean = normalizeDomainInput(domain);
  if (!clean || clean === "myshopify.com") return false;
  const domainPattern = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;
  return domainPattern.test(clean);
}

/**
 * Resolves the primary target sending domain for running the full diagnostic pipeline.
 *
 * Strict Registry Validation Rules:
 * 1. An active domain is accepted ONLY if it matches a valid domain in the authenticated
 *    user's registered-domain list.
 * 2. If the active domain is absent, invalid, or does not match any registered domain,
 *    it falls back to the first valid registered domain.
 * 3. If no valid registered domain exists (empty or invalid registry), returns null.
 * 4. Synthetic domain values like "myshopify.com" are strictly prohibited and filtered out.
 */
export function resolvePipelineTargetDomain(
  activeDomain?: string | null,
  registeredDomains: Array<{ domain_name?: string; domain?: string } | string> = []
): string | null {
  if (!Array.isArray(registeredDomains) || registeredDomains.length === 0) {
    return null;
  }

  // Extract and normalize all valid registered domains (excluding synthetic/invalid values)
  const validRegistered: string[] = [];
  for (const item of registeredDomains) {
    const raw = typeof item === "string" ? item : item.domain_name || item.domain || "";
    const clean = normalizeDomainInput(raw);
    if (isValidSendingDomain(clean) && !validRegistered.includes(clean)) {
      validRegistered.push(clean);
    }
  }

  if (validRegistered.length === 0) {
    return null;
  }

  // If activeDomain is provided, verify it is valid and exists within the user's registered list
  if (activeDomain && typeof activeDomain === "string") {
    const cleanActive = normalizeDomainInput(activeDomain);
    if (isValidSendingDomain(cleanActive) && validRegistered.includes(cleanActive)) {
      return cleanActive;
    }
  }

  // If activeDomain is absent or not in registry, fall back to the primary registered domain
  return validRegistered[0] || null;
}
