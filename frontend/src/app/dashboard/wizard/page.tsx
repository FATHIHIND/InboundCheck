"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Sparkles,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Copy,
  Check,
  RefreshCw,
  ArrowRight,
  ArrowLeft,
  Server,
  Globe,
  Lock,
  FileCode,
  Layers,
  ChevronRight,
  Zap,
  Sliders,
  ExternalLink
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

export interface ReadinessCheckItem {
  check_id: string;
  title: string;
  status: "pass" | "warning" | "fail";
  impact: "critical" | "high" | "medium";
  finding: string;
  remediation: string;
  dns_record_snippet?: string | null;
}

export interface ShopifyReadinessData {
  domain: string;
  readiness_score: number;
  status: "ready" | "needs_attention" | "critical";
  passed_checks: number;
  total_checks: number;
  checks: ReadinessCheckItem[];
  evaluated_at: string;
  can_activate_zero_spam: boolean;
  summary: string;
}

const CHECK_ICONS: Record<string, React.ReactNode> = {
  custom_sending_domain: <Globe className="w-5 h-5" />,
  shopify_dkim: <Lock className="w-5 h-5" />,
  spf_alignment: <Server className="w-5 h-5" />,
  dmarc_policy: <ShieldCheck className="w-5 h-5" />,
  spf_conflict: <Layers className="w-5 h-5" />,
  shared_pool_exposure: <FileCode className="w-5 h-5" />,
};

function SetupWizardContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const queryDomain = searchParams?.get("domain") || "";
  const [domainInput, setDomainInput] = useState<string>(queryDomain);
  const [activeStep, setActiveStep] = useState<number>(0); // 0 = Overview, 1..6 = Specific check, 7 = Activation
  const [data, setData] = useState<ShopifyReadinessData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);
  const [isActivating, setIsActivating] = useState<boolean>(false);
  const [activationSuccess, setActivationSuccess] = useState<boolean>(false);

  // Auto-Fix state
  const [isApplyingFix, setIsApplyingFix] = useState<boolean>(false);
  const [fixSuccessMessage, setFixSuccessMessage] = useState<string | null>(null);
  const [fixErrorMessage, setFixErrorMessage] = useState<string | null>(null);

  const runEvaluation = useCallback(
    async (overrideDomain?: string) => {
      setIsLoading(true);
      setError(null);
      setFixSuccessMessage(null);
      setFixErrorMessage(null);

      try {
        const targetDomain = overrideDomain !== undefined ? overrideDomain : domainInput;
        const res = await apiFetch("/api/v1/shopify/deliverability-readiness", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            domain: targetDomain.trim() || undefined,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Readiness check failed (HTTP ${res.status})`);
        }

        const json: ShopifyReadinessData = await res.json();
        setData(json);
        if (!domainInput && json.domain) {
          setDomainInput(json.domain);
        }
      } catch (err: unknown) {
        console.error("Readiness evaluation error:", err);
        const msg = err instanceof Error ? err.message : "Failed to evaluate deliverability readiness";
        setError(msg);
      } finally {
        setIsLoading(false);
      }
    },
    [domainInput]
  );

  // Initial load
  useEffect(() => {
    runEvaluation(queryDomain || undefined);
  }, [queryDomain, runEvaluation]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(text);
    setTimeout(() => setCopiedSnippet(null), 2500);
  };

  const handleActivateZeroSpam = async () => {
    setIsActivating(true);
    try {
      await runEvaluation();
      setActivationSuccess(true);
    } catch (e) {
      console.error("Activation failed:", e);
    } finally {
      setIsActivating(false);
    }
  };

  const handleApply1ClickFix = async (check: ReadinessCheckItem) => {
    if (!check.dns_record_snippet || !data?.domain) return;
    setIsApplyingFix(true);
    setFixSuccessMessage(null);
    setFixErrorMessage(null);

    try {
      // Determine host and record type
      let host = data.domain;
      let recordType = "TXT";
      let recordValue = check.dns_record_snippet.trim();

      if (check.check_id === "dmarc_policy") {
        host = `_dmarc.${data.domain}`;
        recordType = "TXT";
      } else if (check.check_id === "shopify_dkim") {
        // e.g. CNAME selector
        host = check.dns_record_snippet.includes("dkim") ? check.dns_record_snippet.split(" ")[0] : data.domain;
        recordType = "CNAME";
      }

      const res = await apiFetch("/api/v1/dns/auto-fix/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain_name: data.domain,
          provider_name: "cloudflare",
          record_type: recordType,
          host: host,
          record_value: recordValue,
          ttl: 3600,
        }),
      });

      const resData = await res.json().catch(() => ({}));
      if (res.ok && resData.success) {
        setFixSuccessMessage(resData.message || "DNS record successfully injected via API.");
        setTimeout(() => runEvaluation(), 1500);
      } else {
        setFixErrorMessage(
          resData.detail ||
          resData.error ||
          "Auto-fix failed. Please verify API token in Settings or insert snippet manually."
        );
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error applying 1-click fix";
      setFixErrorMessage(msg);
    } finally {
      setIsApplyingFix(false);
    }
  };

  const currentCheck = data && activeStep >= 1 && activeStep <= 6 ? data.checks[activeStep - 1] : null;

  return (
    <div className="space-y-6 max-w-[1360px] mx-auto animate-fadeIn pb-16">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <Sparkles className="w-5 h-5 text-emerald-400" strokeWidth={2} />
            Shopify Deliverability Setup Wizard
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            Step-by-step interactive diagnostic pipeline to guarantee 100% Google &amp; Yahoo bulk sender compliance for Shopify stores.
          </p>
        </div>

        {/* Global Action Header */}
        <div className="flex items-center gap-2">
          {data && (
            <button
              type="button"
              onClick={() => runEvaluation()}
              disabled={isLoading}
              className="h-10 px-4 rounded-lg bg-zinc-900/60 hover:bg-zinc-800 border border-zinc-700/60 hover:border-emerald-500/40 text-zinc-300 hover:text-white transition-all text-xs font-mono flex items-center gap-2 cursor-pointer disabled:opacity-50"
              title="Re-run Diagnostic Scan"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin text-emerald-400" : "text-emerald-400"}`} />
              <span>Re-Run Pipeline</span>
            </button>
          )}

          <Link
            href="/dashboard/shopify"
            className="h-10 px-4 rounded-lg border border-white/[0.08] hover:border-white/20 bg-white/[0.03] hover:bg-white/[0.06] text-zinc-300 hover:text-white transition-colors text-xs font-semibold flex items-center gap-2"
          >
            <span>Store Fleet</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>

      {/* Main Glassmorphic Workspace Framing */}
      <div className="max-w-6xl mx-auto rounded-xl border border-white/[0.08] bg-[#0A0A0C] p-6 lg:p-8 space-y-6 shadow-2xl">
        {/* Step Navigation Ribbon */}
        {data && (
          <div className="p-2 border border-white/[0.06] bg-[#0E0E14]/70 rounded-xl flex items-center gap-1.5 sm:gap-2 overflow-x-auto scrollbar-none font-mono">
            <button
              type="button"
              onClick={() => setActiveStep(0)}
              className={`px-3 py-1.5 text-xs rounded-lg transition shrink-0 flex items-center gap-1.5 cursor-pointer border ${
                activeStep === 0
                  ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40 font-semibold"
                  : "text-zinc-400 hover:text-white hover:bg-white/5 border-transparent font-medium"
              }`}
            >
              Overview ({data.passed_checks}/{data.total_checks})
            </button>
            <ChevronRight className="w-3.5 h-3.5 text-zinc-600 shrink-0" />

            {data.checks.map((check, idx) => {
              const stepIndex = idx + 1;
              const isSelected = activeStep === stepIndex;
              return (
                <button
                  key={check.check_id}
                  type="button"
                  onClick={() => setActiveStep(stepIndex)}
                  className={`px-2.5 py-1.5 text-xs rounded-lg transition shrink-0 flex items-center gap-1.5 cursor-pointer border ${
                    isSelected
                      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40 font-semibold"
                      : "text-zinc-400 hover:text-white hover:bg-white/5 border-transparent font-medium"
                  }`}
                >
                  {check.status === "pass" ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  ) : check.status === "warning" ? (
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                  )}
                  <span>Step {stepIndex}</span>
                </button>
              );
            })}

            <ChevronRight className="w-3.5 h-3.5 text-zinc-600 shrink-0" />
            <button
              type="button"
              onClick={() => setActiveStep(7)}
              className={`px-3 py-1.5 text-xs rounded-lg transition shrink-0 flex items-center gap-1.5 cursor-pointer border ${
                activeStep === 7
                  ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40 font-semibold"
                  : "text-zinc-400 hover:text-white hover:bg-white/5 border-transparent font-medium"
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>Activation</span>
            </button>
          </div>
        )}

        {/* Loading State */}
        {isLoading && !data && (
          <div className="py-24 flex flex-col items-center justify-center space-y-4">
            <RefreshCw className="w-10 h-10 text-emerald-400 animate-spin" />
            <p className="text-xs text-zinc-400 font-mono">
              Auditing DNS resolvers &amp; Shopify sender alignment...
            </p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="p-6 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 space-y-3 font-mono text-xs animate-fadeIn">
            <div className="flex items-center gap-2 font-semibold text-sm">
              <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
              <span>Diagnostic Pipeline Error</span>
            </div>
            <p className="text-zinc-300">{error}</p>
            <div className="pt-2">
              <EmeraldHoverButton
                size="sm"
                variant="secondary"
                onClick={() => runEvaluation()}
              >
                Retry Pipeline
              </EmeraldHoverButton>
            </div>
          </div>
        )}

        {/* Content Body */}
        {data && !isLoading && (
          <>
            {/* ================= STEP 0: OVERVIEW DASHBOARD ================= */}
            {activeStep === 0 && (
              <div className="space-y-6 animate-fadeIn">
                {/* Domain Input Field to allow merchant to audit any domain */}
                <div className="flex flex-col sm:flex-row gap-3 items-center">
                  <div className="relative w-full sm:flex-1">
                    <Globe className="w-4 h-4 text-zinc-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                    <input
                      type="text"
                      placeholder="e.g. brandstore.com"
                      value={domainInput}
                      onChange={(e) => setDomainInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") runEvaluation(domainInput);
                      }}
                      className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-[#08080A] border border-zinc-800 text-xs font-mono text-zinc-100 placeholder:text-zinc-500 font-medium focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                  <EmeraldHoverButton
                    size="sm"
                    variant="primary"
                    onClick={() => runEvaluation(domainInput)}
                    isLoading={isLoading}
                    className="h-10 px-5 text-xs font-semibold rounded-lg shrink-0"
                  >
                    Audit Domain
                  </EmeraldHoverButton>
                </div>

                {/* Score & Summary Banner */}
                <div className="p-5 rounded-xl border border-white/[0.08] bg-gradient-to-br from-white/[0.03] to-transparent flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] uppercase tracking-wider text-zinc-400 font-mono font-semibold">
                        Domain Target:
                      </span>
                      <span className="text-sm font-mono text-emerald-400 font-bold">{data.domain}</span>
                    </div>
                    <p className="text-xs text-zinc-300 leading-relaxed max-w-2xl">{data.summary}</p>
                  </div>

                  <div className="flex items-center gap-4 shrink-0 font-mono">
                    <div className="text-center px-4 py-2.5 rounded-xl bg-[#08080A] border border-white/[0.08]">
                      <span className="block text-2xl font-bold font-mono text-white">
                        {data.passed_checks}/{data.total_checks}
                      </span>
                      <span className="text-[10px] uppercase text-zinc-400">Checks Passed</span>
                    </div>

                    <div className="text-center px-4 py-2.5 rounded-xl bg-[#08080A] border border-white/[0.08]">
                      <span
                        className={`block text-2xl font-bold font-mono ${
                          data.readiness_score >= 85
                            ? "text-emerald-400"
                            : data.readiness_score >= 60
                            ? "text-amber-400"
                            : "text-rose-400"
                        }`}
                      >
                        {data.readiness_score}%
                      </span>
                      <span className="text-[10px] uppercase text-zinc-400">Health Index</span>
                    </div>
                  </div>
                </div>

                {/* 6 Core Checks Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {data.checks.map((check, idx) => (
                    <div
                      key={check.check_id}
                      onClick={() => setActiveStep(idx + 1)}
                      className="p-4 rounded-xl border border-white/[0.08] bg-[#0A0A0C] hover:border-emerald-500/40 hover:bg-white/[0.02] cursor-pointer transition flex items-start gap-3.5 group"
                    >
                      <div
                        className={`p-2.5 rounded-lg shrink-0 ${
                          check.status === "pass"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : check.status === "warning"
                            ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                            : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                        }`}
                      >
                        {CHECK_ICONS[check.check_id] || <ShieldCheck className="w-5 h-5" />}
                      </div>

                      <div className="space-y-1 flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <h4 className="text-xs font-semibold text-white truncate group-hover:text-emerald-400 transition">
                            {check.title}
                          </h4>
                          <span
                            className={`text-[10px] uppercase px-2 py-0.5 rounded font-mono font-bold ${
                              check.status === "pass"
                                ? "bg-emerald-500/10 text-emerald-400"
                                : check.status === "warning"
                                ? "bg-amber-500/10 text-amber-400"
                                : "bg-rose-500/10 text-rose-400"
                            }`}
                          >
                            {check.status}
                          </span>
                        </div>
                        <p className="text-xs text-zinc-400 line-clamp-2 leading-relaxed">{check.finding}</p>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex justify-end pt-2">
                  <EmeraldHoverButton
                    variant="primary"
                    size="md"
                    onClick={() => setActiveStep(1)}
                    icon={<ArrowRight className="w-4 h-4" />}
                    iconPosition="right"
                    className="h-10 px-5 text-xs font-semibold rounded-lg shadow-sm"
                  >
                    Start Step-by-Step Fixes
                  </EmeraldHoverButton>
                </div>
              </div>
            )}

            {/* ================= STEPS 1..6: INDIVIDUAL CHECK FOCUS ================= */}
            {currentCheck && activeStep >= 1 && activeStep <= 6 && (
              <div className="space-y-6 animate-fadeIn">
                <div className="flex items-start justify-between gap-4 p-4 rounded-xl border border-white/[0.08] bg-white/[0.02]">
                  <div className="flex items-center gap-3">
                    <div
                      className={`p-2.5 rounded-xl shrink-0 ${
                        currentCheck.status === "pass"
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                          : currentCheck.status === "warning"
                          ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                          : "bg-rose-500/10 text-rose-400 border border-rose-500/30"
                      }`}
                    >
                      {CHECK_ICONS[currentCheck.check_id] || <ShieldCheck className="w-6 h-6" />}
                    </div>
                    <div>
                      <span className="text-[11px] text-zinc-500 font-mono uppercase">
                        Check {activeStep} of 6 • Impact: {currentCheck.impact}
                      </span>
                      <h3 className="text-base sm:text-lg font-bold text-white">{currentCheck.title}</h3>
                    </div>
                  </div>

                  <span
                    className={`text-xs uppercase font-mono px-3 py-1 rounded-full border font-semibold ${
                      currentCheck.status === "pass"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                        : currentCheck.status === "warning"
                        ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                        : "bg-rose-500/10 text-rose-400 border-rose-500/30"
                    }`}
                  >
                    {currentCheck.status}
                  </span>
                </div>

                {/* Diagnostic Finding */}
                <div className="space-y-2">
                  <label className="text-[11px] uppercase tracking-wider text-zinc-400 font-semibold font-mono">
                    Diagnostic Finding:
                  </label>
                  <div className="p-4 rounded-xl bg-[#08080A] border border-white/[0.06] text-xs text-zinc-300 leading-relaxed font-mono">
                    {currentCheck.finding}
                  </div>
                </div>

                {/* Remediation Instructions */}
                <div className="space-y-2">
                  <label className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold font-mono">
                    Action Required:
                  </label>
                  <div className="p-4 rounded-xl bg-emerald-500/[0.04] border border-emerald-500/20 text-xs text-zinc-200 leading-relaxed">
                    {currentCheck.remediation}
                  </div>
                </div>

                {/* DNS Snippet Copy Box & 1-Click Fix */}
                {currentCheck.dns_record_snippet && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-[11px] uppercase tracking-wider text-zinc-400 font-semibold font-mono">
                        Recommended DNS Record:
                      </label>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleCopy(currentCheck.dns_record_snippet!)}
                          className="text-xs flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 transition font-mono cursor-pointer"
                        >
                          {copiedSnippet === currentCheck.dns_record_snippet ? (
                            <>
                              <Check className="w-3.5 h-3.5" /> Copied!
                            </>
                          ) : (
                            <>
                              <Copy className="w-3.5 h-3.5" /> 1-Click Copy
                            </>
                          )}
                        </button>
                      </div>
                    </div>

                    <div className="p-4 rounded-xl bg-[#08080A] border border-white/[0.08] font-mono text-xs text-emerald-300 overflow-x-auto relative">
                      <pre className="whitespace-pre-wrap select-all">{currentCheck.dns_record_snippet}</pre>
                    </div>

                    {/* 1-Click Fix Trigger Option */}
                    <div className="p-3.5 bg-[#08080A] border border-zinc-800 rounded-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                      <span className="text-[11px] text-zinc-400 font-sans">
                        Have Cloudflare credentials saved? Apply this fix directly without leaving this screen.
                      </span>
                      <button
                        type="button"
                        onClick={() => handleApply1ClickFix(currentCheck)}
                        disabled={isApplyingFix}
                        className="px-3.5 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 rounded-lg text-xs font-mono font-semibold flex items-center gap-1.5 transition cursor-pointer disabled:opacity-50 shrink-0"
                      >
                        <Zap className={`w-3.5 h-3.5 ${isApplyingFix ? "animate-spin" : "fill-current"}`} />
                        {isApplyingFix ? "Applying via API..." : "1-Click Auto-Fix"}
                      </button>
                    </div>

                    {fixSuccessMessage && (
                      <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-xs text-emerald-300 font-mono flex items-center gap-2 animate-fadeIn">
                        <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                        <span>{fixSuccessMessage}</span>
                      </div>
                    )}

                    {fixErrorMessage && (
                      <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-xs text-rose-300 font-mono flex items-center gap-2 animate-fadeIn">
                        <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                        <span>{fixErrorMessage}</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Step Navigation Buttons */}
                <div className="flex items-center justify-between pt-4 border-t border-white/[0.08]">
                  <EmeraldHoverButton
                    variant="secondary"
                    size="sm"
                    onClick={() => setActiveStep((prev) => Math.max(0, prev - 1))}
                    icon={<ArrowLeft className="w-4 h-4" />}
                    className="h-10 px-5 text-xs font-semibold rounded-lg"
                  >
                    {activeStep === 1 ? "Overview" : `Step ${activeStep - 1}`}
                  </EmeraldHoverButton>

                  <div className="flex items-center gap-2">
                    <EmeraldHoverButton
                      variant="secondary"
                      size="sm"
                      onClick={() => runEvaluation()}
                      isLoading={isLoading}
                      icon={<RefreshCw className="w-3.5 h-3.5" />}
                      className="h-10 px-5 text-xs font-semibold rounded-lg"
                    >
                      Re-Verify Check
                    </EmeraldHoverButton>

                    <EmeraldHoverButton
                      variant="primary"
                      size="sm"
                      onClick={() => setActiveStep((prev) => Math.min(7, prev + 1))}
                      icon={<ArrowRight className="w-4 h-4" />}
                      iconPosition="right"
                      className="h-10 px-5 text-xs font-semibold rounded-lg shadow-sm"
                    >
                      {activeStep === 6 ? "Final Activation" : `Step ${activeStep + 1}`}
                    </EmeraldHoverButton>
                  </div>
                </div>
              </div>
            )}

            {/* ================= STEP 7: FINAL ACTIVATION & VERIFICATION ================= */}
            {activeStep === 7 && (
              <div className="space-y-6 text-center py-6 animate-fadeIn">
                <div className="w-16 h-16 mx-auto rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-[0_0_30px_rgba(16,185,129,0.2)]">
                  <ShieldCheck className="w-8 h-8" />
                </div>

                <div className="max-w-md mx-auto space-y-2">
                  <h3 className="text-xl font-bold text-white">
                    {data.can_activate_zero_spam
                      ? "Store Ready for Zero-Spam Protection"
                      : "Remediation Incomplete"}
                  </h3>
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    {data.can_activate_zero_spam
                      ? "All critical sender identity, DKIM CNAMEs, and DMARC enforcement criteria have passed."
                      : `Your domain currently has a readiness score of ${data.readiness_score}/100. Resolve remaining critical/warning checks before full activation.`}
                  </p>
                </div>

                {activationSuccess ? (
                  <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 max-w-md mx-auto text-xs flex items-center gap-2 justify-center font-mono">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>Zero-Spam delivery mode active! Automated fallback monitoring enabled.</span>
                  </div>
                ) : (
                  <div className="flex justify-center gap-3">
                    <EmeraldHoverButton
                      variant="secondary"
                      size="md"
                      onClick={() => setActiveStep(0)}
                      className="h-10 px-5 text-xs font-semibold rounded-lg"
                    >
                      Review Checks
                    </EmeraldHoverButton>

                    <EmeraldHoverButton
                      variant="primary"
                      size="md"
                      onClick={handleActivateZeroSpam}
                      isLoading={isActivating}
                      disabled={!data.can_activate_zero_spam}
                      icon={<Sparkles className="w-4 h-4" />}
                      className="h-10 px-5 text-xs font-semibold rounded-lg shadow-sm"
                    >
                      Activate Zero-Spam Mode
                    </EmeraldHoverButton>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function SetupWizardPage() {
  return (
    <Suspense
      fallback={
        <div className="p-12 text-center text-xs font-mono text-zinc-500">
          Loading deliverability setup wizard...
        </div>
      }
    >
      <SetupWizardContent />
    </Suspense>
  );
}
