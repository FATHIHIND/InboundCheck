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
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-white/5 bg-white/[0.02] hover:bg-white/[0.05] transition-colors cursor-pointer group"
    >
      <span className="relative flex h-2 w-2 shrink-0">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${
            isOperational
              ? "bg-emerald-400"
              : isDegraded
              ? "bg-amber-400"
              : "bg-rose-400"
          }`}
        />
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${
            isOperational
              ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]"
              : isDegraded
              ? "bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.8)]"
              : "bg-rose-400 shadow-[0_0_6px_rgba(248,113,113,0.8)]"
          }`}
        />
      </span>
      <span className="text-[10px] text-zinc-400 group-hover:text-zinc-300 font-sans select-none whitespace-nowrap">
        {isOperational ? "Monitoring Active" : isDegraded ? "System Degraded" : "Connecting..."}
      </span>
    </button>
  );
}

export default BackendStatusBadge;
