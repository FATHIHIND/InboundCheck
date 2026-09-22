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
  badgeVariant?: "emerald" | "amber" | "cyan" | "rose" | "neutral";
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
  /** Whether to disable background accents (preserved for backwards compatibility) */
  disableGrid?: boolean;
  /** Optional custom footer label */
  footerLabel?: string;
  /** Nested content or additional children elements */
  children?: React.ReactNode;
  /** Additional CSS class names for custom layout overrides */
  className?: string;
}

const BADGE_VARIANTS = {
  emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
  amber: "bg-amber-50 text-amber-700 border-amber-200",
  cyan: "bg-sky-50 text-sky-700 border-sky-200",
  rose: "bg-rose-50 text-rose-700 border-rose-200",
  neutral: "bg-slate-100 text-slate-600 border-slate-200",
};

const DOT_VARIANTS = {
  emerald: "bg-emerald-500",
  amber: "bg-amber-500",
  cyan: "bg-sky-500",
  rose: "bg-rose-500",
  neutral: "bg-slate-400",
};

/**
 * Enterprise Classic Card styled strictly for Style Option A (Stripe/Shopify Admin Classic).
 * Base: Pure White (#FFFFFF), Hairline Border (#E2E8F0), Shadow-xs, High-Contrast Typography.
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
  disableGrid: _disableGrid = false,
  footerLabel,
  children,
  className = "",
}) => {
  return (
    <div
      onClick={onClick}
      className={`group relative overflow-hidden rounded-lg border border-slate-200 bg-white p-6 shadow-xs transition-all duration-200 hover:border-slate-300 hover:shadow-sm ${
        onClick ? "cursor-pointer" : ""
      } ${className}`}
    >
      {/* Card Header & Badge */}
      <div className="relative z-10 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 transition-colors duration-200">
            {icon || <ShieldCheck className="h-5 w-5" />}
          </div>
          <div>
            <h3 className="text-sm sm:text-base font-semibold tracking-tight text-slate-900 transition-colors duration-200 group-hover:text-emerald-800">
              {title}
            </h3>
            {subtitle && (
              <p className="text-xs font-normal text-slate-500 mt-0.5">
                {subtitle}
              </p>
            )}
          </div>
        </div>

        {badgeText && (
          <div
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-mono font-medium tracking-tight ${BADGE_VARIANTS[badgeVariant]}`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${DOT_VARIANTS[badgeVariant]}`}
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
              <span className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-slate-950 tabular-nums">
                {metricValue}
              </span>
            </div>
          )}
          {trendText && (
            <div className="flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              <Sparkles className="h-3 w-3 text-emerald-600" />
              <span>{trendText}</span>
            </div>
          )}
        </div>
      )}

      {/* Children Content Slot */}
      {children && <div className="relative z-10 mt-4">{children}</div>}

      {/* Card Action Footer */}
      {(actionLabel || footerLabel) && (
        <div
          className={`relative z-10 mt-5 pt-3 border-t border-slate-100 flex items-center ${
            footerLabel && actionLabel ? "justify-between" : footerLabel ? "justify-start" : "justify-end"
          }`}
        >
          {footerLabel && (
            <span className="text-xs text-slate-500 font-medium">
              {footerLabel}
            </span>
          )}
          {actionLabel && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onActionClick?.();
              }}
              className="flex items-center gap-1 text-xs font-semibold text-emerald-700 hover:text-emerald-800 transition-colors group-hover:translate-x-0.5 duration-150"
            >
              <span>{actionLabel}</span>
              <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default GlassEmeraldCard;
