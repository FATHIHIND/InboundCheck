"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle2,
  Copy,
  Check,
  ChevronDown,
  Zap,
  RefreshCw,
  Terminal,
  ArrowRight,
  ExternalLink,
} from "lucide-react";
import {
  RawDiagnosticIssue,
  TranslationContext,
  translateDiagnosticIssue,
} from "@/lib/diagnostic-translator";

interface PlainEnglishDiagnosticCardProps {
  issue: RawDiagnosticIssue;
  context?: TranslationContext;
  onApplyAutoFix?: (record: {
    record_type: string;
    host: string;
    value: string;
    ttl?: string | number;
  }) => Promise<void> | void;
  isApplyingAutoFix?: boolean;
  autoFixSuccess?: boolean;
  autoFixError?: string | null;
}

export function PlainEnglishDiagnosticCard({
  issue,
  context = {},
  onApplyAutoFix,
  isApplyingAutoFix = false,
  autoFixSuccess = false,
  autoFixError = null,
}: PlainEnglishDiagnosticCardProps) {
  const [isCopied, setIsCopied] = useState(false);
  const [isTechDetailsOpen, setIsTechDetailsOpen] = useState(false);

  const diag = translateDiagnosticIssue(issue, context);

  const handleCopy = (value: string) => {
    navigator.clipboard.writeText(value);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  const severityBg =
    diag.severity === "critical"
      ? "bg-rose-50/50 border-rose-200"
      : diag.severity === "warning"
      ? "bg-amber-50/50 border-amber-200"
      : diag.severity === "optimal"
      ? "bg-emerald-50/50 border-emerald-200"
      : "bg-blue-50/50 border-blue-200";

  const severityBadgeClass =
    diag.severity === "critical"
      ? "bg-rose-100 text-rose-800 border-rose-300"
      : diag.severity === "warning"
      ? "bg-amber-100 text-amber-800 border-amber-300"
      : diag.severity === "optimal"
      ? "bg-emerald-100 text-emerald-800 border-emerald-300"
      : "bg-blue-100 text-blue-800 border-blue-300";

  const severityIcon =
    diag.severity === "critical" ? (
      <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
    ) : diag.severity === "warning" ? (
      <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
    ) : diag.severity === "optimal" ? (
      <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
    ) : (
      <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
    );

  const remRecord = diag.technicalDetails.remediationRecord;

  return (
    <div
      className={`rounded-lg border p-4 sm:p-5 transition-all shadow-xs space-y-4 ${severityBg}`}
      data-testid={`diagnostic-card-${diag.id}`}
    >
      {/* 1. Header: Severity Badge, Protocol, Fix Method */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-slate-200/60 pb-3">
        <div className="flex items-center gap-2">
          <span
            className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider border flex items-center gap-1.5 ${severityBadgeClass}`}
          >
            {severityIcon}
            <span>{diag.badgeLabel}</span>
          </span>
          <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded bg-white border border-slate-200 text-slate-700">
            {diag.category}
          </span>
        </div>

        <span
          className={`text-[11px] font-medium px-2.5 py-0.5 rounded-md border flex items-center gap-1 ${
            diag.fixMethod === "automated"
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : diag.fixMethod === "manual"
              ? "bg-slate-100 text-slate-700 border-slate-200"
              : "bg-blue-50 text-blue-700 border-blue-200"
          }`}
        >
          {diag.fixMethod === "automated" && (
            <Zap className="w-3 h-3 text-emerald-600 fill-emerald-600/30" />
          )}
          {diag.fixMethodLabel}
        </span>
      </div>

      {/* 2. Plain-English Summary: What We Found */}
      <div className="space-y-1">
        <h4 className="text-sm font-bold text-slate-900 font-sans tracking-tight">
          {diag.whatWeFound}
        </h4>
        <p className="text-xs text-slate-700 leading-relaxed font-sans">
          {diag.whyItMatters}
        </p>
      </div>

      {/* 3. Business Impact & Action Guidance Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        {/* Business Impact */}
        <div className="p-3 bg-white/80 rounded-md border border-slate-200 space-y-1">
          <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 font-mono block">
            Business &amp; Customer Impact
          </span>
          <p className="text-slate-800 font-sans leading-relaxed">
            {diag.businessImpact}
          </p>
        </div>

        {/* Recommended Action */}
        <div className="p-3 bg-white/80 rounded-md border border-slate-200 space-y-1">
          <span className="text-[10px] uppercase font-bold tracking-wider text-emerald-700 font-mono block">
            Recommended Action
          </span>
          <p className="text-slate-800 font-sans leading-relaxed">
            {diag.nextAction}
          </p>
        </div>
      </div>

      {/* 4. Actionable Remediation Section (if record available) */}
      {remRecord && (
        <div className="p-3.5 bg-white rounded-lg border border-emerald-200 space-y-2.5 shadow-2xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <span className="text-xs font-bold text-emerald-900 font-sans flex items-center gap-1.5">
              <span>Required DNS Record</span>
              <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200">
                {remRecord.record_type}
              </span>
            </span>

            <div className="flex items-center gap-2">
              {/* 1-Click Auto-Fix Button if supported and handler attached */}
              {context.hasCloudflare && onApplyAutoFix ? (
                <button
                  type="button"
                  onClick={() => onApplyAutoFix(remRecord)}
                  disabled={isApplyingAutoFix || autoFixSuccess}
                  className={`px-3 py-1.5 rounded-md text-xs font-semibold font-mono transition flex items-center gap-1.5 cursor-pointer ${
                    autoFixSuccess
                      ? "bg-emerald-50 text-emerald-800 border border-emerald-300 cursor-default"
                      : isApplyingAutoFix
                      ? "bg-slate-100 text-slate-500 border border-slate-200 cursor-wait"
                      : "bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs"
                  }`}
                  aria-label={`Auto-insert ${remRecord.record_type} record to Cloudflare`}
                >
                  {autoFixSuccess ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                      <span>✓ Applied to Zone</span>
                    </>
                  ) : isApplyingAutoFix ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Applying...</span>
                    </>
                  ) : (
                    <>
                      <Zap className="w-3.5 h-3.5 fill-white/20" />
                      <span>Auto-Insert (Cloudflare)</span>
                    </>
                  )}
                </button>
              ) : context.hasGoDaddy ? (
                <span className="text-[11px] font-mono text-slate-500 bg-slate-50 border border-slate-200 px-2.5 py-1 rounded">
                  GoDaddy: Manual Copy Below
                </span>
              ) : (
                <Link
                  href="/dashboard/settings?tab=providers"
                  className="px-2.5 py-1 text-xs font-mono text-slate-600 hover:text-emerald-700 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded transition inline-flex items-center gap-1"
                >
                  <span>Connect DNS Provider</span>
                  <ArrowRight className="w-3 h-3" />
                </Link>
              )}

              {/* Copy Value Button */}
              <button
                type="button"
                onClick={() => handleCopy(remRecord.value)}
                className="px-2.5 py-1.5 rounded-md bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 font-mono text-xs font-medium transition flex items-center gap-1 shadow-2xs cursor-pointer"
                aria-label="Copy DNS record value to clipboard"
              >
                {isCopied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                    <span>Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 text-slate-500" />
                    <span>Copy Value</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Record Details Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 text-xs font-mono bg-slate-50 p-2.5 rounded border border-slate-200">
            <div>
              <span className="text-[10px] text-slate-500 uppercase block">Host / Name</span>
              <code className="text-slate-900 font-bold block truncate" title={remRecord.host}>
                {remRecord.host}
              </code>
            </div>
            <div className="sm:col-span-3">
              <span className="text-[10px] text-slate-500 uppercase block">Value / Content</span>
              <code className="text-slate-900 break-all select-all block text-[11px]">
                {remRecord.value}
              </code>
            </div>
          </div>

          {/* Auto-Fix Error Alert if any */}
          {autoFixError && (
            <div className="p-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700 font-mono flex items-center justify-between">
              <span>{autoFixError}</span>
              {autoFixError.includes("plan required") && (
                <Link
                  href="/dashboard/billing"
                  className="underline hover:text-rose-900 font-bold text-[11px]"
                >
                  View Plans
                </Link>
              )}
            </div>
          )}

          <p className="text-[11px] text-slate-500 font-sans italic">
            {diag.verificationStep}
          </p>
        </div>
      )}

      {/* 5. Expandable Technical Details Drawer */}
      <div className="pt-2 border-t border-slate-200/60">
        <button
          type="button"
          onClick={() => setIsTechDetailsOpen((prev) => !prev)}
          className="text-xs text-slate-500 hover:text-slate-900 font-mono transition flex items-center gap-1.5 cursor-pointer focus:outline-none focus:ring-1 focus:ring-emerald-500/50 rounded px-1 py-0.5"
          aria-expanded={isTechDetailsOpen}
          aria-controls={`tech-details-${diag.id}`}
        >
          <Terminal className="w-3.5 h-3.5 text-slate-400" />
          <span>Technical details &amp; RFC specifications</span>
          <ChevronDown
            className={`w-3.5 h-3.5 text-slate-400 transition-transform ${
              isTechDetailsOpen ? "rotate-180 text-emerald-600" : ""
            }`}
          />
        </button>

        {isTechDetailsOpen && (
          <div
            id={`tech-details-${diag.id}`}
            className="mt-3 p-3 bg-white rounded-md border border-slate-200 space-y-2 text-xs font-mono text-slate-700 animate-fadeIn"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
              <div>
                <span className="text-slate-400 block text-[10px] uppercase">Internal Issue ID</span>
                <code className="text-slate-900 font-bold">{diag.technicalDetails.rawId}</code>
              </div>
              <div>
                <span className="text-slate-400 block text-[10px] uppercase">Protocol Category</span>
                <span className="text-slate-800">{diag.technicalDetails.category}</span>
              </div>
            </div>

            <div>
              <span className="text-slate-400 block text-[10px] uppercase">Raw Specification Finding</span>
              <p className="text-slate-800 font-sans text-xs mt-0.5">
                {diag.technicalDetails.rawDescription}
              </p>
            </div>

            {diag.technicalDetails.evidence && (
              <div>
                <span className="text-slate-400 block text-[10px] uppercase">Technical Evidence</span>
                <code className="text-slate-900 break-all select-all block bg-slate-50 p-2 rounded border border-slate-200 text-[11px] mt-0.5">
                  {diag.technicalDetails.evidence}
                </code>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
