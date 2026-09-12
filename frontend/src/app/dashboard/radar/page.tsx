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
        throw await toApiError(response, "Rate limit reached. Please wait before scanning again.");
      }

      if (!response.ok) {
        throw await toApiError(response, "RBL real-time scan failed");
      }

      const data: RblScanResponse = await response.json();
      setScan(data);
    } catch (cause) {
      setError(normalizeApiError(cause, "/api/v1/dns/rbl-scan"));
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
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight flex items-center gap-2.5">
            <Radio className="w-6 h-6 text-emerald-400 animate-pulse" />
            Blacklist Radar & Reputation Intelligence
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            Real-time blacklist monitoring across 10 major anti-spam databases with automated delisting guidance.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {scan && (
            <button
              onClick={() => loadLatest()}
              disabled={isLoading || isScanning}
              className="px-3 py-2 text-xs font-mono rounded-lg border border-zinc-800 bg-[#0E0E12] text-zinc-300 hover:text-white hover:border-zinc-700 transition flex items-center gap-1.5"
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
          >
            {rateLimitCountdown !== null
              ? `Cooldown (${rateLimitCountdown}s)`
              : "Scan Reputation Lists"}
          </EmeraldHoverButton>
        </div>
      </div>

      {/* Rate Limit Notice Banner */}
      {rateLimitCountdown !== null && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-300 text-xs font-mono flex items-center justify-between animate-fadeIn">
          <div className="flex items-center gap-2.5">
            <Clock className="w-4 h-4 text-amber-400 shrink-0 animate-pulse" />
            <span>
              <strong>Rate Limit Active:</strong> Next live scan permitted in{" "}
              <span className="font-bold text-white underline">{rateLimitCountdown} seconds</span>.
            </span>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-300 text-xs font-mono flex items-start justify-between gap-3 animate-fadeIn">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-rose-200">Reputation Scan Notice</div>
              <div className="text-rose-300/90 mt-0.5 font-sans text-xs">{error.message}</div>
              {process.env.NODE_ENV === "development" && error.code && (
                <span className="inline-block mt-1 text-[10px] text-rose-400/70 font-mono">Debug: {error.code}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => runScan()}
              className="px-2.5 py-1 bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 rounded border border-rose-500/40 text-[11px] transition"
            >
              Retry
            </button>
            <button
              onClick={() => setError(null)}
              className="text-zinc-400 hover:text-white text-xs px-2 py-1 rounded"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 2. Target Search & Control Bar */}
      <div className="bg-[#0E0E12]/80 backdrop-blur-md p-4 rounded-xl border border-zinc-800/80 hover:border-emerald-500/30 transition-all duration-200 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-96">
          <Globe className="w-4 h-4 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runScan();
            }}
            placeholder="Enter domain, e.g. store.com"
            className="w-full pl-9 pr-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500/50 transition-colors"
          />
        </div>

        <div className="flex items-center gap-4 text-xs font-mono text-zinc-400 flex-wrap">
          <span>
            Target: <strong className="text-emerald-400 font-mono text-xs">{scan ? scan.domain : target}</strong>
          </span>
          {scan && scan.resolved_ips && scan.resolved_ips.length > 0 && (
            <>
              <span className="text-zinc-700">•</span>
              <span>
                Public A-Records:{" "}
                <strong className="text-cyan-400 font-mono text-xs">
                  {scan.resolved_ips.join(", ")}
                </strong>
              </span>
            </>
          )}
          <span className="text-zinc-700">•</span>
          <span>
            Scanned:{" "}
            <strong className="text-white font-mono text-xs">
              {scan ? new Date(scan.scanned_at).toLocaleTimeString() : "Pending"}
            </strong>
          </span>
        </div>
      </div>

      {/* 3. Listed Incident Notification Banner if Any Provider is Listed */}
      {scan && scan.rbl_listed_count > 0 && (
        <div className="p-4 bg-rose-950/40 border border-rose-500/50 rounded-xl animate-fadeIn">
          <div className="flex items-start gap-3">
            <Flame className="w-5 h-5 text-rose-400 shrink-0 mt-0.5 animate-bounce" />
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-rose-200 uppercase tracking-wide flex items-center gap-2">
                  Active Blacklist Incident Detected ({scan.rbl_listed_count} of {scan.rbl_total_count} Lists)
                </h2>
                <span className="text-[11px] font-mono text-rose-300 font-bold px-2 py-0.5 rounded bg-rose-500/20 border border-rose-500/40">
                  SEVERITY: {scan.highest_severity.toUpperCase()}
                </span>
              </div>
              <p className="text-xs text-rose-300/90 mt-1 font-sans">
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
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs font-mono border border-rose-500/40 transition"
                    >
                      <span>{r.provider_name}</span>
                      <span className="text-rose-400 font-bold">[{r.response_codes.join(", ") || "LISTED"}]</span>
                      <ExternalLink className="w-3 h-3 ml-1 text-rose-300" />
                    </a>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 4. Partial Scan Warning Banner */}
      {scan && scan.overall_status === "partial" && scan.rbl_listed_count === 0 && (
        <div className="p-4 bg-amber-950/30 border border-amber-500/40 rounded-xl text-amber-300 text-xs font-mono flex items-start gap-3 animate-fadeIn">
          <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <div className="font-bold text-amber-200">Reputation Check In Progress (Partial Response)</div>
            <p className="text-amber-300/90 mt-0.5 font-sans">
              {scan.rbl_unknown_count} of {scan.rbl_total_count} reputation providers timed out or returned pending results. We will continue polling to verify your domain reputation status.
            </p>
          </div>
        </div>
      )}

      {/* 5. 3D Real-Time RBL Node Topology Canvas */}
      <div className="bg-[#0E0E12]/80 backdrop-blur-md p-4 rounded-xl border border-zinc-800/80 hover:border-emerald-500/30 transition-all duration-200 space-y-3 relative overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2 text-xs">
          <span className="font-mono text-emerald-400 font-bold flex items-center gap-2">
            <Radio className="w-4 h-4 animate-pulse text-emerald-400" />
            GLOBAL SPAM BLACKLIST NETWORK
          </span>
          <span className="text-[10px] font-mono text-zinc-400">
            {scan ? `${scan.rbl_total_count} AUTHORITATIVE LISTS` : "AWAITING SCAN"}
          </span>
        </div>
        <RblTopology3DCanvas rbls={canvasNodes} className="h-44 w-full" />
      </div>

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
          icon={<ShieldCheck className="w-5 h-5 text-emerald-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono">
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
          icon={<Server className="w-5 h-5 text-emerald-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono line-clamp-1">
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
          icon={<Activity className="w-5 h-5 text-emerald-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono">
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
          title="Verification Speed"
          subtitle="Check Response Speed"
          badgeText={scan ? `${scan.execution_time_ms.toFixed(0)}ms scan` : "Real-time"}
          badgeVariant="cyan"
          metricValue={avgLatency}
          icon={<Clock className="w-5 h-5 text-cyan-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono">
            {scan
              ? `Bounded 1.5s per-zone multi-resolver execution.`
              : "Real-time query response speed."}
          </p>
        </GlassEmeraldCard>
      </div>

      {/* 7. Loading Skeleton State */}
      {isLoading && !scan && (
        <div className="bg-[#0E0E12]/80 backdrop-blur-md p-8 rounded-xl border border-zinc-800/80 animate-pulse space-y-4">
          <div className="h-4 bg-zinc-800 rounded w-1/4"></div>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-zinc-900/80 rounded-lg flex items-center justify-between px-4">
                <div className="h-3 bg-zinc-800 rounded w-1/3"></div>
                <div className="h-3 bg-zinc-800 rounded w-1/6"></div>
                <div className="h-3 bg-zinc-800 rounded w-1/12"></div>
              </div>
            ))}
          </div>
          <p className="text-xs text-zinc-500 font-mono text-center pt-2">
            Scanning global reputation databases via dedicated recursive nameservers...
          </p>
        </div>
      )}

      {/* 8. True Empty State (404 / No prior scan recorded) */}
      {!isLoading && !scan && !error && (
        <OperationalEmptyState
          icon={<Radio className="w-8 h-8 text-emerald-400" />}
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
          subtitle="Real-time reputation monitoring and delisting gateway access"
          badgeText={`${scan.rbl_total_count} Lists Monitored`}
          badgeVariant="emerald"
          icon={<Activity className="w-5 h-5 text-emerald-400" />}
        >
          <div className="overflow-y-auto max-h-[360px] scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent hover:scrollbar-thumb-emerald-500/40 rounded-lg">
            <table className="w-full text-left text-xs font-mono border-collapse">
              <thead className="sticky top-0 bg-[#0E0E12] z-10 backdrop-blur-md border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-400">
                <tr>
                  <th className="py-3 px-4 font-semibold">Reputation Provider</th>
                  <th className="py-3 px-4 font-semibold">Reputation Network</th>
                  <th className="py-3 px-4 font-semibold">Target Type</th>
                  <th className="py-3 px-4 font-semibold">Measured Status</th>
                  <th className="py-3 px-4 font-semibold">Verification Speed</th>
                  <th className="py-3 px-4 font-semibold text-right">Delisting Portal</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900/60 text-zinc-300">
                {scan.results.map((rbl) => {
                  const isListed = rbl.status === "listed";
                  const isUnknown = rbl.status === "unknown";
                  const isError = rbl.status === "error";
                  const isExpanded = !!expandedRows[rbl.provider_id];

                  return (
                    <Fragment key={rbl.provider_id}>
                      <tr
                        className="border-b border-zinc-900/60 hover:bg-zinc-800/30 transition-colors cursor-pointer"
                        onClick={() => toggleRow(rbl.provider_id)}
                      >
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleRow(rbl.provider_id);
                              }}
                              className="p-0.5 rounded text-zinc-400 hover:text-emerald-400 transition cursor-pointer"
                              title={isExpanded ? "Collapse Row" : "Expand Row"}
                            >
                              <ChevronDown
                                className={`w-4 h-4 transition-transform duration-200 ${
                                  isExpanded ? "rotate-180 text-emerald-400" : "text-zinc-400"
                                }`}
                              />
                            </button>
                            <div>
                              <div className="font-bold text-white text-xs font-sans flex items-center gap-1.5">
                                {rbl.provider_name}
                              </div>
                              <div className="text-[11px] text-zinc-400 mt-0.5 line-clamp-1 font-sans">
                                Target: {rbl.queried_target}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-4 font-mono text-xs text-zinc-300">{rbl.zone}</td>
                        <td className="py-3 px-4">
                          <span className="text-[10px] uppercase font-mono font-bold px-2 py-0.5 rounded-lg bg-zinc-800/80 text-zinc-300 border border-zinc-700/50">
                            {rbl.target_type}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {isListed ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-rose-400 bg-rose-500/10 border border-rose-500/20">
                              <XCircle className="w-3.5 h-3.5" />
                              LISTED
                            </span>
                          ) : isUnknown ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-amber-400 bg-amber-500/10 border border-amber-500/20">
                              <AlertCircle className="w-3.5 h-3.5" />
                              UNKNOWN
                            </span>
                          ) : isError ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-zinc-400 bg-zinc-800 border border-zinc-700">
                              <HelpCircle className="w-3.5 h-3.5" />
                              ERROR
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/20">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              CLEAN
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 font-mono text-xs text-zinc-300">
                          {rbl.latency_ms !== null ? `${rbl.latency_ms}ms` : "--"}
                        </td>
                        <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <a
                            href={rbl.delisting_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-zinc-400 hover:text-emerald-400 font-mono text-xs inline-flex items-center gap-1 transition-colors"
                          >
                            Lookup <ExternalLink className="w-3 h-3" />
                          </a>
                        </td>
                      </tr>

                      {/* Collapsible Accordion Drawer */}
                      {isExpanded && (
                        <tr className="bg-[#08080A]/90 border-b border-zinc-800/80 animate-fadeIn">
                          <td colSpan={6} className="p-4">
                            <div className="space-y-3 font-mono text-xs">
                              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80">
                                  <span className="text-[10px] text-zinc-500 uppercase block">Response Classification</span>
                                  <span className="text-xs text-emerald-400 font-bold block mt-0.5">
                                    {rbl.response_codes.length > 0
                                      ? rbl.response_codes.join(", ")
                                      : "Clean (No Blacklist Entry)"}
                                  </span>
                                  <span className="text-[10px] text-zinc-400 block mt-0.5">
                                    Severity: {rbl.severity.toUpperCase()}
                                  </span>
                                </div>

                                <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80">
                                  <span className="text-[10px] text-zinc-500 uppercase block">Delisting Gateway</span>
                                  <span className="text-xs text-zinc-300 block mt-0.5 font-sans">
                                    Direct Provider Removal Portal
                                  </span>
                                  <a
                                    href={rbl.delisting_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[10px] text-emerald-400 hover:underline block mt-0.5"
                                  >
                                    Open Delisting Portal ↗
                                  </a>
                                </div>

                                <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80">
                                  <span className="text-[10px] text-zinc-500 uppercase block">Monitoring Status</span>
                                  <span className="text-[11px] text-zinc-300 block mt-0.5">
                                    {rbl.message || "Reputation verified clean across database."}
                                  </span>
                                  <span className="text-[10px] text-zinc-400 block mt-0.5">
                                    Verification Speed: {rbl.latency_ms !== null ? `${rbl.latency_ms}ms` : "timeout"}
                                  </span>
                                </div>
                              </div>

                              <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80 flex items-center justify-between text-xs font-sans text-zinc-400">
                                <span>Target: {rbl.queried_target} via {rbl.zone}</span>
                                <span className="font-mono text-[10px] text-zinc-500">Checked: {new Date(rbl.checked_at).toISOString()}</span>
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
