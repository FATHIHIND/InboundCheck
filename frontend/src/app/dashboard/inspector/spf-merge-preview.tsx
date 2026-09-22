"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Layers,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Copy,
  Check,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  Server,
  Zap,
  Info,
  ExternalLink,
  ArrowRight
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";
import Link from "next/link";

export interface SpfMechanism {
  raw: string;
  kind: string;
  qualifier: string;
  normalized_value: string;
  source_record_indexes: number[];
}

export interface SpfLookupBudget {
  static_terms: number;
  recursively_resolved_terms: number;
  maximum_allowed: number;
  status: "within_limit" | "over_limit" | "unknown";
  resolution_failures: string[];
}

export interface SpfMergeWarning {
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
}

export interface SpfMergePlanResponse {
  plan_id: string;
  domain: string;
  source_records: string[];
  proposed_record: string | null;
  mechanisms: SpfMechanism[];
  removed_duplicates: string[];
  warnings: SpfMergeWarning[];
  lookup_budget: SpfLookupBudget;
  safe_to_apply: boolean;
  requires_manual_review: boolean;
  expires_at: string;
}

interface SpfMergePreviewProps {
  domain: string;
  onApplied?: () => void;
  className?: string;
}

export const SpfMergePreview: React.FC<SpfMergePreviewProps> = ({
  domain,
  onApplied,
  className = "",
}) => {
  const [plan, setPlan] = useState<SpfMergePlanResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [preferredQualifier, setPreferredQualifier] = useState<"~all" | "-all">("~all");
  const [copied, setCopied] = useState<boolean>(false);
  const [isApplying, setIsApplying] = useState<boolean>(false);
  const [applySuccess, setApplySuccess] = useState<boolean>(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [isTierLocked, setIsTierLocked] = useState<boolean>(false);
  const [configuredProvider, setConfiguredProvider] = useState<"cloudflare" | "godaddy">("cloudflare");

  useEffect(() => {
    async function checkProvider() {
      try {
        const res = await apiFetch("/api/v1/dns/auto-fix/credentials");
        if (res.ok) {
          const data = await res.json();
          if (data?.credentials?.godaddy?.api_token_configured && !data?.credentials?.cloudflare?.api_token_configured) {
            setConfiguredProvider("godaddy");
          } else {
            setConfiguredProvider("cloudflare");
          }
        }
      } catch {}
    }
    checkProvider();
  }, []);

  const generatePlan = useCallback(
    async (qualifier: "~all" | "-all" = preferredQualifier) => {
      if (!domain || domain.trim().length < 3) return;
      setIsLoading(true);
      setError(null);
      setApplySuccess(false);

      try {
        const res = await apiFetch("/api/v1/dns/spf-merge-plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            domain: domain.trim(),
            preferred_qualifier: qualifier,
          }),
        });

        if (!res.ok) {
          const errJson = await res.json().catch(() => ({}));
          throw new Error(errJson.detail || `Failed to calculate merge plan (HTTP ${res.status})`);
        }

        const data: SpfMergePlanResponse = await res.json();
        setPlan(data);
      } catch (err: unknown) {
        console.error("SPF Merge Plan Error:", err);
        const msg = err instanceof Error ? err.message : "Failed to generate SPF merge plan";
        setError(msg);
      } finally {
        setIsLoading(false);
      }
    },
    [domain, preferredQualifier]
  );

  useEffect(() => {
    generatePlan();
  }, [domain, generatePlan]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2200);
  };

  const handleApply = async () => {
    if (!plan || !plan.proposed_record || !plan.safe_to_apply || plan.requires_manual_review) return;
    setIsApplying(true);
    setApplyError(null);
    setIsTierLocked(false);
    setApplySuccess(false);

    try {
      const res = await apiFetch("/api/v1/dns/auto-fix/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain_name: domain.trim(),
          provider_name: configuredProvider,
          record_type: "TXT",
          host: "@",
          record_value: plan.proposed_record,
          ttl: 3600,
        }),
      });

      if (res.status === 403) {
        setIsTierLocked(true);
        const data = await res.json().catch(() => ({}));
        setApplyError(data.detail || "1-Click DNS Auto-Fix is reserved for Growth & Agency tiers.");
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || data.error || `Failed to inject record (HTTP ${res.status})`);
      }

      setApplySuccess(true);
      if (onApplied) onApplied();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to apply consolidated SPF record.";
      setApplyError(msg);
    } finally {
      setIsApplying(false);
    }
  };

  const totalLookups = plan
    ? plan.lookup_budget.static_terms + plan.lookup_budget.recursively_resolved_terms
    : 0;

  const isOverLimit = totalLookups > 10;

  return (
    <div
      className={`rounded-lg border border-slate-200 bg-white p-6 shadow-xs space-y-6 ${className}`}
    >
      {/* 1. Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-600">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base sm:text-lg font-bold text-slate-900 flex items-center gap-2">
              Smart SPF Conflict Resolver
              {plan && plan.source_records.length > 1 && (
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-rose-50 text-rose-800 border border-rose-200">
                  Multiple Records ({plan.source_records.length})
                </span>
              )}
            </h3>
            <p className="text-xs text-slate-600">
              Automated duplicate cleanup, DNS lookup budget protection, and safe sender consolidation.
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-end sm:items-center gap-2">
          <div className="flex flex-col items-end gap-1">
            {/* Qualifier Switcher */}
            <div className="flex items-center rounded-md bg-slate-100 border border-slate-200 p-0.5 text-xs font-mono">
              <button
                type="button"
                onClick={() => {
                  setPreferredQualifier("~all");
                  generatePlan("~all");
                }}
                className={`px-3 py-1.5 rounded-md transition cursor-pointer ${
                  preferredQualifier === "~all"
                    ? "bg-white text-emerald-800 font-bold border border-slate-300 shadow-2xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
                title="Flexible Delivery Mode: Permits legitimate forwarders while tagging unlisted IPs"
              >
                Flexible Delivery Mode (~all)
              </button>
              <button
                type="button"
                onClick={() => {
                  setPreferredQualifier("-all");
                  generatePlan("-all");
                }}
                className={`px-3 py-1.5 rounded-md transition cursor-pointer ${
                  preferredQualifier === "-all"
                    ? "bg-white text-emerald-800 font-bold border border-slate-300 shadow-2xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
                title="Strict Blocking Mode: Commands mailbox providers to immediately reject unauthorized IPs"
              >
                Strict Blocking Mode (-all)
              </button>
            </div>
            <span className="text-[10px] text-slate-500 font-sans text-right">
              {preferredQualifier === "~all"
                ? "Recommended: SoftFail lets legitimate automated receipts pass safely without bounce risks."
                : "Strict: HardFail requests mailboxes immediately drop unlisted sending IPs."}
            </span>
          </div>

          <button
            type="button"
            onClick={() => generatePlan()}
            disabled={isLoading}
            className="p-2 rounded-md bg-white hover:bg-slate-50 border border-slate-300 text-slate-600 hover:text-slate-900 transition disabled:opacity-50 cursor-pointer self-start sm:self-center shadow-2xs"
            title="Recalculate Merge Plan"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin text-emerald-600" : ""}`} />
          </button>
        </div>
      </div>

      {isLoading && !plan ? (
        <div className="py-12 flex flex-col items-center justify-center space-y-3">
          <RefreshCw className="w-8 h-8 text-emerald-600 animate-spin" />
          <p className="text-xs text-slate-600 font-mono">
            Querying apex TXT records &amp; analyzing recursive includes for {domain}...
          </p>
        </div>
      ) : error ? (
        <div className="p-4 rounded-lg border border-rose-200 bg-rose-50 text-rose-800 space-y-2 text-xs">
          <div className="flex items-center gap-2 font-semibold">
            <XCircle className="w-4 h-4 text-rose-600" />
            <span>Merge Engine Failed</span>
          </div>
          <p>{error}</p>
        </div>
      ) : plan ? (
        <>
          {/* 2. Source Records Detected */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 uppercase font-mono font-semibold">
                Discovered Source Records ({plan.source_records.length})
              </span>
              {plan.source_records.length > 1 ? (
                <span className="text-rose-700 font-mono font-semibold flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-600" /> Multiple SPF Records Detected (Delivery Failure)
                </span>
              ) : (
                <span className="text-emerald-700 font-mono font-semibold flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> Single SPF Record
                </span>
              )}
            </div>

            <div className="space-y-1.5">
              {plan.source_records.map((rec, idx) => (
                <div
                  key={idx}
                  className="p-2.5 rounded-md bg-slate-50 border border-slate-200 font-mono text-xs text-slate-800 flex items-start justify-between gap-2 overflow-x-auto"
                >
                  <div className="flex items-center gap-2">
                    <span className="px-1.5 py-0.5 rounded bg-slate-200/70 text-[10px] text-slate-700 font-semibold shrink-0">
                      Record {idx + 1}
                    </span>
                    <span className="text-slate-900">{rec}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 3. Lookup Budget & Mechanism Analytics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* KPI: DNS Lookups Gauge */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase text-slate-500 font-mono">DNS Lookup Budget</span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-mono font-bold ${
                    isOverLimit
                      ? "bg-rose-50 text-rose-800 border border-rose-200"
                      : "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  }`}
                >
                  {totalLookups}/10 Used
                </span>
              </div>

              <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
                <div
                  className={`h-full transition-all duration-500 ${
                    isOverLimit ? "bg-rose-600" : totalLookups >= 8 ? "bg-amber-500" : "bg-emerald-600"
                  }`}
                  style={{ width: `${Math.min(100, (totalLookups / 10) * 100)}%` }}
                />
              </div>

              <div className="flex justify-between text-[10px] font-mono text-slate-500">
                <span>Apex Lookups: {plan.lookup_budget.static_terms}</span>
                <span>Recursive: {plan.lookup_budget.recursively_resolved_terms}</span>
              </div>
            </div>

            {/* KPI: Sender Rule Cleanup */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-xs uppercase text-slate-500 font-mono block">Sender Rule Cleanup</span>
              <div className="flex items-baseline gap-2">
                {plan.removed_duplicates.length === 0 ? (
                  <span className="text-xs font-medium text-emerald-700">
                    Clean Record: No duplicate sender rules detected
                  </span>
                ) : (
                  <>
                    <span className="text-xl font-bold font-mono text-slate-900">
                      {plan.removed_duplicates.length}
                    </span>
                    <span className="text-xs text-slate-600">duplicate sender rules cleaned</span>
                  </>
                )}
              </div>
              <p className="text-[10px] text-slate-500 font-mono">
                {plan.mechanisms.length} total sender rules consolidated
              </p>
            </div>

            {/* KPI: Plan Safety Assessment */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-xs uppercase text-slate-500 font-mono block">Application Gate</span>
              <div className="flex items-center gap-2">
                {plan.safe_to_apply ? (
                  <>
                    <ShieldCheck className="w-5 h-5 text-emerald-600" />
                    <span className="text-sm font-bold text-emerald-700 font-mono">Safe to Auto-Apply</span>
                  </>
                ) : (
                  <>
                    <ShieldAlert className="w-5 h-5 text-amber-600" />
                    <span className="text-sm font-bold text-amber-700 font-mono">Manual Review Req</span>
                  </>
                )}
              </div>
              <p className="text-[10px] text-slate-500">
                {plan.safe_to_apply
                  ? "Within standard 10-lookup limit & has zero syntax conflicts"
                  : "Contains warnings, lookup overflow, or modifiers"}
              </p>
            </div>
          </div>

          {/* 4. Warnings and Deliverability Compliance Notices */}
          {plan.warnings.length > 0 && (
            <div className="space-y-2">
              <span className="text-xs text-slate-500 uppercase font-mono font-semibold">
                Policy Warnings &amp; Compliance Notes ({plan.warnings.length})
              </span>
              <div className="space-y-1.5">
                {plan.warnings.map((w, idx) => (
                  <div
                    key={idx}
                    className={`p-3 rounded-md border flex items-start gap-2.5 text-xs ${
                      w.severity === "critical"
                        ? "bg-rose-50 border-rose-200 text-rose-800"
                        : w.severity === "warning"
                        ? "bg-amber-50 border-amber-200 text-amber-800"
                        : "bg-slate-50 border-slate-200 text-slate-800"
                    }`}
                  >
                    {w.severity === "critical" ? (
                      <XCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                    ) : w.severity === "warning" ? (
                      <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                    ) : (
                      <Info className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                    )}
                    <div>
                      <span className="font-mono text-slate-900 font-semibold block">{w.code}</span>
                      <span className="text-slate-600 text-[11px] font-sans">{w.message}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 5. Proposed Consolidated Record */}
          {plan.proposed_record && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase text-emerald-800 font-mono font-semibold">
                  Proposed Consolidated Record (TXT @)
                </span>
                <button
                  type="button"
                  onClick={() => handleCopy(plan.proposed_record!)}
                  className="relative text-xs flex items-center gap-1.5 text-emerald-700 hover:text-emerald-800 font-semibold transition cursor-pointer p-1.5 rounded-md focus:outline-none"
                >
                  {copied ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-600" /> Copied Record
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5" /> 1-Click Copy
                    </>
                  )}
                </button>
              </div>

              <div className="p-4 rounded-lg bg-slate-50 border border-slate-300 font-mono text-xs text-slate-900 overflow-x-auto select-all selection:bg-emerald-100 selection:text-emerald-900 shadow-2xs">
                {plan.proposed_record}
              </div>
            </div>
          )}

          {/* 6. Action Footer */}
          <div className="space-y-3 pt-2">
            {applyError && (
              <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-800 font-mono flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fadeIn">
                <div className="flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-rose-800 block">{applyError}</span>
                    {isTierLocked && (
                      <span className="text-[11px] text-slate-600 block mt-0.5 font-sans">
                        Upgrade your plan to unlock automated 1-click zone remediation without manual DNS editing.
                      </span>
                    )}
                  </div>
                </div>
                {isTierLocked && (
                  <Link
                    href="/dashboard/billing"
                    className="shrink-0 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-md text-xs flex items-center gap-1 transition shadow-xs"
                  >
                    Upgrade Plan <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                )}
              </div>
            )}

            <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
              <span className="text-[11px] text-slate-500 font-mono">
                Plan ID: {plan.plan_id.slice(0, 8)}... • Valid for 24h
              </span>

              {applySuccess ? (
                <div className="flex items-center gap-2 px-3.5 py-2 bg-emerald-50 border border-emerald-200 rounded-md text-xs text-emerald-800 font-mono font-bold animate-fadeIn">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  <span>✓ Injected to Zone</span>
                </div>
              ) : (
                <EmeraldHoverButton
                  size="sm"
                  variant={plan.safe_to_apply && !plan.requires_manual_review ? "primary" : "secondary"}
                  disabled={!plan.safe_to_apply || plan.requires_manual_review || isApplying}
                  onClick={handleApply}
                  isLoading={isApplying}
                  icon={<Zap className="w-3.5 h-3.5" />}
                >
                  {plan.safe_to_apply && !plan.requires_manual_review
                    ? "Fix Domain Configuration"
                    : "Review DNS Records (Manual Action Required)"}
                </EmeraldHoverButton>
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
};

export default SpfMergePreview;
