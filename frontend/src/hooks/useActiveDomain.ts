"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "@/lib/api";
import { normalizeDomainInput } from "@/lib/domain";
import { resolveActiveDomainCandidate, ActiveDomainCandidate } from "@/lib/domain-selection";

interface RawDomainItem {
  domain_name?: string;
  domain?: string;
}

export interface UseActiveDomainResult {
  activeDomain: string;
  resolutionSource: "query" | "registry" | "none";
  isLoading: boolean;
  registeredDomains: string[];
  refreshRegistry: () => Promise<void>;
}

/**
 * Loads the authenticated user's registered domains, normalized.
 * Resolves to null on network failure or a non-OK response.
 */
async function fetchRegisteredDomains(): Promise<string[] | null> {
  try {
    const res = await apiFetch("/api/v1/domains");
    if (!res.ok) return null;
    const json = await res.json().catch(() => []);
    const rawList: RawDomainItem[] = Array.isArray(json)
      ? json
      : Array.isArray(json?.domains)
      ? json.domains
      : Array.isArray(json?.data)
      ? json.data
      : [];

    return rawList
      .map((d) => normalizeDomainInput(d.domain_name || d.domain || ""))
      .filter((d): d is string => Boolean(d));
  } catch {
    // Offline / network failure preserved
    return null;
  }
}

/**
 * Enterprise hook to resolve the active sending domain for diagnostic tools
 * (Inspector, Blacklist Radar, Setup Wizard).
 *
 * Ensures seamless continuity across dashboard tools:
 * 1. Honors explicit valid query parameters (?domain=...).
 * 2. Falls back to the authenticated user's first registered monitored domain.
 * 3. Gracefully resolves to empty state ("none") when the user has 0 registered domains.
 */
export function useActiveDomain(queryDomainParam?: string | null): UseActiveDomainResult {
  const [activeDomain, setActiveDomain] = useState<string>(() => {
    return queryDomainParam ? normalizeDomainInput(queryDomainParam) : "";
  });
  const [resolutionSource, setResolutionSource] = useState<"query" | "registry" | "none">(() => {
    return queryDomainParam && normalizeDomainInput(queryDomainParam) ? "query" : "none";
  });
  const [registeredDomains, setRegisteredDomains] = useState<string[]>([]);
  // The registry is fetched on mount, so the hook starts in the loading state.
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const isMountedRef = useRef(true);

  // When the explicit query domain changes, adopt it immediately during render
  // (React "adjusting state when a prop changes" pattern) instead of in an effect.
  const [prevQueryDomainParam, setPrevQueryDomainParam] = useState(queryDomainParam);
  if (queryDomainParam !== prevQueryDomainParam) {
    setPrevQueryDomainParam(queryDomainParam);
    // A new query re-runs the registry fetch effect below.
    setIsLoading(true);
    const cleanQuery = queryDomainParam ? normalizeDomainInput(queryDomainParam) : "";
    if (cleanQuery) {
      setActiveDomain(cleanQuery);
      setResolutionSource("query");
    }
  }

  // Applies a fetched registry (null = request failed / non-OK, state preserved).
  const applyRegistry = useCallback((domainNames: string[] | null) => {
    if (!isMountedRef.current) return;
    if (domainNames) {
      setRegisteredDomains(domainNames);

      // Resolve active domain candidate
      const candidate = resolveActiveDomainCandidate(queryDomainParam, domainNames);
      setActiveDomain(candidate.domain);
      setResolutionSource(candidate.source);
    }
    setIsLoading(false);
  }, [queryDomainParam]);

  const refreshRegistry = useCallback(async () => {
    setIsLoading(true);
    applyRegistry(await fetchRegisteredDomains());
  }, [applyRegistry]);

  useEffect(() => {
    isMountedRef.current = true;
    // If an explicit query domain is provided, we still load registered domains
    // but the active domain is already firmly established by the query.
    // State is only updated from the async callback once the request settles.
    void fetchRegisteredDomains().then(applyRegistry);

    return () => {
      isMountedRef.current = false;
    };
  }, [applyRegistry]);

  return {
    activeDomain,
    resolutionSource,
    isLoading,
    registeredDomains,
    refreshRegistry,
  };
}
