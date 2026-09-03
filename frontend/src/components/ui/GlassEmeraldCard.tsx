"use client";

import React from "react";
import { Sparkles, ArrowUpRight, ShieldCheck } from "lucide-react";

export interface GlassEmeraldCardProps {
  /** Title of the card header */
  title: string;
  /** Subtitle or section label */
  subtitle?: string;
  /** Badge tag displayed in top-right corner */
  badgeText?: string;
  /** Status variant for badge indicator dot */
  badgeVariant?: "emerald" | "amber" | "cyan" | "rose";
  /** Main quantitative metric or score */
  metricValue?: string | number;
  /** Trend comparison or indicator string (e.g. "+12.4% vs last week") */
  trendText?: string;
  /** Custom Lucide icon component to render in header avatar slot */
  icon?: React.ReactNode;
  /** Optional click handler or link action */
  onClick?: () => void;
  /** Optional secondary action label */
  actionLabel?: string;
  /** Optional secondary action click handler */
  onActionClick?: () => void;
  /** Nested content or additional children elements */
  children?: React.ReactNode;
  /** Additional CSS class names for custom layout overrides */
  className?: string;
}

const BADGE_VARIANTS = {
  emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30 shadow-[0_0_12px_rgba(16,185,129,0.2)]",
  amber: "bg-amber-500/10 text-amber-400 border-amber-500/30 shadow-[0_0_12px_rgba(245,158,11,0.2)]",
  cyan: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30 shadow-[0_0_12px_rgba(6,182,212,0.2)]",
  rose: "bg-rose-500/10 text-rose-400 border-rose-500/30 shadow-[0_0_12px_rgba(244,63,94,0.2)]",
};

const DOT_VARIANTS = {
  emerald: "bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)]",
  amber: "bg-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.8)]",
  cyan: "bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]",
  rose: "bg-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.8)]",
};

/**
 * Premium UIverse-inspired Glassmorphic Card styled strictly for the InboundCheck theme.
 * Base: Midnight Obsidian (#08080A / #0E0E12) with backdrop blur.
 * Accents: Shopify Emerald (#10B981) neon glow.
 */
export const GlassEmeraldCard: React.FC<GlassEmeraldCardProps> = ({
  title,
  subtitle,
  badgeText,
  badgeVariant = "emerald",
  metricValue,
  trendText,
  icon,
  onClick,
  actionLabel,
  onActionClick,
  children,
  className = "",
}) => {
  return (
    <div
      onClick={onClick}
      className={`group relative overflow-hidden rounded-2xl border border-emerald-500/20 bg-[#0E0E12]/80 backdrop-blur-md p-6 transition-all duration-300 hover:border-emerald-500/50 hover:shadow-[0_0_30px_rgba(16,185,129,0.18)] ${
        onClick ? "cursor-pointer" : ""
      } ${className}`}
    >
      {/* Top Ambient Radial Glow Effect */}
      <div className="pointer-events-none absolute -top-24 -left-24 h-48 w-48 rounded-full bg-emerald-500/10 blur-3xl transition-all duration-500 group-hover:bg-emerald-500/20 group-hover:scale-125" />
      <div className="pointer-events-none absolute -bottom-24 -right-24 h-48 w-48 rounded-full bg-emerald-400/5 blur-3xl transition-all duration-500 group-hover:bg-emerald-400/15" />

      {/* Cyber Subtle Grid Lines Overlay */}
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,#10b98108_1px,transparent_1px),linear-gradient(to_bottom,#10b98108_1px,transparent_1px)] bg-[size:24px_24px] opacity-40 group-hover:opacity-70 transition-opacity duration-300" />

      {/* Glass Light Reflection Shimmer Line */}
      <div className="pointer-events-none absolute -left-full top-0 h-full w-1/2 -skew-x-12 bg-gradient-to-r from-transparent via-emerald-400/10 to-transparent group-hover:animate-[shimmer_1.5s_ease-in-out_infinite]" />

      {/* Card Header & Badge */}
      <div className="relative z-10 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)] transition-transform duration-300 group-hover:scale-105 group-hover:border-emerald-400/50">
            {icon || <ShieldCheck className="h-5 w-5" />}
          </div>
          <div>
            <h3 className="text-base font-semibold tracking-tight text-white transition-colors duration-200 group-hover:text-emerald-300">
              {title}
            </h3>
            {subtitle && (
              <p className="text-xs font-medium text-zinc-400 mt-0.5">
                {subtitle}
              </p>
            )}
          </div>
        </div>

        {badgeText && (
          <div
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold tracking-wide ${BADGE_VARIANTS[badgeVariant]}`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full animate-pulse ${DOT_VARIANTS[badgeVariant]}`}
            />
            {badgeText}
          </div>
        )}
      </div>

      {/* Main Metric / Content Display */}
      {(metricValue !== undefined || trendText) && (
        <div className="relative z-10 mt-5 flex items-baseline justify-between">
          {metricValue !== undefined && (
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold tracking-tight text-white drop-shadow-[0_2px_10px_rgba(16,185,129,0.3)]">
                {metricValue}
              </span>
            </div>
          )}
          {trendText && (
            <div className="flex items-center gap-1 text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              <Sparkles className="h-3 w-3" />
              <span>{trendText}</span>
            </div>
          )}
        </div>
      )}

      {/* Children Content Slot */}
      {children && <div className="relative z-10 mt-4 text-sm">{children}</div>}

      {/* Card Action Footer */}
      {actionLabel && (
        <div className="relative z-10 mt-5 pt-3 border-t border-emerald-500/10 flex items-center justify-between">
          <span className="text-xs text-zinc-400 font-medium group-hover:text-zinc-300 transition-colors">
            InboundCheck Intelligence
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onActionClick?.();
            }}
            className="flex items-center gap-1 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition-colors group-hover:translate-x-0.5 duration-200"
          >
            <span>{actionLabel}</span>
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
};

export default GlassEmeraldCard;
