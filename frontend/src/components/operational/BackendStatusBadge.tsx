"use client";

import React from "react";
import { Activity, AlertTriangle, CheckCircle2, XCircle, RefreshCw } from "lucide-react";
import { useBackendHealth } from "@/hooks/useBackendHealth";

export function BackendStatusBadge() {
  const { status, data, refreshHealth } = useBackendHealth(60000);

  // In production, render as a subtle unlabelled status dot without technical text
  if (process.env.NODE_ENV !== "development") {
    return (
      <div
        className="flex items-center justify-center cursor-default"
        title="Deliverability Network Active"
      >
        <div
          className={`w-2 h-2 rounded-full transition-colors ${
            status === "healthy" || status === "operational"
              ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]"
              : status === "degraded"
              ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]"
              : "bg-rose-400 shadow-[0_0_8px_rgba(248,113,113,0.6)]"
          }`}
        />
      </div>
    );
  }

  const getStatusConfig = () => {
    switch (status) {
      case "healthy":
      case "operational":
        return {
          dotColor: "bg-emerald-400",
          pingColor: "bg-emerald-400/50",
          textColor: "text-emerald-300",
          bgColor: "bg-emerald-500/10 border-emerald-500/20",
          label: "API Operational",
          icon: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
        };
      case "degraded":
        return {
          dotColor: "bg-amber-400",
          pingColor: "bg-amber-400/50",
          textColor: "text-amber-300",
          bgColor: "bg-amber-500/10 border-amber-500/20",
          label: "API Degraded",
          icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />,
        };
      case "unavailable":
        return {
          dotColor: "bg-rose-400",
          pingColor: "bg-rose-400/50",
          textColor: "text-rose-300",
          bgColor: "bg-rose-500/10 border-rose-500/20",
          label: "System Unavailable",
          icon: <XCircle className="w-3.5 h-3.5 text-rose-400" />,
        };
      case "checking":
      default:
        return {
          dotColor: "bg-zinc-400",
          pingColor: "bg-zinc-400/50",
          textColor: "text-zinc-400",
          bgColor: "bg-zinc-500/10 border-zinc-500/20",
          label: "Checking Telemetry...",
          icon: <Activity className="w-3.5 h-3.5 text-zinc-400 animate-pulse" />,
        };
    }
  };

  const config = getStatusConfig();

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => refreshHealth()}
        title={
          data?.dependencies
            ? `DB: ${data.dependencies.database} | Scheduler: ${data.dependencies.scheduler} (Click to refresh)`
            : "Click to refresh connection status"
        }
        className={`flex items-center gap-2 px-2.5 py-1 rounded-full border text-xs font-mono transition-all hover:opacity-90 active:scale-95 ${config.bgColor}`}
      >
        <span className="relative flex h-2 w-2">
          {status !== "checking" && (
            <span
              className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${config.pingColor}`}
            />
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${config.dotColor}`} />
        </span>
        <span className={`text-[11px] font-medium tracking-tight ${config.textColor}`}>
          {config.label}
        </span>
      </button>
    </div>
  );
}
