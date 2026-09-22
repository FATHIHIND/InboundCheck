"use client";

import React, { useState } from "react";
import { AlertTriangle, RefreshCw, Copy, Check, Terminal, ShieldAlert } from "lucide-react";
import { ApiError } from "@/lib/apiResource";

interface OperationalErrorCardProps {
  title?: string;
  error?: ApiError | null;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
  compact?: boolean;
}

function getMerchantAdvice(error?: ApiError | null): string {
  if (!error) return "Please check your network connection and try again in a few moments.";
  const status = error.status;
  if (status === 429) {
    return "Rate limit reached. The system automatically protects multi-resolver throughput. Please wait a moment before requesting another scan.";
  }
  if (status === 404) {
    return "The requested domain or record was not found. Please verify the domain spelling and ensure DNS records are published.";
  }
  if (status === 422 || status === 400) {
    return "Invalid domain input. Please enter a valid sending domain name (e.g., store.com) and try again.";
  }
  if (status && status >= 500) {
    return "DNS resolver servers temporarily timed out. This is usually transient—please retry in a few moments.";
  }
  return "Please review your sending domain records or retry the request in a few moments.";
}

export function OperationalErrorCard({
  title = "Operational Data Unavailable",
  error,
  onRetry,
  retryLabel = "Retry Request",
  className = "",
  compact = false,
}: OperationalErrorCardProps) {
  const [copied, setCopied] = useState(false);

  const referenceId = error?.referenceId;
  const endpoint = error?.endpoint;
  const status = error?.status;
  const rawMessage = error?.message || "";
  const isNetworkFailure = rawMessage.includes("Failed to fetch") || rawMessage.includes("NetworkError");
  const message = isNetworkFailure
    ? "Unable to connect to diagnostic services. Please verify your internet connection."
    : rawMessage || "Failed to establish a secure connection to the diagnostic services.";

  const advice = getMerchantAdvice(error);

  const handleCopyRef = () => {
    if (referenceId) {
      navigator.clipboard.writeText(referenceId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (compact) {
    return (
      <div
        className={`bg-rose-50/70 border border-rose-200 rounded-md p-3.5 flex items-center justify-between gap-4 shadow-2xs ${className}`}
      >
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-md bg-rose-100 text-rose-700 border border-rose-200 shrink-0">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-rose-900">{title}</div>
            <div className="text-[11px] text-slate-600 font-sans line-clamp-1">{advice}</div>
          </div>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold border border-slate-300 shadow-2xs transition-colors shrink-0"
          >
            <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
            <span>Retry</span>
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={`relative overflow-hidden rounded-lg bg-rose-50/40 border border-rose-200 p-5 shadow-xs transition-all ${className}`}
    >
      <div className="relative flex flex-col md:flex-row md:items-start justify-between gap-5">
        <div className="flex items-start gap-3.5">
          <div className="p-2.5 rounded-lg bg-rose-100 border border-rose-200 text-rose-700 shrink-0 mt-0.5">
            <ShieldAlert className="w-5 h-5" />
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h3 className="text-base font-semibold text-slate-900 tracking-tight">{title}</h3>
              {process.env.NODE_ENV === "development" && status && (
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-rose-100 text-rose-800 border border-rose-200">
                  HTTP {status}
                </span>
              )}
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider bg-amber-100 text-amber-800 border border-amber-200">
                ACTION REQUIRED
              </span>
            </div>

            <p className="text-sm text-slate-700 leading-relaxed max-w-2xl font-sans">
              {message}
            </p>

            <p className="text-xs text-slate-600 font-sans leading-relaxed max-w-2xl bg-white border border-slate-200 rounded-md p-2.5 shadow-2xs">
              <span className="text-emerald-700 font-semibold">Suggested Action: </span>
              {advice}
            </p>

            {/* Technical diagnostic details (Development Only) */}
            {process.env.NODE_ENV === "development" && (endpoint || referenceId) && (
              <div className="pt-1 flex flex-wrap items-center gap-2.5 text-xs font-mono text-slate-600">
                {endpoint && (
                  <div className="flex items-center gap-1.5 bg-white px-2.5 py-1 rounded border border-slate-200 shadow-2xs">
                    <Terminal className="w-3.5 h-3.5 text-slate-400" />
                    <span className="text-slate-400">Route:</span>
                    <span className="text-slate-700">{endpoint}</span>
                  </div>
                )}

                {referenceId && (
                  <div className="flex items-center gap-1.5 bg-white px-2.5 py-1 rounded border border-slate-200 shadow-2xs">
                    <span className="text-slate-400">Ref ID:</span>
                    <span className="text-slate-800 font-medium">{referenceId}</span>
                    <button
                      onClick={handleCopyRef}
                      title="Copy incident reference ID"
                      className="ml-1 text-slate-400 hover:text-slate-600 transition-colors p-0.5"
                    >
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Action triggers */}
        <div className="flex md:flex-col items-center md:items-end justify-end gap-2 shrink-0 pt-2 md:pt-0">
          {onRetry && (
            <button
              onClick={onRetry}
              className="w-full md:w-auto flex items-center justify-center gap-1.5 px-4 py-2 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition-colors shadow-xs cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>{retryLabel}</span>
            </button>
          )}

          {referenceId && (
            <button
              onClick={handleCopyRef}
              className="w-full md:w-auto flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium border border-slate-300 transition-colors shadow-2xs cursor-pointer"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Reference Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-slate-500" />
                  <span>Copy Incident Ref</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default OperationalErrorCard;
