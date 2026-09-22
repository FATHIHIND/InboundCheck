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
      className={`relative overflow-hidden rounded-lg bg-white border border-slate-200 p-6 shadow-xs space-y-5 ${className}`}
    >
      <div className="flex items-center gap-3.5">
        <div className="p-2.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700">
          <Loader2 className="w-4 h-4 animate-spin" />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-900">{label}</div>
          <div className="text-xs text-slate-500 font-mono mt-0.5">{subtext}</div>
        </div>
      </div>

      <div className="space-y-2.5 pt-1">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-10 w-full rounded-md bg-slate-50 border border-slate-100 animate-pulse flex items-center px-4 justify-between"
          >
            <div className="h-3.5 bg-slate-200 rounded w-1/3" />
            <div className="h-3.5 bg-slate-200 rounded w-1/6" />
            <div className="h-3.5 bg-slate-200 rounded w-1/4" />
          </div>
        ))}
      </div>
    </div>
  );
}

export default OperationalLoadingState;
