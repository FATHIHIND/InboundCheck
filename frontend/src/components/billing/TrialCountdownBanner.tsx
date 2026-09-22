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
  trialEndsAt: _trialEndsAt,
  onUpgradeClick,
}: TrialCountdownBannerProps) {
  const displayDays = Math.max(0, daysRemaining);
  const formattedDays = displayDays < 1 ? "< 1 day" : `${Math.ceil(displayDays)} days`;

  return (
    <div className="sticky top-0 z-30 w-full bg-emerald-50 border-b border-emerald-200 px-4 py-2 shadow-2xs">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2.5 text-slate-800">
          <div className="w-5 h-5 rounded-full bg-emerald-100 border border-emerald-300 flex items-center justify-center shrink-0">
            <Clock size={12} className="text-emerald-700" />
          </div>
          <span className="font-medium text-slate-800">
            <strong className="text-emerald-800 font-semibold">{formattedDays} remaining</strong> in your free trial.
            <span className="hidden md:inline text-slate-500 ml-1.5">
              Upgrade to maintain continuous inbox protection.
            </span>
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {onUpgradeClick ? (
            <button
              type="button"
              onClick={onUpgradeClick}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition-colors shadow-xs cursor-pointer"
            >
              <Sparkles size={12} />
              <span>Upgrade Protection</span>
              <ArrowRight size={11} />
            </button>
          ) : (
            <Link
              href="/dashboard/billing"
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition-colors shadow-xs cursor-pointer"
            >
              <Sparkles size={12} />
              <span>Upgrade Protection</span>
              <ArrowRight size={11} />
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

export default TrialCountdownBanner;
