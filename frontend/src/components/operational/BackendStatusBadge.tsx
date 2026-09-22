"use client";

import React from "react";
import { useBackendHealth } from "@/hooks/useBackendHealth";

export function BackendStatusBadge() {
  const { status, refreshHealth } = useBackendHealth(60000);

  const isOperational = status === "healthy" || status === "operational";
  const isDegraded = status === "degraded";

  return (
    <button
      type="button"
      onClick={() => refreshHealth()}
      title={isOperational ? "Monitoring Active • Click to refresh" : isDegraded ? "System Degraded • Click to refresh" : "Connecting to Services"}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-slate-200 bg-slate-50 hover:bg-slate-100 transition-colors cursor-pointer group shadow-2xs"
    >
      <span className="relative flex h-2 w-2 shrink-0">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${
            isOperational
              ? "bg-emerald-500"
              : isDegraded
              ? "bg-amber-500"
              : "bg-rose-500"
          }`}
        />
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${
            isOperational
              ? "bg-emerald-500"
              : isDegraded
              ? "bg-amber-500"
              : "bg-rose-500"
          }`}
        />
      </span>
      <span className="text-[10px] text-slate-600 group-hover:text-slate-900 font-medium select-none whitespace-nowrap">
        {isOperational ? "Monitoring Active" : isDegraded ? "System Degraded" : "Connecting..."}
      </span>
    </button>
  );
}

export default BackendStatusBadge;
