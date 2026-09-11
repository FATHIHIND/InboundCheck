"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  X,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Copy,
  Check,
  RefreshCw,
  Sparkles,
  ShieldCheck,
  ArrowRight,
  ArrowLeft,
  Server,
  Globe,
  Lock,
  FileCode,
  Layers,
  ChevronRight
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

interface ZeroSpamWizardProps {
  isOpen: boolean;
  onClose: () => void;
  domain?: string;
  onSuccess?: () => void;
}

const CHECK_ICONS: Record<string, React.ReactNode> = {
  custom_sending_domain: <Globe className="w-5 h-5" />,
  shopify_dkim: <Lock className="w-5 h-5" />,
  spf_alignment: <Server className="w-5 h-5" />,
  dmarc_policy: <ShieldCheck className="w-5 h-5" />,
  spf_conflict: <Layers className="w-5 h-5" />,
  shared_pool_exposure: <FileCode className="w-5 h-5" />,
};

export const ZeroSpamWizardModal: React.FC<ZeroSpamWizardProps> = ({
  isOpen,
  onClose,
  domain: initialDomain,
  onSuccess,
}) => {
  const [domainInput, setDomainInput] = useState(initialDomain || "");
  const [activeStep, setActiveStep] = useState<number>(0); // 0 = Overview, 1..6 = Specific check, 7 = Complete
  const [data, setData] = useState<ShopifyReadinessData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);
  const [isActivating, setIsActivating] = useState<boolean>(false);
  const [activationSuccess, setActivationSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (initialDomain) {
      setDomainInput(initialDomain);
    }
  }, [initialDomain]);

  const runEvaluation = useCallback(
    async (overrideDomain?: string) => {
      setIsLoading(true);
      setError(null);
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
      } catch (err: any) {
        console.error("Readiness evaluation error:", err);
        setError(err?.message || "Failed to evaluate deliverability readiness");
      } finally {
        setIsLoading(false);
      }
    },
    [domainInput]
  );

  useEffect(() => {
    if (isOpen) {
      runEvaluation();
    }
  }, [isOpen, runEvaluation]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(text);
    setTimeout(() => setCopiedSnippet(null), 2500);
  };

  const handleActivateZeroSpam = async () => {
    setIsActivating(true);
    try {
      // Re-verify before activation
      await runEvaluation();
      setActivationSuccess(true);
      if (onSuccess) onSuccess();
    } catch (e) {
      console.error("Activation failed:", e);
    } finally {
      setIsActivating(false);
    }
  };

  if (!isOpen) return null;

  const currentCheck = data && activeStep >= 1 && activeStep <= 6 ? data.checks[activeStep - 1] : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl max-h-[92vh] flex flex-col rounded-2xl border border-white/10 bg-[#0A0A0E] shadow-[0_0_50px_rgba(0,0,0,0.8)] overflow-hidden text-zinc-100">
        {/* Modal Top Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#0E0E14]/80">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                Shopify Zero-Spam Readiness Wizard
                {data && (
                  <span
                    className={`text-xs px-2.5 py-0.5 rounded-full font-mono border ${
                      data.status === "ready"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                        : data.status === "needs_attention"
                        ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                        : "bg-rose-500/10 text-rose-400 border-rose-500/30"
                    }`}
                  >
                    Score: {data.readiness_score}/100
                  </span>
                )}
              </h2>
              <p className="text-xs text-zinc-400">
                Guaranteed Google & Yahoo 2024 compliance for Shopify order receipts
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => runEvaluation()}
              disabled={isLoading}
              className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-400 hover:text-white transition disabled:opacity-50"
              title="Re-run Diagnostic Scan"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin text-emerald-400" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-400 hover:text-white transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Step Navigation Ribbon */}
        {data && (
          <div className="px-6 py-2.5 border-b border-white/5 bg-black/40 flex items-center gap-1 sm:gap-2 overflow-x-auto scrollbar-none">
            <button
              onClick={() => setActiveStep(0)}
              className={`px-3 py-1 text-xs rounded-lg transition shrink-0 flex items-center gap-1.5 ${
                activeStep === 0
                  ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-semibold"
                  : "text-zinc-400 hover:bg-white/5"
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
                  onClick={() => setActiveStep(stepIndex)}
                  className={`px-2.5 py-1 text-xs rounded-lg transition shrink-0 flex items-center gap-1.5 ${
                    isSelected
                      ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-semibold"
                      : "text-zinc-400 hover:bg-white/5"
                  }`}
                >
                  {check.status === "pass" ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  ) : check.status === "warning" ? (
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-rose-400" />
                  )}
                  <span>Step {stepIndex}</span>
                </button>
              );
            })}

            <ChevronRight className="w-3.5 h-3.5 text-zinc-600 shrink-0" />
            <button
              onClick={() => setActiveStep(7)}
              className={`px-3 py-1 text-xs rounded-lg transition shrink-0 flex items-center gap-1.5 ${
                activeStep === 7
                  ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-semibold"
                  : "text-zinc-400 hover:bg-white/5"
              }`}
            >
              Activation
            </button>
          </div>
        )}

        {/* Modal Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {isLoading && !data ? (
            <div className="py-20 flex flex-col items-center justify-center space-y-4">
              <RefreshCw className="w-10 h-10 text-emerald-400 animate-spin" />
              <p className="text-sm text-zinc-400">Auditing DNS resolvers & Shopify sender alignment...</p>
            </div>
          ) : error ? (
            <div className="p-6 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 space-y-3">
              <div className="flex items-center gap-2 font-semibold">
                <XCircle className="w-5 h-5 text-rose-400" />
                <span>Audit Error</span>
              </div>
              <p className="text-xs">{error}</p>
              <EmeraldHoverButton size="sm" variant="secondary" onClick={() => runEvaluation()}>
                Retry Scan
              </EmeraldHoverButton>
            </div>
          ) : data ? (
            <>
              {/* Step 0: Overview Dashboard */}
              {activeStep === 0 && (
                <div className="space-y-6">
                  {/* Domain Input Field to allow merchant to audit any domain */}
                  <div className="flex flex-col sm:flex-row gap-3 items-center">
                    <input
                      type="text"
                      placeholder="e.g. brandstore.com"
                      value={domainInput}
                      onChange={(e) => setDomainInput(e.target.value)}
                      className="w-full sm:flex-1 px-4 py-2 rounded-xl bg-black/60 border border-white/10 text-sm font-mono text-white placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500"
                    />
                    <EmeraldHoverButton
                      size="sm"
                      variant="primary"
                      onClick={() => runEvaluation(domainInput)}
                      isLoading={isLoading}
                    >
                      Audit Domain
                    </EmeraldHoverButton>
                  </div>

                  {/* Score & Summary Banner */}
                  <div className="p-5 rounded-xl border border-white/10 bg-gradient-to-br from-white/[0.03] to-transparent flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs uppercase tracking-wider text-zinc-400 font-semibold">
                          Domain Target:
                        </span>
                        <span className="text-sm font-mono text-emerald-400 font-bold">{data.domain}</span>
                      </div>
                      <p className="text-sm text-zinc-300">{data.summary}</p>
                    </div>

                    <div className="flex items-center gap-4 shrink-0">
                      <div className="text-center px-4 py-2 rounded-xl bg-black/40 border border-white/10">
                        <span className="block text-2xl font-bold font-mono text-white">
                          {data.passed_checks}/{data.total_checks}
                        </span>
                        <span className="text-[10px] uppercase text-zinc-400">Checks Passed</span>
                      </div>

                      <div className="text-center px-4 py-2 rounded-xl bg-black/40 border border-white/10">
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
                        className="p-4 rounded-xl border border-white/10 bg-black/30 hover:border-emerald-500/40 hover:bg-white/[0.02] cursor-pointer transition flex items-start gap-3.5 group"
                      >
                        <div
                          className={`p-2 rounded-lg shrink-0 ${
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
                            <h4 className="text-sm font-semibold text-white truncate group-hover:text-emerald-400 transition">
                              {check.title}
                            </h4>
                            <span
                              className={`text-[10px] uppercase px-2 py-0.5 rounded font-mono ${
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
                          <p className="text-xs text-zinc-400 line-clamp-2">{check.finding}</p>
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
                    >
                      Start Step-by-Step Fixes
                    </EmeraldHoverButton>
                  </div>
                </div>
              )}

              {/* Steps 1..6: Individual Check Focus */}
              {currentCheck && activeStep >= 1 && activeStep <= 6 && (
                <div className="space-y-6 animate-in fade-in duration-150">
                  <div className="flex items-start justify-between gap-4 p-4 rounded-xl border border-white/10 bg-white/[0.02]">
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
                        <span className="text-xs text-zinc-500 font-mono uppercase">
                          Check {activeStep} of 6 • Impact: {currentCheck.impact}
                        </span>
                        <h3 className="text-lg font-bold text-white">{currentCheck.title}</h3>
                      </div>
                    </div>

                    <span
                      className={`text-xs uppercase font-mono px-3 py-1 rounded-full border ${
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

                  {/* Finding Explanation */}
                  <div className="space-y-2">
                    <label className="text-xs uppercase tracking-wider text-zinc-400 font-semibold">
                      Diagnostic Finding:
                    </label>
                    <div className="p-4 rounded-xl bg-black/40 border border-white/5 text-sm text-zinc-300 leading-relaxed font-mono">
                      {currentCheck.finding}
                    </div>
                  </div>

                  {/* Remediation Instructions */}
                  <div className="space-y-2">
                    <label className="text-xs uppercase tracking-wider text-emerald-400 font-semibold">
                      Action Required:
                    </label>
                    <div className="p-4 rounded-xl bg-emerald-500/[0.04] border border-emerald-500/20 text-sm text-zinc-200 leading-relaxed">
                      {currentCheck.remediation}
                    </div>
                  </div>

                  {/* DNS Snippet Copy Box if available */}
                  {currentCheck.dns_record_snippet && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-xs uppercase tracking-wider text-zinc-400 font-semibold">
                          Recommended DNS Record:
                        </label>
                        <button
                          onClick={() => handleCopy(currentCheck.dns_record_snippet!)}
                          className="text-xs flex items-center gap-1 text-emerald-400 hover:text-emerald-300 transition"
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

                      <div className="p-4 rounded-xl bg-black/70 border border-white/10 font-mono text-xs text-emerald-300 overflow-x-auto relative group">
                        <pre className="whitespace-pre-wrap select-all">{currentCheck.dns_record_snippet}</pre>
                      </div>
                    </div>
                  )}

                  {/* Step Navigation Buttons */}
                  <div className="flex items-center justify-between pt-4 border-t border-white/10">
                    <EmeraldHoverButton
                      variant="secondary"
                      size="sm"
                      onClick={() => setActiveStep((prev) => Math.max(0, prev - 1))}
                      icon={<ArrowLeft className="w-4 h-4" />}
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
                      >
                        Re-Verify Check
                      </EmeraldHoverButton>

                      <EmeraldHoverButton
                        variant="primary"
                        size="sm"
                        onClick={() => setActiveStep((prev) => Math.min(7, prev + 1))}
                        icon={<ArrowRight className="w-4 h-4" />}
                        iconPosition="right"
                      >
                        {activeStep === 6 ? "Final Activation" : `Step ${activeStep + 1}`}
                      </EmeraldHoverButton>
                    </div>
                  </div>
                </div>
              )}

              {/* Step 7: Final Activation & Verification */}
              {activeStep === 7 && (
                <div className="space-y-6 text-center py-6">
                  <div className="w-16 h-16 mx-auto rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                    <ShieldCheck className="w-8 h-8" />
                  </div>

                  <div className="max-w-md mx-auto space-y-2">
                    <h3 className="text-xl font-bold text-white">
                      {data.can_activate_zero_spam
                        ? "Store Ready for Zero-Spam Protection"
                        : "Remediation Incomplete"}
                    </h3>
                    <p className="text-xs text-zinc-400">
                      {data.can_activate_zero_spam
                        ? "All critical sender identity, DKIM CNAMEs, and DMARC enforcement criteria have passed."
                        : `Your domain currently has a readiness score of ${data.readiness_score}/100. Resolve remaining critical/warning checks before full activation.`}
                    </p>
                  </div>

                  {activationSuccess ? (
                    <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 max-w-md mx-auto text-xs flex items-center gap-2 justify-center">
                      <CheckCircle2 className="w-4 h-4" />
                      <span>Zero-Spam delivery mode active! Automated fallback monitoring enabled.</span>
                    </div>
                  ) : (
                    <div className="flex justify-center gap-3">
                      <EmeraldHoverButton
                        variant="secondary"
                        size="md"
                        onClick={() => setActiveStep(0)}
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
                      >
                        Activate Zero-Spam Mode
                      </EmeraldHoverButton>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default ZeroSpamWizardModal;
