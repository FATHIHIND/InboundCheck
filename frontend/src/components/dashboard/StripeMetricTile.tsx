"use client";

import React from "react";
import { TrendingUp, TrendingDown, LucideIcon } from "lucide-react";

export interface StripeMetricTileProps {
  label: string;
  value: React.ReactNode;
  unit?: string;
  subtext?: string;
  highlightText?: string;
  highlightVariant?: "emerald" | "amber" | "rose" | "neutral";
  badgeText?: string;
  badgeVariant?: "emerald" | "amber" | "rose" | "neutral";
  delta?: {
    direction: "up" | "down" | "neutral";
    percentage: string;
    subtext?: string;
  };
  icon?: LucideIcon;
  iconColor?: string;
  children?: React.ReactNode;
  className?: string;
}

export function StripeMetricTile({
  label,
  value,
  unit,
  subtext,
  highlightText,
  highlightVariant = "neutral",
  badgeText,
  badgeVariant = "neutral",
  delta,
  icon: Icon,
  iconColor = "text-emerald-400",
  children,
  className = "",
}: StripeMetricTileProps) {
  const badgeColors = {
    emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    rose: "bg-rose-500/10 text-rose-400 border-rose-500/30",
    neutral: "bg-white/5 text-zinc-400 border-white/10",
  }[badgeVariant];

  const highlightColors = {
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    rose: "text-rose-400",
    neutral: "text-zinc-400",
  }[highlightVariant];

  return (
    <div
      className={`group relative flex flex-col justify-between overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0A0A0C] p-5 shadow-fluent-elevation transition-all duration-200 hover:border-white/[0.16] hover:bg-[#0E1015] min-h-[160px] h-full ${className}`}
    >
      {/* Specular Top Edge (Stripe Hairline) */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/[0.14] to-transparent" />

      {/* Header Row: Label + Badge or Icon */}
      <div className="flex items-center justify-between relative z-10">
        <span className="text-xs uppercase tracking-widest text-zinc-400 font-mono font-semibold">
          {label}
        </span>
        {badgeText ? (
          <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full font-bold border ${badgeColors}`}>
            {badgeText}
          </span>
        ) : Icon ? (
          <div className="rounded-md border border-white/[0.06] bg-white/[0.02] p-1.5 text-zinc-400 transition-colors group-hover:text-emerald-400 group-hover:border-emerald-500/30">
            <Icon className={`h-4 w-4 ${iconColor}`} aria-hidden="true" />
          </div>
        ) : null}
      </div>

      {/* Center Slot: Optional 3D Canvas / Visual Gauge */}
      {children && (
        <div className="w-full my-auto relative z-10">
          {children}
        </div>
      )}

      {/* Metric Value & Dynamics */}
      <div className="space-y-1 relative z-10 mt-auto pt-2">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-2xl sm:text-3xl font-extrabold tracking-tight text-white tabular-nums">
            {value}
          </span>
          {unit && (
            <span className="font-mono text-xs text-zinc-500 font-normal">
              {unit}
            </span>
          )}
        </div>

        {/* Subtext, Delta, and Highlights */}
        <div className="text-[11px] font-mono flex items-center justify-between gap-2 text-zinc-400">
          {highlightText ? (
            <span className={`font-semibold ${highlightColors}`}>
              {highlightText}
            </span>
          ) : delta ? (
            <div className="flex items-center gap-1">
              {delta.direction === "up" ? (
                <span className="flex items-center gap-0.5 font-semibold text-emerald-400">
                  <TrendingUp className="h-3 w-3" />
                  {delta.percentage}
                </span>
              ) : delta.direction === "down" ? (
                <span className="flex items-center gap-0.5 font-semibold text-rose-400">
                  <TrendingDown className="h-3 w-3" />
                  {delta.percentage}
                </span>
              ) : (
                <span className="font-semibold text-zinc-400">&mdash;</span>
              )}
              {delta.subtext && <span className="text-zinc-500">{delta.subtext}</span>}
            </div>
          ) : subtext ? (
            <span className="truncate">{subtext}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
