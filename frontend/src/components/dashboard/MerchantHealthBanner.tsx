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
      badgeClass: "bg-rose-50 text-rose-800 border-rose-200",
      accentBarClass: "bg-rose-500",
      icon: ShieldAlert,
      iconColor: "text-rose-600",
      containerClass: "border-rose-200 bg-rose-50/40",
      title: `${atRiskOrders > 0 ? atRiskOrders.toLocaleString() : "Store"} Order Confirmation Receipts at Risk`,
      description: `Critical SPF/DMARC misalignment detected on ${domainName || "store sending domain"}. Google and Yahoo 2024 mailbox filters are rejecting unauthenticated checkout receipts and order tracking updates.`,
      tag: "Critical Misalignment",
    },
    warning: {
      badgeClass: "bg-amber-50 text-amber-800 border-amber-200",
      accentBarClass: "bg-amber-500",
      icon: AlertTriangle,
      iconColor: "text-amber-600",
      containerClass: "border-amber-200 bg-amber-50/40",
      title: "Delivery Degradation Warning",
      description: `Suboptimal DNS configuration on ${domainName || "store domain"}. Marketing flows and receipts risk spam folder placement.`,
      tag: "Moderate Attrition Exposure",
    },
    optimal: {
      badgeClass: "bg-emerald-50 text-emerald-800 border-emerald-200",
      accentBarClass: "bg-emerald-500",
      icon: CheckCircle2,
      iconColor: "text-emerald-600",
      containerClass: "border-emerald-200 bg-emerald-50/40",
      title: "Store Deliverability Guarded",
      description: `All sending domains for ${domainName || "your store"} pass 2024 Google & Yahoo inbox standards. 100% of order receipts delivered to primary inbox.`,
      tag: "100% Protected",
    },
  }[severity];

  const IconComponent = config.icon;

  return (
    <section
      aria-label="Merchant Deliverability Health Banner"
      className={`relative overflow-hidden rounded-lg border p-5 shadow-xs ${config.containerClass}`}
    >
      {/* Top 2px micro-accent bar */}
      <div className={`absolute inset-x-0 top-0 h-[2px] ${config.accentBarClass}`} />

      <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left: Icon & Merchant-First Problem Translation */}
        <div className="flex items-start sm:items-center gap-3.5">
          <div
            className={`w-10 h-10 rounded-lg border flex items-center justify-center shrink-0 ${config.badgeClass}`}
          >
            <IconComponent
              className={`w-5 h-5 ${config.iconColor}`}
              aria-hidden="true"
            />
          </div>

          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm sm:text-base font-bold text-slate-900 tracking-tight flex items-center gap-1.5">
                <span>{config.title}</span>
              </h2>
              <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full font-semibold border ${config.badgeClass}`}>
                {config.tag}
              </span>
              {misalignedStoresCount > 1 && severity !== "optimal" && (
                <span className="text-[10px] font-mono text-slate-600 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full">
                  {misalignedStoresCount} Domains Affected
                </span>
              )}
            </div>
            <p className="text-xs text-slate-600 leading-relaxed max-w-3xl">
              {config.description}
            </p>
          </div>
        </div>

        {/* Right: Stripe-Style Financial At-Risk Number + Single-Click CTAs */}
        <div className="flex flex-wrap items-center gap-3.5 shrink-0 pt-2 lg:pt-0">
          {atRiskGmvFormatted && severity !== "optimal" && (
            <div className="text-left lg:text-right mr-2">
              <span className="block text-[10px] font-mono uppercase tracking-wider text-slate-500">
                At-Risk Order GMV
              </span>
              <span className="font-mono text-base sm:text-lg font-bold tabular-nums text-rose-600">
                {atRiskGmvFormatted}
              </span>
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenWizard}
              className="inline-flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-4 py-2 rounded-md text-xs transition-colors shadow-xs cursor-pointer"
            >
              <Zap className="w-3.5 h-3.5 fill-current" />
              <span>1-Click Auto-Remediation</span>
            </button>

            <Link
              href={inspectorHref}
              className="inline-flex items-center gap-1.5 bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 font-medium px-4 py-2 rounded-md text-xs transition-colors shadow-2xs cursor-pointer"
            >
              <Terminal className="w-3.5 h-3.5 text-emerald-600" />
              <span>Inspect DNS</span>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

export default MerchantHealthBanner;
