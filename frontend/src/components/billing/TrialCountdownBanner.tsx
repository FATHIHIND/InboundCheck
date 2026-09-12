"use client";

import React from "react";
import Link from "next/link";
import { Clock, Sparkles, ArrowRight } from "lucide-react";

interface TrialCountdownBannerProps {
  daysRemaining: number;
  trialEndsAt?: string | null;
  onUpgradeClick?: () => void;
}

export function TrialCountdownBanner({
  daysRemaining,
  trialEndsAt,
  onUpgradeClick,
}: TrialCountdownBannerProps) {
  const displayDays = Math.max(0, daysRemaining);
  const formattedDays = displayDays < 1 ? "< 1 day" : `${Math.ceil(displayDays)} days`;

  return (
    <div className="sticky top-0 z-30 w-full bg-gradient-to-r from-emerald-950/80 via-[#0D1612]/95 to-emerald-950/80 border-b border-emerald-500/30 backdrop-blur-md px-4 py-2.5 shadow-[0_4px_20px_rgba(16,185,129,0.12)]">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2.5 text-xs">
        <div className="flex items-center gap-2.5 text-zinc-200">
          <div className="w-6 h-6 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center shrink-0 shadow-[0_0_8px_rgba(16,185,129,0.3)]">
            <Clock size={13} className="text-emerald-400 animate-pulse" />
          </div>
          <span className="font-medium text-white tracking-tight">
            <strong className="text-emerald-400 font-semibold">{formattedDays} remaining</strong> in your free trial.
            <span className="hidden md:inline text-zinc-400 ml-1.5">
              Upgrade to maintain continuous inbox protection.
            </span>
          </span>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {onUpgradeClick ? (
            <button
              type="button"
              onClick={onUpgradeClick}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-all shadow-[0_0_12px_rgba(16,185,129,0.3)] hover:shadow-[0_0_18px_rgba(16,185,129,0.5)] cursor-pointer"
            >
              <Sparkles size={13} />
              <span>Upgrade Protection</span>
              <ArrowRight size={12} />
            </button>
          ) : (
            <Link
              href="/dashboard/billing"
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-all shadow-[0_0_12px_rgba(16,185,129,0.3)] hover:shadow-[0_0_18px_rgba(16,185,129,0.5)] cursor-pointer"
            >
              <Sparkles size={13} />
              <span>Upgrade Protection</span>
              <ArrowRight size={12} />
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
