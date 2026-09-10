"use client";

import React from "react";
import { Loader2 } from "lucide-react";

interface OperationalLoadingStateProps {
  label?: string;
  subtext?: string;
  className?: string;
  rows?: number;
}

export function OperationalLoadingState({
  label = "Querying live diagnostic telemetry...",
  subtext = "Establishing secure mTLS session with diagnostic nodes",
  className = "",
  rows = 3,
}: OperationalLoadingStateProps) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl bg-[#0E0E12]/70 border border-white/5 p-8 backdrop-blur-xl shadow-xl space-y-6 ${className}`}
    >
      <div className="flex items-center gap-4">
        <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
        <div>
          <div className="text-sm font-medium text-white">{label}</div>
          <div className="text-xs text-zinc-500 font-mono mt-0.5">{subtext}</div>
        </div>
      </div>

      <div className="space-y-3 pt-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-12 w-full rounded-xl bg-white/[0.02] border border-white/[0.04] animate-pulse flex items-center px-4 justify-between"
          >
            <div className="h-4 bg-white/5 rounded-md w-1/3" />
            <div className="h-4 bg-white/5 rounded-md w-1/6" />
            <div className="h-4 bg-white/5 rounded-md w-1/4" />
          </div>
        ))}
      </div>
    </div>
  );
}
