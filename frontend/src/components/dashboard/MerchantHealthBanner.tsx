"use client";

import React from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, ShieldAlert, Zap, Terminal } from "lucide-react";

export type HealthSeverity = "critical" | "warning" | "optimal";

export interface MerchantHealthBannerProps {
  severity: HealthSeverity;
  domainName: string;
  atRiskOrders?: number;
  atRiskGmvFormatted?: string;
  misalignedStoresCount?: number;
  onOpenWizard: () => void;
  inspectorHref?: string;
}

export function MerchantHealthBanner({
  severity,
  domainName,
  atRiskOrders = 0,
  atRiskGmvFormatted,
  misalignedStoresCount = 1,
  onOpenWizard,
  inspectorHref = "/dashboard/inspector",
}: MerchantHealthBannerProps) {
  const config = {
    critical: {
      badgeClass: "bg-rose-500/10 text-rose-400 border-rose-500/30",
      accentBarClass: "bg-gradient-to-r from-rose-500 via-amber-500 to-transparent",
      icon: ShieldAlert,
      iconColor: "text-rose-400",
      containerClass:
        "border-rose-500/40 bg-gradient-to-r from-rose-950/40 via-[#0A0A0C] to-rose-950/20 shadow-[0_0_30px_rgba(244,63,94,0.15)]",
      title: `${atRiskOrders > 0 ? atRiskOrders.toLocaleString() : "Store"} Order Confirmation Receipts at Risk`,
      description: `Critical SPF/DMARC misalignment detected on ${domainName || "store sending domain"}. Google and Yahoo 2024 mailbox filters are rejecting unauthenticated checkout receipts and order tracking updates.`,
      tag: "Critical Misalignment",
    },
    warning: {
      badgeClass: "bg-amber-500/10 text-amber-400 border-amber-500/30",
      accentBarClass: "bg-gradient-to-r from-amber-500 via-yellow-500 to-transparent",
      icon: AlertTriangle,
      iconColor: "text-amber-400",
      containerClass:
        "border-amber-500/30 bg-gradient-to-r from-amber-950/30 via-[#0A0A0C] to-amber-950/15 shadow-[0_0_25px_rgba(245,158,11,0.1)]",
      title: "Delivery Degradation Warning",
      description: `Suboptimal DNS configuration on ${domainName || "store domain"}. Marketing flows and receipts risk spam folder placement.`,
      tag: "Moderate Attrition Exposure",
    },
    optimal: {
      badgeClass: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
      accentBarClass: "bg-gradient-to-r from-emerald-500 to-transparent",
      icon: CheckCircle2,
      iconColor: "text-emerald-400",
      containerClass:
        "border-emerald-500/30 bg-gradient-to-r from-emerald-950/30 via-[#0A0A0C] to-emerald-950/10 shadow-[0_0_25px_rgba(16,185,129,0.1)]",
      title: "Store Deliverability Guarded",
      description: `All sending domains for ${domainName || "your store"} pass 2024 Google & Yahoo inbox standards. 100% of order receipts delivered to primary inbox.`,
      tag: "100% Protected",
    },
  }[severity];

  const IconComponent = config.icon;

  return (
    <section
      aria-label="Merchant Deliverability Health Banner"
      className={`relative overflow-hidden rounded-2xl border p-5 backdrop-blur-xl animate-fadeIn ${config.containerClass}`}
    >
      {/* Top 2px micro-accent bar */}
      <div className={`absolute inset-x-0 top-0 h-[2px] ${config.accentBarClass}`} />

      {/* Subtle radial inner glow */}
      <div
        className={`absolute -top-20 -right-20 h-56 w-56 rounded-full blur-3xl pointer-events-none opacity-20 ${
          severity === "critical"
            ? "bg-rose-500"
            : severity === "warning"
            ? "bg-amber-500"
            : "bg-emerald-500"
        }`}
      />

      <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left: Icon & Merchant-First Problem Translation */}
        <div className="flex items-start sm:items-center gap-3.5">
          <div
            className={`w-11 h-11 rounded-xl border flex items-center justify-center shrink-0 shadow-lg ${config.badgeClass}`}
          >
            <IconComponent
              className={`w-5 h-5 ${config.iconColor} ${severity === "critical" ? "animate-pulse" : ""}`}
              aria-hidden="true"
            />
          </div>

          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm sm:text-base font-extrabold text-white tracking-tight flex items-center gap-1.5">
                <span>{config.title}</span>
              </h2>
              <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full font-bold border ${config.badgeClass}`}>
                {config.tag}
              </span>
              {misalignedStoresCount > 1 && severity !== "optimal" && (
                <span className="text-[10px] font-mono text-zinc-400 bg-white/5 border border-white/10 px-2 py-0.5 rounded-full">
                  {misalignedStoresCount} Domains Affected
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-300 leading-relaxed max-w-3xl">
              {config.description}
            </p>
          </div>
        </div>

        {/* Right: Stripe-Style Financial At-Risk Number + Polaris Single-Click CTAs */}
        <div className="flex flex-wrap items-center gap-3.5 shrink-0 pt-2 lg:pt-0">
          {atRiskGmvFormatted && severity !== "optimal" && (
            <div className="text-left lg:text-right mr-2">
              <span className="block text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                At-Risk Order GMV
              </span>
              <span className="font-mono text-base sm:text-lg font-bold tabular-nums text-rose-400">
                {atRiskGmvFormatted}
              </span>
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenWizard}
              className="inline-flex items-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-4 py-2.5 rounded-xl text-xs transition-all shadow-lg shadow-emerald-500/20 active:scale-95 cursor-pointer min-h-[44px]"
            >
              <Zap className="w-3.5 h-3.5 fill-current" />
              <span>1-Click Auto-Remediation</span>
            </button>

            <Link
              href={inspectorHref}
              className="inline-flex items-center gap-1.5 bg-[#14141A] hover:bg-[#1E1E26] border border-white/[0.1] text-zinc-200 font-semibold px-4 py-2.5 rounded-xl text-xs transition-all active:scale-95 cursor-pointer min-h-[44px]"
            >
              <Terminal className="w-3.5 h-3.5 text-emerald-400" />
              <span>Inspect DNS</span>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
