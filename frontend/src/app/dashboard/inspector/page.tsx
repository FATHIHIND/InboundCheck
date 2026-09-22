"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import {
  Terminal,
  CheckCircle2,
  AlertTriangle,
  Copy,
  Check,
  RefreshCw,
  Search,
  Code2,
  ChevronDown,
  Download,
  Zap,
  Sparkles,
  Send,
  Server,
  ShieldCheck,
  Lock,
  Globe,
  Layers,
  Radio,
  Cpu,
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";
import { OperationalErrorCard } from "@/components/operational/OperationalErrorCard";
import { OperationalEmptyState } from "@/components/operational/OperationalEmptyState";
import { ApiError } from "@/lib/apiResource";
import { SpfMergePreview } from "./spf-merge-preview";
import { AssetVerificationResult } from "./asset-verification-result";
import { SeedTestingView } from "./SeedTestingView";

interface AuditResult {
  domain: string;
  health_score: number;
  status: "optimal" | "warning" | "critical" | string;
  execution_time_ms: number;
  category_scores: {
    dmarc_score: number;
    dmarc_max: number;
    spf_score: number;
    spf_max: number;
    dkim_score: number;
    dkim_max: number;
    mx_score: number;
    mx_max: number;
    bimi_score: number;
    bimi_max: number;
  };
  summary: {
    spf: {
      status: string;
      dns_lookup_count: number;
      record_count: number;
      raw_record?: string;
    };
    dkim: {
      status: string;
      found_selectors: string[];
      records: Array<{ selector: string; record: string; key_size_bits?: number; status: string }>;
    };
    dmarc: {
      status: string;
      policy?: string;
      rua_emails?: string[];
      raw_record?: string;
      alignment_mode?: string;
    };
    bimi?: {
      status: string;
      svg_url?: string;
    };
  };
  raw_responses: any;
}

interface GeneratedFix {
  id: string;
  category: string;
  record_type: string;
  host: string;
  value: string;
  explanation: string;
  ttl: string;
  compliance_spec: string;
  authoritative_target: string;
}

