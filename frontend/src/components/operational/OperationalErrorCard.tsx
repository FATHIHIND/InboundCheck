"use client";

import React, { useState } from "react";
import { AlertTriangle, RefreshCw, Copy, Check, Terminal, ExternalLink, ShieldAlert } from "lucide-react";
import { ApiError } from "@/lib/apiResource";

interface OperationalErrorCardProps {
  title?: string;
  error?: ApiError | null;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
  compact?: boolean;
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
  const message = error?.message || "Failed to establish a secure connection to the diagnostic telemetry backend.";

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
        className={`bg-[#0E0E12]/90 border border-rose-500/30 rounded-xl p-4 flex items-center justify-between gap-4 backdrop-blur-md ${className}`}
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20 shrink-0">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-rose-300">{title}</div>
            <div className="text-[11px] text-zinc-400 font-mono line-clamp-1">{message}</div>
          </div>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-xs font-medium border border-emerald-500/20 transition-colors shrink-0"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={`relative overflow-hidden rounded-2xl bg-[#0E0E12]/95 border border-rose-500/30 p-6 shadow-2xl backdrop-blur-xl transition-all ${className}`}
    >
      {/* Ambient background glow */}
      <div className="absolute top-0 right-0 -mr-16 -mt-16 w-64 h-64 bg-rose-500/5 rounded-full blur-3xl pointer-events-none" />

      <div className="relative flex flex-col md:flex-row md:items-start justify-between gap-6">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 shadow-inner shrink-0 mt-0.5">
            <ShieldAlert className="w-6 h-6" />
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-3 flex-wrap">
              <h3 className="text-base font-semibold text-white tracking-tight">{title}</h3>
              {status && (
                <span className="px-2 py-0.5 rounded-md bg-rose-500/20 text-rose-300 font-mono text-[11px] font-semibold border border-rose-500/30">
                  HTTP {status}
                </span>
              )}
              <span className="px-2 py-0.5 rounded-md bg-zinc-800/80 text-zinc-400 font-mono text-[11px] border border-zinc-700/50">
                SYSTEM DEGRADED
              </span>
            </div>

            <p className="text-sm text-zinc-300 leading-relaxed max-w-2xl font-sans">
              {message}
            </p>

            {/* Technical diagnostic details */}
            <div className="pt-2 flex flex-wrap items-center gap-3 text-xs font-mono text-zinc-400">
              {endpoint && (
                <div className="flex items-center gap-1.5 bg-black/40 px-2.5 py-1 rounded-md border border-white/5">
                  <Terminal className="w-3.5 h-3.5 text-zinc-500" />
                  <span className="text-zinc-500">Route:</span>
                  <span className="text-zinc-300">{endpoint}</span>
                </div>
              )}

              {referenceId && (
                <div className="flex items-center gap-1.5 bg-black/40 px-2.5 py-1 rounded-md border border-white/5">
                  <span className="text-zinc-500">Ref ID:</span>
                  <span className="text-amber-300/90 font-medium">{referenceId}</span>
                  <button
                    onClick={handleCopyRef}
                    title="Copy incident reference ID"
                    className="ml-1 hover:text-white transition-colors p-0.5"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Action triggers */}
        <div className="flex md:flex-col items-center md:items-end justify-end gap-2.5 shrink-0 pt-2 md:pt-0">
          {onRetry && (
            <button
              onClick={onRetry}
              className="w-full md:w-auto flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-black font-semibold text-xs transition-all shadow-lg shadow-emerald-500/20 active:scale-95"
            >
              <RefreshCw className="w-4 h-4" />
              {retryLabel}
            </button>
          )}

          {referenceId && (
            <button
              onClick={handleCopyRef}
              className="w-full md:w-auto flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-300 text-xs font-medium border border-white/10 transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Reference Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-zinc-400" />
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
