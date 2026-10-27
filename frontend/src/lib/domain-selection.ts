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

export interface DomainKpiDisplayResolution {
  healthBadgeText: string;
  healthBadgeVariant: "emerald" | "amber" | "rose" | "neutral";
  healthHighlightText: string;
  healthHighlightVariant: "emerald" | "amber" | "rose" | "neutral";
  healthSubtext?: string;
  riskBadgeText: string;
  riskBadgeVariant: "emerald" | "amber" | "rose" | "neutral";
  riskHighlightText: string;
  riskHighlightVariant: "emerald" | "amber" | "rose" | "neutral";
  isDomainAwaiting: boolean;
}

/**
 * Resolves display labels for domain-level KPI cards (Deliverability Health Status & Risk Forecast).
 * Ensures that when zero domains are registered, the UI explicitly indicates "Awaiting Domain"
 * rather than falsely claiming an unfulfilled Shopify store requirement.
 */
export function formatDomainKpiDisplay(
  domainCount: number,
  healthScore: number | null,
  healthStatusTier: "Optimal" | "Warning" | "Critical" | "Setup Required"
): DomainKpiDisplayResolution {
  const isAwaiting = domainCount === 0 || healthScore === null;
  if (isAwaiting) {
    return {
      healthBadgeText: "Awaiting Domain",
      healthBadgeVariant: "neutral",
      healthHighlightText: "Awaiting domain connection",
      healthHighlightVariant: "neutral",
      healthSubtext: "No domain connected",
      riskBadgeText: "Awaiting Domain",
      riskBadgeVariant: "neutral",
      riskHighlightText: "Predictive Risk Model",
      riskHighlightVariant: "neutral",
      isDomainAwaiting: true,
    };
  }

  const healthVariant: "emerald" | "amber" | "rose" | "neutral" =
    healthStatusTier === "Optimal"
      ? "emerald"
      : healthStatusTier === "Warning"
      ? "amber"
      : healthStatusTier === "Critical"
      ? "rose"
      : "neutral";

  const riskBadge =
    healthScore >= 90
      ? "Optimal Trajectory"
      : healthScore >= 60
      ? "Moderate Risk"
      : "Elevated Risk";

  const riskVariant: "emerald" | "amber" | "rose" =
    healthScore >= 90 ? "emerald" : healthScore >= 60 ? "amber" : "rose";

  const riskHighlight =
    healthScore >= 90
      ? "Optimal Delivery Trajectory"
      : healthScore >= 60
      ? "Moderate Attrition Exposure"
      : "Elevated Dispute Risk";

  return {
    healthBadgeText: healthStatusTier,
    healthBadgeVariant: healthVariant,
    healthHighlightText: `• ${healthStatusTier} Risk Tier (${domainCount} ${domainCount === 1 ? "domain" : "domains"})`,
    healthHighlightVariant: healthVariant,
    healthSubtext: undefined,
    riskBadgeText: riskBadge,
    riskBadgeVariant: riskVariant,
    riskHighlightText: riskHighlight,
    riskHighlightVariant: riskVariant,
    isDomainAwaiting: false,
  };
}

export interface RadarKpiDisplayResolution {
  value: string;
  badgeText: string;
  badgeVariant: "emerald" | "neutral";
  subtext: string;
  isMonitoringActive: boolean;
}

/**
 * Resolves display labels and telemetry states for the Blacklist Radar Coverage KPI.
 * Strictly prevents claiming active monitoring or active alert feeds when zero eligible
 * registered domains exist.
 */
export function formatRadarKpiDisplay(
  domainCount: number,
  hasValidDomain: boolean,
  isTelegramActive: boolean,
  lowestRblClean: number = 10
): RadarKpiDisplayResolution {
  const isEligible = domainCount > 0 && hasValidDomain;
  if (!isEligible) {
    return {
      value: "10 Feeds Supported",
      badgeText: "Standing By",
      badgeVariant: "neutral",
      subtext: "Awaiting domain",
      isMonitoringActive: false,
    };
  }

  return {
    value: `${lowestRblClean}/10 Clean`,
    badgeText: "Active Radar",
    badgeVariant: "emerald",
    subtext: isTelegramActive ? "✓ Telegram Alerts Active" : "Telegram Alerts: Inactive",
    isMonitoringActive: true,
  };
}

export interface WizardRouteOptions {
  domain?: string | null;
  shop?: string | null;
  returnUrl?: string | null;
  step?: number | null;
}

/**
 * Standardizes resolution of the dedicated setup wizard URL (/dashboard/wizard).
 * Normalizes domain and shop query parameters, strips dangerous protocols,
 * and preserves legitimate return paths.
 */
export function resolveWizardRoute(options: WizardRouteOptions = {}): string {
  const rawTarget = options.domain || options.shop || "";
  const cleanTarget = normalizeDomainInput(rawTarget);

  const params = new URLSearchParams();
  if (cleanTarget) {
    params.set("domain", cleanTarget);
  }
  if (options.step !== undefined && options.step !== null && options.step >= 0 && options.step <= 7) {
    params.set("step", String(options.step));
  }
  if (options.returnUrl) {
    const trimmed = options.returnUrl.trim();
    if (trimmed.startsWith("/") && !trimmed.startsWith("//") && !trimmed.includes("\\")) {
      params.set("return_url", trimmed);
    }
  }

  const query = params.toString();
  return query ? `/dashboard/wizard?${query}` : "/dashboard/wizard";
}

