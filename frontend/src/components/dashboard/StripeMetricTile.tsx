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
  iconColor = "text-emerald-600",
  children,
  className = "",
}: StripeMetricTileProps) {
  const badgeColors = {
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    rose: "bg-rose-50 text-rose-700 border-rose-200",
    neutral: "bg-slate-100 text-slate-600 border-slate-200",
  }[badgeVariant];

  const highlightColors = {
    emerald: "text-emerald-700",
    amber: "text-amber-700",
    rose: "text-rose-700",
    neutral: "text-slate-500",
  }[highlightVariant];

  return (
    <div
      className={`group relative flex flex-col justify-between overflow-hidden rounded-lg border border-slate-200 bg-white p-5 shadow-xs transition-all duration-150 hover:border-slate-300 hover:shadow-sm min-h-[160px] h-full ${className}`}
    >
      {/* Header Row: Label + Badge or Icon */}
      <div className="flex items-center justify-between relative z-10">
        <span className="text-[11px] font-mono font-semibold uppercase tracking-wider text-slate-500">
          {label}
        </span>
        {badgeText ? (
          <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full font-bold border ${badgeColors}`}>
            {badgeText}
          </span>
        ) : Icon ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-1.5 text-slate-500 transition-colors group-hover:text-emerald-600 group-hover:border-emerald-200">
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
          <span className="text-2xl sm:text-3xl font-bold font-mono text-slate-950 tracking-tight tabular-nums">
            {value}
          </span>
          {unit && (
            <span className="font-mono text-xs text-slate-500 font-normal">
              {unit}
            </span>
          )}
        </div>

        {/* Subtext, Delta, and Highlights */}
        <div className="text-[11px] font-mono flex items-center justify-between gap-2 text-slate-500">
          {highlightText ? (
            <span className={`font-semibold ${highlightColors}`}>
              {highlightText}
            </span>
          ) : delta ? (
            <div className="flex items-center gap-1">
              {delta.direction === "up" ? (
                <span className="flex items-center gap-0.5 font-semibold text-emerald-700">
                  <TrendingUp className="h-3 w-3" />
                  {delta.percentage}
                </span>
              ) : delta.direction === "down" ? (
                <span className="flex items-center gap-0.5 font-semibold text-rose-700">
                  <TrendingDown className="h-3 w-3" />
                  {delta.percentage}
                </span>
              ) : (
                <span className="font-semibold text-slate-400">&mdash;</span>
              )}
              {delta.subtext && <span className="text-slate-400">{delta.subtext}</span>}
            </div>
          ) : subtext ? (
            <span className="truncate text-slate-500">{subtext}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default StripeMetricTile;
