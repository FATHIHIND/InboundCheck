"use client";

import { useState, useEffect, useCallback, Fragment } from "react";
import dynamic from "next/dynamic";
import {
  ShieldCheck,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Activity,
  Globe,
  Radio,
  Clock,
  Server,
  ChevronDown,
  HelpCircle,
  Flame,
  AlertCircle
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";
import { OperationalEmptyState } from "@/components/operational/OperationalEmptyState";
import { apiFetch } from "@/lib/api";
import { ApiError, normalizeApiError } from "@/lib/apiResource";

const RblTopology3DCanvas = dynamic(() => import("../components/RblTopology3DCanvas"), {
  ssr: false,
});

export type RBLStatus = "clean" | "listed" | "unknown" | "error";
export type RBLTargetType = "ip" | "domain";
export type RBLSeverity = "none" | "low" | "medium" | "high" | "critical";

export interface RblItem {
  provider_id: string;
  provider_name: string;
  zone: string;
  target_type: RBLTargetType;
  status: RBLStatus;
  severity: RBLSeverity;
  queried_target: string;
  response_codes: string[];
  latency_ms: number | null;
  message: string | null;
  delisting_url: string;
  checked_at: string;
}

export interface RblScanResponse {
  domain: string;
  resolved_ips: string[];
  results: RblItem[];
  rbl_clean_count: number;
  rbl_listed_count: number;
  rbl_unknown_count: number;
  rbl_error_count: number;
  rbl_total_count: number;
  overall_status: "clean" | "listed" | "partial" | "unavailable";
  highest_severity: RBLSeverity;
  execution_time_ms: number;
  scanned_at: string;
}

async function toApiError(response: Response, defaultMessage = "Request failed"): Promise<ApiError> {
  let detail = `${defaultMessage} (Status ${response.status})`;
  let retryAfterSeconds: number | undefined;

  const retryHeader = response.headers.get("Retry-After");
  if (retryHeader) {
    const parsed = parseInt(retryHeader, 10);
    if (!isNaN(parsed)) retryAfterSeconds = parsed;
  }

  try {
    const json = await response.json();
    if (json.detail) {
      detail = typeof json.detail === "string" ? json.detail : JSON.stringify(json.detail);
    }
  } catch {}

  if (response.status === 429) {
    detail = "Scan rate limit reached. The system automatically protects multi-resolver throughput. Please wait a moment before requesting another scan.";
  } else if (response.status === 404) {
    detail = "The requested domain was not found. Please ensure the domain name is spelled correctly and has active DNS records.";
  } else if (response.status === 422 || response.status === 400) {
    detail = "Invalid domain input. Please enter a valid sending domain (e.g. store.com) and try again.";
  } else if (response.status >= 500) {
    detail = "The reputation scanning service is currently busy querying global databases. Please retry in a few moments.";
  }

  return {
    message: detail,
    status: response.status,
    retryable: response.status >= 500 || response.status === 429,
    endpoint: response.url,
    code: response.status === 429 ? "RATE_LIMITED" : `HTTP_${response.status}`,
    referenceId: retryAfterSeconds ? `Retry after ${retryAfterSeconds}s` : undefined
  };
}

export default function BlacklistRadarPage() {
  const [target, setTarget] = useState("");
  const [scan, setScan] = useState<RblScanResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [rateLimitCountdown, setRateLimitCountdown] = useState<number | null>(null);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  const formatRblListing = (codes: string[]) => {
    if (!codes || codes.length === 0) return "LISTED";
    return codes
      .map((c) => (c === "127.0.0.2" ? "Listed as Spam Trap Origin: 127.0.0.2" : c.startsWith("127.0.0.") ? `Listed: ${c}` : c))
      .join(", ");
  };

  // Countdown timer for rate limiting
  useEffect(() => {
    if (rateLimitCountdown === null || rateLimitCountdown <= 0) return;
    const timer = setInterval(() => {
      setRateLimitCountdown((prev) => (prev && prev > 1 ? prev - 1 : null));
    }, 1000);
    return () => clearInterval(timer);
  }, [rateLimitCountdown]);

  const loadLatest = useCallback(async (domainToQuery?: string) => {
    const dom = (domainToQuery || target).trim();
    if (!dom) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await apiFetch(`/api/v1/dns/rbl-status?domain=${encodeURIComponent(dom)}`);

      if (response.status === 404) {
        setScan(null); // true empty state: no scan yet
        return;
      }

      if (!response.ok) {
        throw await toApiError(response, "Failed to fetch RBL reputation status");
      }

      const data: RblScanResponse = await response.json();
      setScan(data);
    } catch (cause) {
      setError(normalizeApiError(cause, "/api/v1/dns/rbl-status"));
    } finally {
      setIsLoading(false);
    }
  }, [target]);

  const runScan = async (domainOverride?: string) => {
    setExpandedRows({});
    const domainToScan = (domainOverride || target).trim();
    if (!domainToScan) return;

    setIsScanning(true);
    setError(null);

    try {
      const response = await apiFetch("/api/v1/dns/rbl-scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain: domainToScan }),
      });

      if (response.status === 429) {
        const retryHeader = response.headers.get("Retry-After");
        const seconds = retryHeader ? parseInt(retryHeader, 10) : 60;
        setRateLimitCountdown(isNaN(seconds) ? 60 : seconds);
        setError(null);
        return;
      }

      if (!response.ok) {
        throw await toApiError(response, "RBL real-time scan failed");
      }

      const data: RblScanResponse = await response.json();
      setScan(data);
    } catch (cause) {
      if (rateLimitCountdown !== null) {
        setError(null);
      } else {
        setError(normalizeApiError(cause, "/api/v1/dns/rbl-scan"));
      }
    } finally {
      setIsScanning(false);
    }
  };

  useEffect(() => {
    async function initRadar() {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        const paramDom = urlParams.get("domain");
        if (paramDom) {
          setTarget(paramDom);
          loadLatest(paramDom);
          return;
        }

        const res = await apiFetch("/api/v1/domains");
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data.domains) && data.domains.length > 0) {
            const firstDom = data.domains[0].domain_name;
            setTarget(firstDom);
            loadLatest(firstDom);
            return;
          }
        }
      } catch {}
      setIsLoading(false);
    }
    initRadar();
  }, [loadLatest]);

  const toggleRow = (id: string) => {
    setExpandedRows((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const canvasNodes = scan
    ? scan.results.map((r) => ({
        name: r.provider_name,
        host: r.zone,
        status: r.status,
        latency_ms: r.latency_ms ?? 0,
      }))
    : [];

  const avgLatency = scan && scan.results.length > 0
    ? (() => {
        const measured = scan.results
          .map((r) => r.latency_ms)
          .filter((l): l is number => typeof l === "number" && !isNaN(l));
        if (measured.length === 0) return "--";
        return `${(measured.reduce((a, b) => a + b, 0) / measured.length).toFixed(1)}ms`;
      })()
    : "--";

  return (
    <div className="space-y-6 max-w-[1360px] mx-auto animate-fadeIn pb-12">
      {/* 1. Header with Title & Action */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2.5">
            <Radio className="w-6 h-6 text-emerald-600 animate-pulse" />
            Reputation Radar &amp; Blacklist Intelligence
          </h1>
          <p className="text-sm text-slate-600 font-normal mt-1">
            Monitor sender domain and IP reputation across 10 global RBL feeds.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {scan && (
            <button
              onClick={() => loadLatest()}
              disabled={isLoading || isScanning}
              className="px-3 py-2 text-xs font-mono rounded-md border border-slate-300 bg-white text-slate-700 hover:text-slate-900 hover:bg-slate-50 transition flex items-center gap-1.5 shadow-2xs cursor-pointer"
              title="Refresh latest stored audit"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          )}

          <EmeraldHoverButton
            onClick={() => runScan()}
            isLoading={isScanning}
            disabled={rateLimitCountdown !== null}
            loadingText="Scanning Reputation Lists..."
            icon={<RefreshCw className="w-3.5 h-3.5" />}
            size="sm"
            variant="primary"
            className="h-10 px-5 text-xs font-semibold rounded-md shadow-xs"
          >
            {rateLimitCountdown !== null
              ? `Cooldown (${rateLimitCountdown}s)`
              : "Scan Reputation Lists"}
          </EmeraldHoverButton>
        </div>
      </div>

      {/* Rate Limit Notice Banner */}
      {rateLimitCountdown !== null && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-xs font-mono flex items-center justify-between animate-fadeIn">
          <div className="flex items-center gap-2.5">
            <Clock className="w-4 h-4 text-amber-600 shrink-0 animate-pulse" />
            <span>
              <strong>Rate Limit Active:</strong> Next live scan permitted in{" "}
              <span className="font-bold text-amber-950 underline">{rateLimitCountdown} seconds</span>.
            </span>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg text-rose-800 text-xs font-mono flex items-start justify-between gap-3 animate-fadeIn">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-rose-900">Reputation Scan Notice</div>
              <div className="text-rose-700 mt-0.5 font-sans text-xs">{error.message}</div>
              {process.env.NODE_ENV === "development" && error.code && (
                <span className="inline-block mt-1 text-[10px] text-rose-600 font-mono">Debug: {error.code}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => runScan()}
              className="relative px-2.5 py-1 bg-white hover:bg-rose-100 text-rose-800 rounded border border-rose-300 text-[11px] transition before:absolute before:-inset-2 before:content-[''] cursor-pointer shadow-2xs"
            >
              Retry
            </button>
            <button
              onClick={() => setError(null)}
              aria-label="Dismiss error notification"
              className="relative text-slate-500 hover:text-slate-900 text-xs px-2 py-1 rounded before:absolute before:-inset-2 before:content-[''] cursor-pointer"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 2. Target Search & Control Bar */}
      <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-xs flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-96">
          <Globe className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runScan();
            }}
            placeholder="Enter domain, e.g. store.com"
            className="w-full pl-9 pr-3 py-2 bg-white border border-slate-300 rounded-md text-slate-900 placeholder:text-slate-400 font-medium font-mono text-xs focus:outline-none focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600 shadow-2xs transition-colors"
          />
        </div>

        <div className="flex items-center gap-4 text-xs font-mono text-slate-600 flex-wrap">
          <span>
            Target: <strong className="text-emerald-700 font-bold font-mono text-xs">{scan ? scan.domain : target}</strong>
          </span>
          {scan && scan.resolved_ips && scan.resolved_ips.length > 0 && (
            <>
              <span className="text-slate-300">•</span>
              <span>
                Store Sending IP Addresses:{" "}
                <strong className="text-slate-900 font-bold font-mono text-xs">
                  {scan.resolved_ips.join(", ")}
                </strong>
              </span>
            </>
          )}
          <span className="text-slate-300">•</span>
          <span>
            Scanned:{" "}
            <strong className="text-slate-900 font-bold font-mono text-xs">
              {scan ? new Date(scan.scanned_at).toLocaleTimeString() : "Pending"}
            </strong>
          </span>
        </div>
      </div>

      {/* 3. Listed Incident Notification Banner if Any Provider is Listed */}
      {scan && scan.rbl_listed_count > 0 && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg animate-fadeIn">
          <div className="flex items-start gap-3">
            <Flame className="w-5 h-5 text-rose-600 shrink-0 mt-0.5 animate-bounce" />
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-rose-900 uppercase tracking-wide flex items-center gap-2">
                  Active Blacklist Incident Detected ({scan.rbl_listed_count} of {scan.rbl_total_count} Lists)
                </h2>
                <span className="text-[11px] font-mono text-rose-800 font-bold px-2 py-0.5 rounded bg-rose-100 border border-rose-300">
                  SEVERITY: {scan.highest_severity.toUpperCase()}
                </span>
              </div>
              <p className="text-xs text-rose-700 mt-1 font-sans">
                One or more global reputation databases are flagging email traffic from this sending domain. Customer order confirmations and transactional emails risk landing in spam.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {scan.results
                  .filter((r) => r.status === "listed")
                  .map((r) => (
                    <a
                      key={r.provider_id}
                      href={r.delisting_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-rose-100 text-rose-800 text-xs font-mono border border-rose-300 shadow-2xs transition"
                    >
                      <span>{r.provider_name}</span>
                      <span className="text-rose-600 font-bold">[{formatRblListing(r.response_codes)}]</span>
                      <ExternalLink className="w-3 h-3 ml-1 text-rose-600" />
                    </a>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 4. Partial Scan Warning Banner */}
      {scan && scan.overall_status === "partial" && scan.rbl_listed_count === 0 && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-xs font-mono flex items-start gap-3 animate-fadeIn">
          <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <div className="font-bold text-amber-900">Reputation Check In Progress (Partial Response)</div>
            <p className="text-amber-700 mt-0.5 font-sans">
              {scan.rbl_unknown_count} of {scan.rbl_total_count} reputation providers timed out or returned pending results. We will continue polling to verify your domain reputation status.
            </p>
          </div>
        </div>
      )}

      {/* 5. 3D Real-Time RBL Node Topology Canvas */}
      {scan && (
        <div className="bg-white p-4 rounded-lg border border-slate-200 shadow-xs space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-200 pb-2 text-xs">
            <span className="font-mono text-emerald-700 font-bold flex items-center gap-2">
              <Radio className="w-4 h-4 text-emerald-600" />
              GLOBAL SPAM BLACKLIST NETWORK
            </span>
            <span className="text-[10px] font-mono text-slate-500">
              {scan.rbl_total_count} AUTHORITATIVE LISTS
            </span>
          </div>
          <RblTopology3DCanvas rbls={canvasNodes} className="h-44 w-full" />
        </div>
      )}

      {/* 6. Purpose-Driven Enterprise Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <GlassEmeraldCard
          title="Active Incidents"
          subtitle="Real-time RBL Status"
          badgeText={
            !scan
              ? "Pending"
              : scan.rbl_listed_count === 0
              ? "Clean Posture"
              : `${scan.rbl_listed_count} Listed`
          }
          badgeVariant={
            !scan
              ? undefined
              : scan.rbl_listed_count === 0
              ? "emerald"
              : "rose"
          }
          metricValue={scan ? scan.rbl_listed_count : "--"}
          icon={<ShieldCheck className="w-5 h-5 text-emerald-600" />}
        >
          <p className="text-xs text-slate-600 font-mono">
            {!scan
              ? "Awaiting first live reputation scan."
              : scan.rbl_listed_count === 0
              ? "Zero listings detected across authoritative realtime blacklists."
              : `${scan.rbl_listed_count} blacklist listing(s) requiring immediate delisting.`}
          </p>
        </GlassEmeraldCard>

        <GlassEmeraldCard
          title="RBL Hosts Queried"
          subtitle="Spam Databases Monitored"
          badgeText={
            !scan
              ? "Unchecked"
              : `${scan.rbl_clean_count} / ${scan.rbl_total_count} Clean`
          }
          badgeVariant={
            !scan
              ? undefined
              : scan.overall_status === "clean"
              ? "emerald"
              : scan.overall_status === "listed"
              ? "rose"
              : "amber"
          }
          metricValue={scan ? `${scan.rbl_clean_count} / ${scan.rbl_total_count}` : "--"}
          icon={<Server className="w-5 h-5 text-emerald-600" />}
        >
          <p className="text-xs text-slate-600 font-mono line-clamp-1">
            {scan
              ? `${scan.rbl_unknown_count} unknown, ${scan.rbl_error_count} resolver error`
              : "Spamhaus, Barracuda, SpamCop, Invaluement, Mailspike."}
          </p>
        </GlassEmeraldCard>

        <GlassEmeraldCard
          title="Overall Posture"
          subtitle="Evidence-Based Status"
          badgeText={scan ? scan.overall_status.toUpperCase() : "PENDING"}
          badgeVariant={
            !scan
              ? undefined
              : scan.overall_status === "clean"
              ? "emerald"
              : scan.overall_status === "listed"
              ? "rose"
              : "amber"
          }
          metricValue={scan ? scan.overall_status.toUpperCase() : "--"}
          icon={<Activity className="w-5 h-5 text-emerald-600" />}
        >
          <p className="text-xs text-slate-600 font-mono">
            {!scan
              ? "Run live scan to compute overall posture."
              : scan.overall_status === "clean"
              ? "All active lists returned definitive negative records."
              : scan.overall_status === "listed"
              ? "High impact delivery block active."
              : "Incomplete scan results."}
          </p>
        </GlassEmeraldCard>

        <GlassEmeraldCard
          title="Avg. Resolution Latency"
          subtitle="Multi-resolver DNS query speed per RBL zone"
          badgeText={scan ? `${scan.execution_time_ms.toFixed(0)}ms scan` : "Real-time"}
          badgeVariant="cyan"
          metricValue={avgLatency}
          icon={<Clock className="w-5 h-5 text-slate-700" />}
        >
          <p className="text-xs text-slate-600 font-mono">
            {scan
              ? `Bounded 1.5s per-zone multi-resolver execution.`
              : "Real-time query response speed."}
          </p>
        </GlassEmeraldCard>
      </div>

      {/* 7. Loading Skeleton State */}
      {isLoading && !scan && (
        <div className="bg-white p-8 rounded-lg border border-slate-200 animate-pulse space-y-4 shadow-xs">
          <div className="h-4 bg-slate-200 rounded w-1/4"></div>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-slate-50 border border-slate-200 rounded-md flex items-center justify-between px-4">
                <div className="h-3 bg-slate-200 rounded w-1/3"></div>
                <div className="h-3 bg-slate-200 rounded w-1/6"></div>
                <div className="h-3 bg-slate-200 rounded w-1/12"></div>
              </div>
            ))}
          </div>
          <p className="text-xs text-slate-500 font-mono text-center pt-2">
            Scanning global reputation databases via dedicated recursive nameservers...
          </p>
        </div>
      )}

      {/* 8. True Empty State (404 / No prior scan recorded) */}
      {!isLoading && !scan && !error && (
        <OperationalEmptyState
          icon={<Radio className="w-8 h-8 text-emerald-600" />}
          badge="Awaiting Reputation Scan"
          title="No Blacklist Audits Recorded"
          description={
            target
              ? `No reputation check has been run yet for ${target}. Scan global reputation databases to verify sending domain deliverability.`
              : "No spam blacklist scan has been run yet. Enter your sending domain above to check your store's reputation across 10 authoritative databases."
          }
          action={{
            label: "Scan Reputation Lists",
            onClick: () => runScan(),
          }}
        />
      )}

      {/* 9. Measured Authoritative RBL Monitoring Matrix Table */}
      {scan && (
        <GlassEmeraldCard
          title="Global Spam Blacklist Network"
          subtitle="Live query results across 10 authoritative anti-spam databases"
          badgeText={`${scan.rbl_total_count} Lists Monitored`}
          badgeVariant="emerald"
          icon={<Activity className="w-5 h-5 text-emerald-600" />}
          disableGrid
        >
          <div className="overflow-y-auto max-h-[460px] scrollbar-thin scrollbar-thumb-slate-300 scrollbar-track-transparent rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-left text-xs font-mono border-collapse" role="grid">
              <thead className="sticky top-0 z-10 bg-slate-50/80 backdrop-blur-md border-b border-slate-200 text-[10px] font-mono uppercase tracking-wider text-slate-600 font-semibold">
                <tr>
                  <th scope="col" className="py-2.5 px-3 font-semibold text-left">Reputation Provider</th>
                  <th scope="col" className="py-2.5 px-3 font-semibold text-left">Reputation Zone</th>
                  <th scope="col" className="py-2.5 px-3 font-semibold text-left">Target Type</th>
                  <th scope="col" className="py-2.5 px-3 font-semibold text-left">Measured Status</th>
                  <th scope="col" className="py-2.5 px-3 font-semibold text-center">Latency</th>
                  <th scope="col" className="py-2.5 px-3 font-semibold text-right">Delisting Portal</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-800">
                {scan.results.map((rbl) => {
                  const isListed = rbl.status === "listed";
                  const isUnknown = rbl.status === "unknown";
                  const isError = rbl.status === "error";
                  const isExpanded = !!expandedRows[rbl.provider_id];

                  return (
                    <Fragment key={rbl.provider_id}>
                      <tr
                        className="hover:bg-slate-50/70 transition-colors cursor-pointer"
                        onClick={() => toggleRow(rbl.provider_id)}
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            toggleRow(rbl.provider_id);
                          }
                        }}
                      >
                        <td className="py-2.5 px-3 text-xs font-mono">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleRow(rbl.provider_id);
                              }}
                              className="relative p-1 rounded text-slate-400 hover:text-emerald-600 transition cursor-pointer before:absolute before:-inset-2 before:content-['']"
                              aria-label={isExpanded ? "Collapse row details" : "Expand row details"}
                              title={isExpanded ? "Collapse Row" : "Expand Row"}
                            >
                              <ChevronDown
                                className={`w-3.5 h-3.5 transition-transform duration-200 ${
                                  isExpanded ? "rotate-180 text-emerald-600" : "text-slate-400"
                                }`}
                              />
                            </button>
                            <div>
                              <div className="font-bold text-slate-900 text-xs font-sans flex items-center gap-1.5">
                                {rbl.provider_name}
                              </div>
                              <div className="text-[10px] text-slate-500 font-mono mt-0.5 line-clamp-1">
                                Target: {rbl.queried_target}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono text-slate-600">{rbl.zone}</td>
                        <td className="py-2.5 px-3 text-xs font-mono">
                          <span className="text-[10px] font-mono uppercase tracking-wider font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                            {rbl.target_type}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono">
                          {isListed ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider font-semibold text-rose-800 bg-rose-50 border border-rose-200">
                              <XCircle className="w-3 h-3 text-rose-600" />
                              LISTED
                            </span>
                          ) : isUnknown ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider font-semibold text-amber-800 bg-amber-50 border border-amber-200">
                              <AlertCircle className="w-3 h-3 text-amber-600" />
                              UNKNOWN
                            </span>
                          ) : isError ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider font-semibold text-slate-700 bg-slate-100 border border-slate-200">
                              <HelpCircle className="w-3 h-3 text-slate-500" />
                              ERROR
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200">
                              <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                              CLEAN
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono text-slate-700 tabular-nums text-center">
                          {rbl.latency_ms ?? "--"}ms
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono text-right" onClick={(e) => e.stopPropagation()}>
                          <a
                            href={rbl.delisting_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-slate-600 hover:text-emerald-700 font-mono text-xs inline-flex items-center gap-1 transition-colors min-h-[32px] px-2 py-1 rounded hover:bg-slate-100"
                          >
                            Lookup <ExternalLink className="w-3 h-3" />
                          </a>
                        </td>
                      </tr>

                      {/* Collapsible Accordion Drawer */}
                      {isExpanded && (
                        <tr className="bg-slate-50/90 border-b border-slate-200 animate-fadeIn">
                          <td colSpan={6} className="p-4">
                            <div className="space-y-3 font-mono text-xs">
                              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                <div className="p-3 bg-white rounded-md border border-slate-200 shadow-2xs">
                                  <span className="text-[10px] text-slate-500 uppercase block">Response Classification</span>
                                  <span className="text-xs text-emerald-700 font-bold block mt-0.5">
                                    {rbl.response_codes.length > 0
                                      ? formatRblListing(rbl.response_codes)
                                      : "Clean (No Blacklist Entry)"}
                                  </span>
                                  <span className="text-[10px] text-slate-500 block mt-0.5">
                                    Severity: {rbl.severity.toUpperCase()}
                                  </span>
                                </div>

                                <div className="p-3 bg-white rounded-md border border-slate-200 shadow-2xs">
                                  <span className="text-[10px] text-slate-500 uppercase block">Delisting Gateway</span>
                                  <span className="text-xs text-slate-700 block mt-0.5 font-sans">
                                    Direct Provider Removal Portal
                                  </span>
                                  <a
                                    href={rbl.delisting_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[10px] text-emerald-700 hover:underline block mt-0.5 font-bold"
                                  >
                                    Open Delisting Portal ↗
                                  </a>
                                </div>

                                <div className="p-3 bg-white rounded-md border border-slate-200 shadow-2xs">
                                  <span className="text-[10px] text-slate-500 uppercase block">Monitoring Status</span>
                                  <span className="text-[11px] text-slate-700 block mt-0.5">
                                    {rbl.message || "Reputation verified clean across database."}
                                  </span>
                                  <span className="text-[10px] text-slate-500 block mt-0.5">
                                    Query Latency: {rbl.latency_ms !== null ? `${rbl.latency_ms}ms` : "timeout"}
                                  </span>
                                </div>
                              </div>

                              <div className="p-3 bg-white rounded-md border border-slate-200 flex items-center justify-between text-xs font-sans text-slate-600 shadow-2xs">
                                <span>Zone Route: {rbl.zone}</span>
                                <span className="font-mono text-[10px] text-slate-500">Checked: {new Date(rbl.checked_at).toISOString()}</span>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassEmeraldCard>
      )}
    </div>
  );
}