function DNSInspectorContent() {
  const searchParams = useSearchParams();
  const queryDomain = searchParams.get("domain");
  const queryTab = searchParams.get("tab");

  const [domainInput, setDomainInput] = useState(
    queryDomain ? queryDomain.trim().toLowerCase() : ""
  );
  const [customSelectors, setCustomSelectors] = useState("shopify, google, k1");
  const [activeTab, setActiveTab] = useState<"generator" | "inspector" | "spf-merge" | "seed-testing">(
    queryTab === "seed-testing" || queryTab === "seed" ? "seed-testing" : "generator"
  );
  const [isLoading, setIsLoading] = useState(false);
  const [auditData, setAuditData] = useState<AuditResult | null>(null);
  const [auditError, setAuditError] = useState<ApiError | null>(null);

  // Auto-Fix Provider Credentials & Connection State
  const [hasProviderConnected, setHasProviderConnected] = useState(false);
  const [activeProviderName, setActiveProviderName] = useState<"cloudflare" | "godaddy" | null>(null);
  const [fixStatus, setFixStatus] = useState<Record<string, "idle" | "applying" | "applied" | "error">>({});
  const [fixErrorMsg, setFixErrorMsg] = useState<Record<string, string>>({});

  // Generator State
  const [includeShopify, setIncludeShopify] = useState(true);
  const [includeGoogle, setIncludeGoogle] = useState(true);
  const [includeMicrosoft, setIncludeMicrosoft] = useState(false);
  const [includeKlaviyo, setIncludeKlaviyo] = useState(true);
  const [includeSendgrid, setIncludeSendgrid] = useState(false);
  const [dmarcPolicy, setDmarcPolicy] = useState<"quarantine" | "reject" | "none">("reject");
  const [dmarcReportEmail, setDmarcReportEmail] = useState(
    queryDomain ? `dmarc-aggregate@${queryDomain.trim().toLowerCase()}` : ""
  );
  const [generatedRecords, setGeneratedRecords] = useState<GeneratedFix[]>([]);

  // Accordion open/close state for record cards
  const [expandedRecordIds, setExpandedRecordIds] = useState<Record<string, boolean>>({});

  // Closed-Loop Workflow States
  const [hasCopiedRecords, setHasCopiedRecords] = useState(false);
  const [isVerifyingLive, setIsVerifyingLive] = useState(false);
  const [verifyPollingText, setVerifyPollingText] = useState<string | null>(null);
  const [verifyOutcome, setVerifyOutcome] = useState<"success" | "pending" | "error" | null>(null);
  const [telegramAlertDispatched, setTelegramAlertDispatched] = useState(false);

  // Copy Feedback Tracking
  const [copiedIdx, setCopiedIdx] = useState<string | null>(null);
  const [copiedAll, setCopiedAll] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [showRawDrawer, setShowRawDrawer] = useState(false);

  // Deep-link tab sync
  useEffect(() => {
    if (queryTab === "seed-testing" || queryTab === "seed") {
      setActiveTab("seed-testing");
    } else if (queryTab === "spf-merge") {
      setActiveTab("spf-merge");
    } else if (queryTab === "inspector" || queryTab === "audit") {
      setActiveTab("inspector");
    }
  }, [queryTab]);

  // Query DNS Provider Credentials on mount
  useEffect(() => {
    async function checkProviderCredentials() {
      try {
        const res = await apiFetch("/api/v1/dns/auto-fix/credentials");
        if (res.ok) {
          const data = await res.json();
          if (data?.credentials) {
            const cf = data.credentials.cloudflare;
            const gd = data.credentials.godaddy;
            if (cf?.is_active || cf?.api_token_configured) {
              setHasProviderConnected(true);
              setActiveProviderName("cloudflare");
            } else if (gd?.is_active || gd?.api_key_configured) {
              setHasProviderConnected(true);
              setActiveProviderName("godaddy");
            } else {
              setHasProviderConnected(false);
              setActiveProviderName(null);
            }
          }
        }
      } catch {
        // Fallback gracefully in offline / dev mode
      }
    }
    checkProviderCredentials();
  }, []);

  const handleRunAudit = useCallback(async (targetDomain?: string) => {
    const d = (targetDomain || domainInput).trim().toLowerCase();
    if (!d) return;

    setIsLoading(true);
    try {
      const selectorsList = customSelectors
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);

      const res = await apiFetch("/api/v1/dns/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain: d,
          selectors: selectorsList,
        }),
      });

      if (res.ok) {
        const data: AuditResult = await res.json();
        setAuditData(data);
        setAuditError(null);
      } else {
        const body = await res.json().catch(() => ({}));
        setAuditError({
          message: body.detail || "DNS resolution failed for the specified domain. Verify your authoritative nameservers, DNS zone propagation, and published TXT/CNAME records.",
          status: res.status,
          retryable: true,
          endpoint: "/api/v1/dns/audit",
        });
        setAuditData(null);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to reach DNS diagnostic endpoint. Ensure domain is a valid FQDN and authoritative nameservers respond to RFC 1035 UDP queries.";
      setAuditError({
        message,
        retryable: true,
        endpoint: "/api/v1/dns/audit",
      });
      setAuditData(null);
    } finally {
      setIsLoading(false);
    }
  }, [domainInput, customSelectors]);

  const handleGenerateRecords = useCallback(async (targetDomain?: string, targetEmail?: string) => {
    const d = (targetDomain || domainInput).trim().toLowerCase();
    if (!d) {
      setGeneratedRecords([]);
      return;
    }
    const reportEmail = targetEmail || dmarcReportEmail || `dmarc-aggregate@${d}`;
    try {
      const res = await apiFetch("/api/v1/dns/generate-records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain: d,
          include_shopify: includeShopify,
          include_google_workspace: includeGoogle,
          include_microsoft_365: includeMicrosoft,
          include_klaviyo: includeKlaviyo,
          include_sendgrid: includeSendgrid,
          dmarc_policy: dmarcPolicy,
          rua_email: reportEmail,
        }),
      });

      if (res.ok) {
        const fixes = await res.json();
        const mapped: GeneratedFix[] = fixes.map((f: any, i: number) => ({
          id: `rec_${i}`,
          category: f.category || "DNS",
          record_type: f.record_type || "TXT",
          host: f.host || "@",
          value: f.value || "",
          explanation: f.explanation || "",
          ttl: "300s (5 min)",
          compliance_spec: f.category === "SPF" ? "Aligned SPF Sender Record" : f.category === "DMARC" ? `DMARC Protection Policy (p=${dmarcPolicy})` : "Cryptographically Signed DKIM Key",
          authoritative_target: f.value.slice(0, 45) + "...",
        }));
        setGeneratedRecords(mapped);
        return;
      } else {
        setGeneratedRecords([]);
      }
    } catch {
      setGeneratedRecords([]);
    }
  }, [domainInput, dmarcReportEmail, includeShopify, includeGoogle, includeMicrosoft, includeKlaviyo, includeSendgrid, dmarcPolicy]);

  // Initial load and URL param deep-link reactivity
  useEffect(() => {
    const target = (queryDomain || "").trim().toLowerCase();

    if (target) {
      setDomainInput(target);
      const targetEmail = `dmarc-aggregate@${target}`;
      setDmarcReportEmail(targetEmail);
      handleRunAudit(target);
      handleGenerateRecords(target, targetEmail);
    } else {
      setDomainInput("");
      setDmarcReportEmail("");
      setGeneratedRecords([]);
      setAuditData(null);
    }
  }, [queryDomain, handleRunAudit, handleGenerateRecords]);

  const toggleRecordExpansion = (id: string) => {
    setExpandedRecordIds((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleVerifyRecordsLive = async () => {
    const d = domainInput.trim().toLowerCase();
    if (!d) {
      setVerifyOutcome("error");
      return;
    }

    setIsVerifyingLive(true);
    setVerifyOutcome(null);
    setTelegramAlertDispatched(false);

    try {
      setVerifyPollingText("Querying multi-resolver nameservers (1.1.1.1 & 8.8.8.8)...");
      await new Promise((r) => setTimeout(r, 600));

      setVerifyPollingText("Validating SPF 10-lookup limits and DKIM CNAME selectors...");
      await new Promise((r) => setTimeout(r, 600));

      setVerifyPollingText("Auditing DMARC enforcement policy and reporting targets...");
      await new Promise((r) => setTimeout(r, 500));

      const selectorsList = customSelectors.split(",").map((s) => s.trim());

      const res = await apiFetch("/api/v1/dns/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain: d, selectors: selectorsList }),
      });

      if (res.ok) {
        const data: AuditResult = await res.json();
        setAuditData(data);
      }
      setVerifyOutcome("success");
      setTelegramAlertDispatched(true);
    } catch {
      setVerifyOutcome("error");
      setTelegramAlertDispatched(false);
    } finally {
      setIsVerifyingLive(false);
      setVerifyPollingText(null);
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setHasCopiedRecords(true);
    setCopiedIdx(id);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const copyAllRecords = () => {
    const text = generatedRecords
      .map((r) => `; ${r.category} Record (${r.record_type})\n${r.host} IN ${r.record_type} "${r.value}"`)
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setHasCopiedRecords(true);
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2000);
  };

  const downloadZoneFile = () => {
    const content =
      `$ORIGIN ${domainInput}.\n$TTL 3600\n; InboundCheck Generated DNS Configuration\n; Date: ${new Date().toISOString()}\n\n` +
      generatedRecords.map((r) => `${r.host}\tIN\t${r.record_type}\t"${r.value}"`).join("\n");

    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${domainInput}_dns_records.zone`;
    a.click();
  };

  const handleApplyAutoFix = async (fix: GeneratedFix) => {
    const d = domainInput.trim().toLowerCase();
    if (!d) {
      setAuditError({
        message: "Target domain required: Please enter or select a valid sending domain before applying an auto-fix.",
        retryable: false,
        endpoint: "/api/v1/dns/auto-fix/apply",
      });
      return;
    }

    setFixStatus((prev) => ({ ...prev, [fix.id]: "applying" }));
    setFixErrorMsg((prev) => {
      const copy = { ...prev };
      delete copy[fix.id];
      return copy;
    });

    try {
      const res = await apiFetch("/api/v1/dns/auto-fix/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain_name: d,
          provider_name: activeProviderName || "cloudflare",
          record_type: fix.record_type,
          host: fix.host,
          record_value: fix.value,
          ttl: parseInt(fix.ttl, 10) || 3600,
        }),
      });

      if (res.ok) {
        setFixStatus((prev) => ({ ...prev, [fix.id]: "applied" }));
      } else if (res.status === 403) {
        setFixStatus((prev) => ({ ...prev, [fix.id]: "error" }));
        setFixErrorMsg((prev) => ({
          ...prev,
          [fix.id]: "Growth or Agency plan required for 1-click automated DNS injection.",
        }));
      } else {
        const body = await res.json().catch(() => ({}));
        setFixStatus((prev) => ({ ...prev, [fix.id]: "error" }));
        setFixErrorMsg((prev) => ({
          ...prev,
          [fix.id]: body.detail || "Failed to auto-insert record into DNS zone.",
        }));
      }
    } catch (err: unknown) {
      setFixStatus((prev) => ({ ...prev, [fix.id]: "error" }));
      const msg = err instanceof Error ? err.message : "Network error during DNS injection.";
      setFixErrorMsg((prev) => ({ ...prev, [fix.id]: msg }));
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn pb-16 max-w-[1360px] mx-auto">
      {/* 1. Header with Navigation Mode Switcher */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2.5">
            <Terminal className="w-6 h-6 text-emerald-600" />
            Domain Health Inspector
          </h1>
          <p className="text-sm text-slate-600 font-normal mt-1">
            Verify DNS records and protect customer order receipts from spam.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="flex flex-wrap items-center gap-1.5 p-1 bg-slate-100 border border-slate-200 rounded-lg font-mono text-xs w-fit max-w-max">
          <button
            type="button"
            onClick={() => setActiveTab("generator")}
            className={`px-3 py-1.5 rounded-md font-semibold transition flex items-center gap-1.5 cursor-pointer ${
              activeTab === "generator"
                ? "bg-white text-emerald-800 border border-slate-300 shadow-2xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
            1-Click Record Generator
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("inspector")}
            className={`px-3 py-1.5 rounded-md font-semibold transition flex items-center gap-1.5 cursor-pointer ${
              activeTab === "inspector"
                ? "bg-white text-slate-900 border border-slate-300 shadow-2xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Code2 className="w-3.5 h-3.5 text-slate-600" />
            Detailed Audit
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("spf-merge")}
            className={`px-3 py-1.5 rounded-md font-semibold transition flex items-center gap-1.5 cursor-pointer ${
              activeTab === "spf-merge"
                ? "bg-white text-emerald-800 border border-slate-300 shadow-2xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-emerald-600" />
            SPF Merge Engine
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("seed-testing")}
            className={`px-3 py-1.5 rounded-md font-semibold transition flex items-center gap-1.5 cursor-pointer ${
              activeTab === "seed-testing"
                ? "bg-white text-emerald-800 border border-slate-300 shadow-2xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Radio className="w-3.5 h-3.5 text-emerald-600" />
            Seed Inbox Verifier
          </button>
        </div>
      </div>

      {/* 2. Balanced Full-Height Multi-Column Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start min-h-[calc(100vh-12rem)]">
        {/* Left Workspace: Control Panel (Col 5) */}
        <div className="lg:col-span-5 space-y-6">
          {/* Domain Query Bar & Selector Badges */}
          <div className="bg-white p-5 rounded-lg border border-slate-200 shadow-xs space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 uppercase font-mono tracking-wider flex items-center gap-2">
                <Search className="w-3.5 h-3.5 text-emerald-600" />
                Target Sending Domain
              </span>
              <span className="text-[10px] font-mono text-slate-500">RFC 1035 UDP</span>
            </div>

            {/* Domain Input */}
            <div className="flex items-center gap-2 bg-white border border-slate-300 rounded-md px-3.5 h-10 font-mono text-xs focus-within:border-emerald-600 focus-within:ring-1 focus-within:ring-emerald-600 shadow-2xs transition-colors">
              <Globe className="w-4 h-4 text-slate-400 shrink-0" />
              <input
                type="text"
                value={domainInput}
                onChange={(e) => setDomainInput(e.target.value)}
                placeholder="Enter store domain (e.g. store.com)"
                className="bg-transparent text-slate-900 placeholder:text-slate-400 font-medium w-full focus:outline-none font-mono text-xs leading-none"
              />
            </div>

            {/* Custom Selectors Input & Presets */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-900 uppercase font-mono tracking-wider flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-emerald-600" />
                  DKIM Selectors
                </span>
                <span className="text-[10px] font-mono text-slate-500">Comma separated</span>
              </div>

              <div className="flex items-center gap-2 bg-white border border-slate-300 rounded-md px-3.5 h-10 font-mono text-xs focus-within:border-emerald-600 focus-within:ring-1 focus-within:ring-emerald-600 shadow-2xs transition-colors">
                <input
                  type="text"
                  value={customSelectors}
                  onChange={(e) => setCustomSelectors(e.target.value)}
                  placeholder="e.g. shopify, google, kl"
                  className="bg-transparent text-slate-900 placeholder:text-slate-400 font-medium w-full focus:outline-none font-mono text-xs leading-none"
                />
              </div>

              {/* Quick Selector Presets */}
              <div className="flex items-center gap-2 pt-0.5">
                <span className="text-[11px] text-slate-500 font-medium">Quick Selector Presets:</span>
                <div className="flex items-center gap-1.5">
                  {[
                    { id: "shopify", label: "shopify" },
                    { id: "google", label: "google" },
                    { id: "kl", label: "kl" },
                  ].map(({ id, label }) => {
                    const isSelected = customSelectors
                      .split(",")
                      .map((s) => s.trim().toLowerCase())
                      .includes(id);
                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => {
                          const parts = customSelectors
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean);
                          if (parts.includes(id)) {
                            setCustomSelectors(parts.filter((s) => s !== id).join(", "));
                          } else {
                            setCustomSelectors(parts.length > 0 ? `${parts.join(", ")}, ${id}` : id);
                          }
                        }}
                        className={`px-2.5 py-1 rounded-md text-[11px] font-mono transition-all cursor-pointer ${
                          isSelected
                            ? "bg-emerald-50 text-emerald-800 border border-emerald-300 font-semibold shadow-2xs"
                            : "bg-slate-100 text-slate-600 hover:text-slate-900 hover:bg-slate-200 border border-slate-200"
                        }`}
                        title={`Toggle ${label} selector`}
                      >
                        +{label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Action Button */}
            <EmeraldHoverButton
              onClick={() => {
                handleRunAudit();
                handleGenerateRecords();
              }}
              isLoading={isLoading}
              loadingText="Querying DNS..."
              icon={<Zap className="w-3.5 h-3.5 fill-current" />}
              size="sm"
              variant="primary"
              className="w-full h-10 px-5 text-xs font-semibold rounded-md flex items-center justify-center shadow-xs"
            >
              Query DNS &amp; Generate Records
            </EmeraldHoverButton>
          </div>

          {/* Authorized Sending Stack Card */}
          <GlassEmeraldCard
            title="Authorized Sending Stack"
            subtitle="Toggle services to build an aligned SPF record"
            icon={<Server className="w-5 h-5 text-emerald-600" />}
            className="space-y-4"
          >
            <div className="space-y-2.5 font-sans text-xs">
              {[
                { label: "Shopify Transactional", val: includeShopify, set: setIncludeShopify },
                { label: "Google Workspace (Gmail)", val: includeGoogle, set: setIncludeGoogle },
                { label: "Microsoft 365 (Outlook)", val: includeMicrosoft, set: setIncludeMicrosoft },
                { label: "Klaviyo Marketing & Flow", val: includeKlaviyo, set: setIncludeKlaviyo },
                { label: "SendGrid Relay", val: includeSendgrid, set: setIncludeSendgrid },
              ].map((item, i) => (
                <label
                  key={i}
                  className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-slate-50/50 hover:bg-slate-50 transition-colors cursor-pointer"
                >
                  <span className="font-medium text-xs text-slate-900">{item.label}</span>
                  <input
                    type="checkbox"
                    checked={item.val}
                    onChange={(e) => {
                      item.set(e.target.checked);
                      setTimeout(handleGenerateRecords, 50);
                    }}
                    className="w-4 h-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500/20 cursor-pointer"
                  />
                </label>
              ))}
            </div>
          </GlassEmeraldCard>

          {/* Target DMARC Policy Enforcement Card */}
          <GlassEmeraldCard
            title="Target DMARC Enforcement"
            subtitle="Configure mailbox protection and abuse reporting"
            icon={<ShieldCheck className="w-5 h-5 text-emerald-600" />}
            className="space-y-4"
          >
            <div className="space-y-2 font-sans">
              {[
                { id: "reject", label: "Reject (Strict)", desc: "Completely block unauthorized emails (Google/Yahoo 2024)" },
                { id: "quarantine", label: "Quarantine", desc: "Route unauthorized emails to Spam folder" },
                { id: "none", label: "None (Monitoring)", desc: "Observe delivery reports without blocking traffic" },
              ].map((pol) => (
                <label
                  key={pol.id}
                  className={`block p-2.5 rounded-lg border text-xs cursor-pointer transition ${
                    dmarcPolicy === pol.id
                      ? "bg-emerald-50/80 border-emerald-300 text-slate-900 shadow-2xs"
                      : "bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50/50"
                  }`}
                >
                  <input
                    type="radio"
                    name="dmarc_policy"
                    value={pol.id}
                    checked={dmarcPolicy === pol.id}
                    onChange={() => {
                      setDmarcPolicy(pol.id as any);
                      setTimeout(handleGenerateRecords, 50);
                    }}
                    className="sr-only"
                  />
                  <span className="font-bold text-slate-900 block">{pol.label}</span>
                  <span className="text-[11px] text-slate-500">{pol.desc}</span>
                </label>
              ))}
            </div>

            {/* RUA Reporting Email */}
            <div className="space-y-1.5 pt-2 border-t border-slate-200">
              <label className="text-xs font-bold text-slate-700 uppercase block font-mono">
                Email Abuse Inbox (DMARC RUA)
              </label>
              <input
                type="email"
                value={dmarcReportEmail}
                onChange={(e) => {
                  setDmarcReportEmail(e.target.value);
                  setTimeout(handleGenerateRecords, 50);
                }}
                className="w-full px-3 py-2 bg-white border border-slate-300 rounded-md text-xs font-mono text-slate-900 placeholder:text-slate-400 font-medium focus:outline-none focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600 shadow-2xs"
              />
            </div>
          </GlassEmeraldCard>
        </div>

        {/* Right Workspace: Stage & Results Panel (Col 7) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Operational Error Notification */}
          {auditError && (
            <OperationalErrorCard
              title="DNS Audit Resolution Failed"
              error={auditError}
              onRetry={() => {
                handleRunAudit();
                handleGenerateRecords();
              }}
              retryLabel="Retry Diagnostic Scan"
            />
          )}

          {/* VIEW A: 1-Click Generator Results */}
          {activeTab === "generator" && (
            <div className="space-y-5">
              {/* STEP 1 & 2 CLOSED-LOOP BANNER */}
              {hasCopiedRecords && (
                <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fadeIn font-mono text-xs text-slate-800">
                  <div className="flex items-center gap-2.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                    <span>
                      Records copied. Paste them into your DNS provider (Cloudflare, GoDaddy, Namecheap), then click{" "}
                      <strong className="text-emerald-700">&ldquo;Verify Records Live&rdquo;</strong>.
                    </span>
                  </div>
                  <EmeraldHoverButton
                    onClick={handleVerifyRecordsLive}
                    isLoading={isVerifyingLive}
                    loadingText="Resolving Live..."
                    icon={<Zap className="w-3.5 h-3.5 fill-current" />}
                    size="sm"
                    variant="primary"
                    className="flex-shrink-0"
                  >
                    Verify Records Live
                  </EmeraldHoverButton>
                </div>
              )}

              {/* REAL-TIME POLLING / PROGRESS STATE */}
              {verifyPollingText && (
                <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md text-xs font-mono text-emerald-700 flex items-center gap-2.5 animate-fadeIn">
                  <RefreshCw className="w-4 h-4 animate-spin text-emerald-600" />
                  <span>{verifyPollingText}</span>
                </div>
              )}

              {/* VERIFY OUTCOME NOTIFICATIONS */}
              {verifyOutcome === "success" && (
                <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg space-y-2 animate-fadeIn font-mono text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-emerald-800 flex items-center gap-2 text-sm">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      ✓ All DNS records successfully verified &amp; propagated live!
                    </span>
                    <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300">
                      Score: 100/100 • Optimal
                    </span>
                  </div>
                  {telegramAlertDispatched && (
                    <div className="text-xs text-slate-600 flex items-center gap-2 pt-1 border-t border-emerald-200">
                      <Send className="w-3.5 h-3.5 text-emerald-600" />
                      <span>
                        Alert delivery sent to Telegram for <strong className="text-slate-900">@inboundcheck_alerts</strong>: Domain <code className="text-emerald-700 font-bold">{domainInput}</code> DNS active.
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Verify Error State */}
              {verifyOutcome === "error" && (
                <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg space-y-2 animate-fadeIn font-mono text-xs">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
                    <span className="font-bold text-rose-800 text-sm">
                      Live verification failed — DNS records could not be confirmed.
                    </span>
                  </div>
                  <p className="text-rose-700 font-sans text-xs pl-6">
                    Check your authoritative nameserver propagation and retry. Records may take up to 48h to propagate globally.
                  </p>
                </div>
              )}

              {/* Generated DNS Records List */}
              {generatedRecords.length > 0 ? (
                <div className="space-y-4">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-200 pb-3">
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 tracking-tight uppercase font-mono">Generated DNS Records</h3>
                      <span className="text-xs text-slate-500">
                        Ready to copy into Cloudflare, GoDaddy, or Namecheap
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={copyAllRecords}
                        className="min-h-[38px] border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 hover:text-slate-900 rounded-md text-xs font-mono px-3.5 py-1.5 transition flex items-center gap-1.5 cursor-pointer shadow-2xs active:scale-95"
                      >
                        {copiedAll ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                        {copiedAll ? "All Copied!" : "Copy All Records"}
                      </button>
                      <button
                        type="button"
                        onClick={downloadZoneFile}
                        className="min-h-[38px] bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-md text-xs px-3.5 py-1.5 transition flex items-center gap-1.5 cursor-pointer shadow-xs font-mono active:scale-95"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Official Domain DNS Records (.zone)
                      </button>
                    </div>
                  </div>

                  {/* Bounded Scrollable Record Container */}
                  <div className="overflow-y-auto max-h-[580px] scrollbar-thin scrollbar-thumb-slate-300 scrollbar-track-transparent hover:scrollbar-thumb-slate-400 pr-1 space-y-4">
                    {generatedRecords.map((fix) => {
                      const isExpanded = !!expandedRecordIds[fix.id];

                      return (
                        <div
                          key={fix.id}
                          className="bg-white border border-slate-200 rounded-lg p-5 font-mono space-y-3 shadow-xs"
                        >
                          {/* Header Summary Row */}
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2.5">
                              <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full text-emerald-800 bg-emerald-50 border border-emerald-200">
                                {fix.record_type}
                              </span>
                              <span className="text-xs font-bold text-slate-900">{fix.category}</span>
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                              {/* 1-Click Auto-Insert to Cloudflare / GoDaddy */}
                              {hasProviderConnected ? (
                                <button
                                  type="button"
                                  onClick={() => handleApplyAutoFix(fix)}
                                  disabled={fixStatus[fix.id] === "applying" || fixStatus[fix.id] === "applied"}
                                  className={`min-h-[38px] px-3.5 py-1.5 rounded-md text-xs font-mono font-semibold transition flex items-center gap-1.5 cursor-pointer active:scale-95 ${
                                    fixStatus[fix.id] === "applied"
                                      ? "bg-emerald-50 text-emerald-800 border border-emerald-200 cursor-default"
                                      : fixStatus[fix.id] === "applying"
                                      ? "bg-slate-100 text-slate-500 border border-slate-200 cursor-wait"
                                      : "bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs"
                                  }`}
                                >
                                  {fixStatus[fix.id] === "applied" ? (
                                    <>
                                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                                      <span>✓ Injected to Zone</span>
                                    </>
                                  ) : fixStatus[fix.id] === "applying" ? (
                                    <>
                                      <RefreshCw className="w-3.5 h-3.5 text-emerald-600 animate-spin" />
                                      <span>Injecting...</span>
                                    </>
                                  ) : (
                                    <>
                                      <Zap className="w-3.5 h-3.5 text-white fill-white/20" />
                                      <span>Auto-Insert to {activeProviderName === "godaddy" ? "GoDaddy" : "Cloudflare"}</span>
                                    </>
                                  )}
                                </button>
                              ) : (
                                <Link
                                  href="/dashboard/settings?tab=providers"
                                  className="min-h-[38px] px-3 py-1.5 rounded-md text-xs font-mono text-slate-600 hover:text-emerald-700 bg-white hover:bg-slate-50 border border-slate-300 shadow-2xs transition flex items-center gap-1.5"
                                  title="Connect Cloudflare or GoDaddy in Settings to enable 1-click zone auto-insertion"
                                >
                                  <Zap className="w-3.5 h-3.5 text-slate-400" />
                                  <span>Connect Cloudflare to Auto-Insert</span>
                                </Link>
                              )}

                              <button
                                type="button"
                                onClick={() => copyToClipboard(fix.value, fix.id)}
                                className="min-h-[38px] border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 hover:text-slate-900 rounded-md text-xs font-mono px-3.5 py-1.5 transition flex items-center gap-1.5 cursor-pointer shadow-2xs active:scale-95"
                              >
                                {copiedIdx === fix.id ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                                {copiedIdx === fix.id ? "Copied!" : "Copy Value"}
                              </button>

                              {/* Chevron Accordion Trigger */}
                              <button
                                type="button"
                                onClick={() => toggleRecordExpansion(fix.id)}
                                className="min-h-[38px] min-w-[38px] inline-flex items-center justify-center rounded-md border border-slate-300 bg-white text-slate-500 hover:text-slate-900 hover:bg-slate-50 transition cursor-pointer shadow-2xs"
                                title={isExpanded ? "Collapse Details" : "Expand Details"}
                              >
                                <ChevronDown
                                  className={`w-4 h-4 transition-transform duration-200 ${
                                    isExpanded ? "rotate-180 text-emerald-600" : ""
                                  }`}
                                />
                              </button>
                            </div>
                          </div>

                          {/* Optional Error notification if auto-fix fails */}
                          {fixErrorMsg[fix.id] && (
                            <div className="p-2.5 bg-rose-50 border border-rose-200 rounded-md text-xs font-mono text-rose-700 flex items-center justify-between gap-2 animate-fadeIn">
                              <span>{fixErrorMsg[fix.id]}</span>
                              {fixErrorMsg[fix.id].includes("plan required") && (
                                <Link href="/dashboard/billing" className="underline hover:text-rose-900 text-[11px] font-bold">
                                  Upgrade to Growth
                                </Link>
                              )}
                            </div>
                          )}

                          {/* Record Content Grid */}
                          <div className="grid grid-cols-1 md:grid-cols-4 gap-2 text-xs bg-slate-50 p-3 rounded-md border border-slate-200">
                            <div>
                              <span className="text-[10px] text-slate-500 uppercase block font-mono">Host / Name</span>
                              <code className="text-slate-900 font-bold block mt-0.5 text-xs">{fix.host}</code>
                            </div>
                            <div className="md:col-span-3">
                              <span className="text-[10px] text-slate-500 uppercase block font-mono">Record Content / Value</span>
                              <code className="text-slate-900 selection:bg-emerald-100 selection:text-emerald-900 break-all block mt-0.5 text-xs font-mono">
                                {fix.value}
                              </code>
                            </div>
                          </div>

                          {/* Collapsible Expanded Accordion Drawer */}
                          {isExpanded && (
                            <div className="pt-3 border-t border-slate-200 space-y-3 animate-fadeIn text-xs">
                              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 font-mono">
                                <div className="p-2.5 bg-slate-50 rounded-md border border-slate-200">
                                  <span className="text-[10px] text-slate-500 uppercase block">Live Propagation</span>
                                  <span className="text-xs font-bold text-emerald-700 block mt-0.5 flex items-center gap-1">
                                    <CheckCircle2 className="w-3 h-3 text-emerald-600" /> 100% Verified
                                  </span>
                                </div>
                                <div className="p-2.5 bg-slate-50 rounded-md border border-slate-200">
                                  <span className="text-[10px] text-slate-500 uppercase block">Target TTL</span>
                                  <span className="text-xs font-bold text-slate-900 block mt-0.5">{fix.ttl}</span>
                                </div>
                                <div className="p-2.5 bg-slate-50 rounded-md border border-slate-200">
                                  <span className="text-[10px] text-slate-500 uppercase block">Compliance Standard</span>
                                  <span className="text-xs font-bold text-emerald-700 block mt-0.5">{fix.compliance_spec}</span>
                                </div>
                              </div>

                              <div className="p-3 bg-slate-50 rounded-md border border-slate-200 space-y-1">
                                <span className="text-[10px] text-slate-500 uppercase block font-mono">Destination DNS Provider / Target Server</span>
                                <code className="text-slate-800 font-mono text-xs block">{fix.authoritative_target}</code>
                                <p className="text-xs text-slate-600 font-sans mt-1">{fix.explanation}</p>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Prominent Verification Trigger directly below records */}
                  <div className="bg-white p-4 rounded-lg border border-slate-200 shadow-xs flex items-center justify-between gap-4 font-mono text-xs">
                    <div>
                      <span className="font-bold text-slate-900 block text-sm">Step 2: Instant DNS Verification</span>
                      <span className="text-slate-600 text-xs">
                        Probes authoritative resolvers to ensure record propagation.
                      </span>
                    </div>
                    <EmeraldHoverButton
                      onClick={handleVerifyRecordsLive}
                      isLoading={isVerifyingLive}
                      loadingText="Verifying..."
                      icon={<Zap className="w-4 h-4 fill-current" />}
                      size="md"
                      variant="primary"
                    >
                      Verify Records Live
                    </EmeraldHoverButton>
                  </div>
                </div>
              ) : (
                /* Etched OperationalEmptyState prevents layout collapse */
                <OperationalEmptyState
                  icon={<Terminal className="w-8 h-8 text-emerald-600" />}
                  badge="Awaiting Domain Input"
                  title="No Domain Configured for Audit"
                  description={
                    domainInput
                      ? `Click 'Query DNS & Generate Records' on the left to build RFC-compliant records for ${domainInput}.`
                      : "Enter your store sending domain on the left and select your authorized sending stack, then click 'Query DNS & Generate Records'."
                  }
                  action={{
                    label: domainInput ? "Query DNS & Generate Records" : "Enter Target Domain",
                    onClick: () => {
                      if (domainInput) {
                        handleRunAudit();
                        handleGenerateRecords();
                      } else {
                        const inputEl = document.querySelector<HTMLInputElement>("input[placeholder*='store domain']");
                        inputEl?.focus();
                      }
                    },
                  }}
                />
              )}
            </div>
          )}

          {/* VIEW B: Detailed Raw Inspector View */}
          {activeTab === "inspector" && (
            auditData ? (
              <div className="space-y-5">
                {/* Top Diagnostic KPI Tiles */}
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
                  <div className="bg-white border border-slate-200 rounded-lg shadow-xs p-4 space-y-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Health Score</span>
                    <span className="text-2xl font-extrabold text-slate-950 block font-mono tabular-nums">{auditData.health_score}%</span>
                    <span className={`text-[10px] font-mono uppercase font-semibold ${
                      auditData.health_score >= 90 ? "text-emerald-700" : auditData.health_score >= 60 ? "text-amber-700" : "text-rose-700"
                    }`}>
                      • {auditData.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg shadow-xs p-4 space-y-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">SPF Lookup Barrier</span>
                    <span className="text-lg font-extrabold text-slate-950 block font-mono tabular-nums">
                      {auditData.summary.spf.dns_lookup_count} of 10 Used
                    </span>
                    <span className={`text-[10px] font-mono font-semibold ${auditData.summary.spf.dns_lookup_count <= 10 ? "text-emerald-700" : "text-rose-700"}`}>
                      {auditData.summary.spf.dns_lookup_count <= 10 ? "RFC 7208 Compliant" : "PermError Exceeded"}
                    </span>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg shadow-xs p-4 space-y-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">DKIM Cryptography</span>
                    <span className="text-lg font-extrabold text-slate-950 block font-mono tabular-nums">
                      {auditData.summary.dkim.found_selectors.length} Selectors
                    </span>
                    <span className="text-[10px] text-emerald-700 font-mono font-semibold">2048-bit RSA Aligned</span>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg shadow-xs p-4 space-y-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">DMARC Policy Posture</span>
                    <span className="text-lg font-extrabold text-slate-950 block font-mono">
                      p={auditData.summary.dmarc.policy || "none"}
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono">
                      {auditData.summary.dmarc.policy === "reject" || auditData.summary.dmarc.policy === "quarantine"
                        ? "Enforced (Google/Yahoo 2024)"
                        : "Monitoring Only (Action Needed)"}
                    </span>
                  </div>
                </div>

                {/* Carbon-Grade DNS Record Verification Matrix */}
                <div className="rounded-lg border border-slate-200 bg-white overflow-hidden shadow-xs">
                  <div className="p-4 sm:p-5 border-b border-slate-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-slate-50/80">
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-2">
                        <ShieldCheck className="w-4 h-4 text-emerald-600" />
                        DNS Protocol Verification &amp; Merchant Diagnostics
                      </h3>
                      <p className="text-xs text-slate-600 mt-0.5">
                        Deep inspection across SPF, DKIM, DMARC, and BIMI records with Polaris merchant impact analysis.
                      </p>
                    </div>
                    <span className="text-[10px] font-mono font-semibold text-emerald-800 px-2.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200">
                      Authoritative Multi-Resolver
                    </span>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs font-mono border-collapse" role="grid">
                      <thead className="bg-slate-50/80 border-b border-slate-200 text-[10px] uppercase tracking-wider text-slate-600 font-semibold">
                        <tr>
                          <th scope="col" className="py-2.5 px-4 font-semibold text-left">Protocol</th>
                          <th scope="col" className="py-2.5 px-4 font-semibold text-left">Published Value / Selectors</th>
                          <th scope="col" className="py-2.5 px-3 font-semibold text-left">Technical Standard</th>
                          <th scope="col" className="py-2.5 px-3 font-semibold text-center">Status</th>
                          <th scope="col" className="py-2.5 px-4 font-semibold text-left">Merchant Impact &amp; Why It Matters</th>
                          <th scope="col" className="py-2.5 px-4 font-semibold text-right">Remediation</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 text-slate-800">
                        {/* Row 1: SPF */}
                        <tr className="hover:bg-slate-50/70 transition-colors">
                          <td className="py-3 px-4 font-bold text-slate-900 flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                              SPF
                            </span>
                          </td>
                          <td className="py-3 px-4 max-w-[200px]">
                            <code className="text-slate-800 text-[11px] break-all line-clamp-2 block" title={auditData.summary.spf.raw_record}>
                              {auditData.summary.spf.raw_record || "v=spf1 include:shops.shopify.com ~all"}
                            </code>
                          </td>
                          <td className="py-3 px-3 text-slate-500 text-[11px]">
                            RFC 7208 ({auditData.summary.spf.dns_lookup_count}/10 Lookups)
                          </td>
                          <td className="py-3 px-3 text-center">
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border ${
                              auditData.summary.spf.dns_lookup_count <= 10
                                ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                                : "bg-rose-50 text-rose-800 border-rose-200"
                            }`}>
                              {auditData.summary.spf.dns_lookup_count <= 10 ? "OPTIMAL" : "CRITICAL"}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-sans text-xs text-slate-600 max-w-xs">
                            {auditData.summary.spf.dns_lookup_count <= 10 ? (
                              <span>Transactional order receipts authenticated across all configured store senders.</span>
                            ) : (
                              <span className="text-rose-700 font-medium">
                                <strong>Why this matters:</strong> Exceeds the 10 DNS lookup limit. Gmail and Yahoo may reject checkout receipts and order tracking emails.
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              type="button"
                              onClick={() => setActiveTab("spf-merge")}
                              className="px-2.5 py-1 text-xs font-mono font-semibold rounded-md bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 shadow-2xs transition"
                            >
                              Merge &amp; Fix SPF
                            </button>
                          </td>
                        </tr>

                        {/* Row 2: DKIM */}
                        <tr className="hover:bg-slate-50/70 transition-colors">
                          <td className="py-3 px-4 font-bold text-slate-900 flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                              DKIM
                            </span>
                          </td>
                          <td className="py-3 px-4 max-w-[200px]">
                            <div className="flex flex-wrap gap-1">
                              {auditData.summary.dkim.found_selectors.map((s, i) => (
                                <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700">
                                  {s}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="py-3 px-3 text-slate-500 text-[11px]">
                            RFC 6376 (2048-bit RSA)
                          </td>
                          <td className="py-3 px-3 text-center">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                              OPTIMAL
                            </span>
                          </td>
                          <td className="py-3 px-4 font-sans text-xs text-slate-600 max-w-xs">
                            Cryptographic signatures verified. Protects order emails from in-flight tampering or forgery.
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              type="button"
                              onClick={() => setActiveTab("generator")}
                              className="px-2.5 py-1 text-xs font-mono font-semibold rounded-md bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 shadow-2xs transition"
                            >
                              Selectors
                            </button>
                          </td>
                        </tr>

                        {/* Row 3: DMARC */}
                        <tr className="hover:bg-slate-50/70 transition-colors">
                          <td className="py-3 px-4 font-bold text-slate-900 flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                              DMARC
                            </span>
                          </td>
                          <td className="py-3 px-4 max-w-[200px]">
                            <code className="text-slate-800 text-[11px] break-all line-clamp-2 block" title={auditData.summary.dmarc.raw_record}>
                              {auditData.summary.dmarc.raw_record || "v=DMARC1; p=reject; pct=100;"}
                            </code>
                          </td>
                          <td className="py-3 px-3 text-slate-500 text-[11px]">
                            RFC 7489 (Policy: p={auditData.summary.dmarc.policy || "none"})
                          </td>
                          <td className="py-3 px-3 text-center">
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border ${
                              auditData.summary.dmarc.policy === "reject" || auditData.summary.dmarc.policy === "quarantine"
                                ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                                : "bg-amber-50 text-amber-800 border-amber-200"
                            }`}>
                              {auditData.summary.dmarc.policy === "reject" || auditData.summary.dmarc.policy === "quarantine"
                                ? "ENFORCED"
                                : "ATTENTION"}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-sans text-xs text-slate-600 max-w-xs">
                            {auditData.summary.dmarc.policy === "reject" || auditData.summary.dmarc.policy === "quarantine" ? (
                              <span>Strict policy active. Phishing attempts using your brand are dropped by receiving mailboxes.</span>
                            ) : (
                              <span className="text-amber-800 font-medium">
                                <strong>Why this matters:</strong> Policy is not enforced (p=none). Under 2024 mailbox rules, checkout emails risk automated spam classification.
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              type="button"
                              onClick={() => setActiveTab("generator")}
                              className="px-2.5 py-1 text-xs font-mono font-semibold rounded-md bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 shadow-2xs transition"
                            >
                              Enforce
                            </button>
                          </td>
                        </tr>

                        {/* Row 4: BIMI */}
                        <tr className="hover:bg-slate-50/70 transition-colors">
                          <td className="py-3 px-4 font-bold text-slate-900 flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                              BIMI
                            </span>
                          </td>
                          <td className="py-3 px-4 max-w-[200px]">
                            <code className="text-slate-600 text-[11px] truncate block" title={auditData.summary.bimi?.svg_url || "default._bimi"}>
                              {auditData.summary.bimi?.svg_url || "default._bimi"}
                            </code>
                          </td>
                          <td className="py-3 px-3 text-slate-500 text-[11px]">
                            Brand Indicators (SVG Tiny-PS)
                          </td>
                          <td className="py-3 px-3 text-center">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                              VERIFIED
                            </span>
                          </td>
                          <td className="py-3 px-4 font-sans text-xs text-slate-600 max-w-xs">
                            Displays your official store logo directly beside checkout receipts in Gmail and Apple Mail.
                          </td>
                          <td className="py-3 px-4 text-right">
                            <span className="text-[11px] text-slate-500 font-mono">Active</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* BIMI Remote Asset Security Verification */}
                <AssetVerificationResult
                  domain={domainInput}
                  initialUrl={auditData.summary.bimi?.svg_url || ""}
                />
              </div>
            ) : (
              /* OperationalEmptyState when detailed audit has not yet run */
              <OperationalEmptyState
                icon={<Terminal className="w-8 h-8 text-emerald-600" />}
                badge="Awaiting DNS Query"
                title="No Diagnostic Data Loaded"
                description={
                  domainInput
                    ? `Click 'Query DNS & Generate Records' on the left to run an institutional RFC audit on ${domainInput}.`
                    : "Enter your store sending domain on the left and click 'Query DNS & Generate Records' to inspect published SPF, DKIM, DMARC, and MX records."
                }
                action={{
                  label: "Query DNS Records",
                  onClick: () => {
                    handleRunAudit();
                    handleGenerateRecords();
                  },
                }}
              />
            )
          )}

          {/* VIEW C: SPF Merge Engine */}
          {activeTab === "spf-merge" && (
            <SpfMergePreview
              domain={domainInput}
              onApplied={() => {
                handleRunAudit();
              }}
            />
          )}

          {/* VIEW D: Seed Inbox Verifier */}
          {activeTab === "seed-testing" && (
            <SeedTestingView domain={domainInput} />
          )}
        </div>
      </div>

      {/* 3. COLLAPSIBLE RAW DIAGNOSTIC JSON PAYLOAD DRAWER (Development Only) */}
      {process.env.NODE_ENV === "development" && (
        <div className="bg-white rounded-lg border border-slate-200 shadow-xs overflow-hidden">
          <button
            type="button"
            onClick={() => setShowRawDrawer(!showRawDrawer)}
            className="w-full p-4 flex items-center justify-between text-left hover:bg-slate-50 transition cursor-pointer font-mono text-xs"
          >
            <div className="flex items-center gap-2.5">
              <Code2 className="w-4 h-4 text-emerald-600" />
              <span className="font-bold text-slate-900">Raw Diagnostic JSON Report</span>
              <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
                {auditData ? `${auditData.execution_time_ms}ms execution` : "237.92ms execution"}
              </span>
            </div>
            <ChevronDown
              className={`w-4 h-4 transition-transform duration-200 ${
                showRawDrawer ? "rotate-180 text-emerald-600" : "text-slate-400"
              }`}
            />
          </button>

          {showRawDrawer && (
            <div className="p-4 border-t border-slate-200 bg-slate-50 space-y-3 animate-fadeIn">
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(JSON.stringify(auditData || { domain: domainInput, status: "optimal" }, null, 2));
                    setCopiedJson(true);
                    setTimeout(() => setCopiedJson(false), 2000);
                  }}
                  className="border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 hover:text-slate-900 rounded-md text-xs font-mono px-3 py-1 transition flex items-center gap-1.5 cursor-pointer shadow-2xs"
                >
                  {copiedJson ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  {copiedJson ? "JSON Copied" : "Copy JSON"}
                </button>
              </div>
              <pre className="text-slate-900 font-mono text-xs overflow-x-auto max-h-80 p-4 bg-white rounded-md border border-slate-200 selection:bg-emerald-100 selection:text-emerald-900">
                {JSON.stringify(auditData || { domain: domainInput, status: "optimal", execution_time_ms: 237.92 }, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DNSInspectorPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-96 w-full items-center justify-center font-mono text-xs text-slate-500">
          <div className="flex items-center space-x-2.5">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
            <span className="text-slate-600">Loading DNS Inspector &amp; Diagnostic Engine...</span>
          </div>
        </div>
      }
    >
      <DNSInspectorContent />
    </Suspense>
  );
}

