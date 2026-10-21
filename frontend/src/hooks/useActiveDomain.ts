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
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const isMountedRef = useRef(true);

  const loadRegistry = useCallback(async () => {
    // If an explicit query domain is provided, we can still load registered domains
    // but the active domain is already firmly established by the query.
    setIsLoading(true);
    try {
      const res = await apiFetch("/api/v1/domains");
      if (res.ok && isMountedRef.current) {
        const json = await res.json().catch(() => []);
        const rawList: RawDomainItem[] = Array.isArray(json)
          ? json
          : Array.isArray(json?.domains)
          ? json.domains
          : Array.isArray(json?.data)
          ? json.data
          : [];

        const domainNames = rawList
          .map((d) => normalizeDomainInput(d.domain_name || d.domain || ""))
          .filter((d): d is string => Boolean(d));

        setRegisteredDomains(domainNames);

        // Resolve active domain candidate
        const candidate = resolveActiveDomainCandidate(queryDomainParam, domainNames);
        setActiveDomain(candidate.domain);
        setResolutionSource(candidate.source);
      }
    } catch {
      // Offline / network failure preserved
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  }, [queryDomainParam]);

  useEffect(() => {
    isMountedRef.current = true;
    const cleanQuery = queryDomainParam ? normalizeDomainInput(queryDomainParam) : "";
    if (cleanQuery) {
      setActiveDomain(cleanQuery);
      setResolutionSource("query");
    }

    loadRegistry();

    return () => {
      isMountedRef.current = false;
    };
  }, [queryDomainParam, loadRegistry]);

  return {
    activeDomain,
    resolutionSource,
    isLoading,
    registeredDomains,
    refreshRegistry: loadRegistry,
  };
}
