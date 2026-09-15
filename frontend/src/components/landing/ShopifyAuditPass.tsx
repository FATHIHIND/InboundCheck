"use client";

import React from "react";
import { CheckCircle2, AlertTriangle, ShieldCheck } from "lucide-react";

interface AuditCardProps {
  type: "storefront" | "radar";
}

export function ShopifyAuditCard({ type }: AuditCardProps) {
  const isRadar = type === "radar";

  return (
    <div className="animated-audit-card w-full max-w-[440px] flex flex-col justify-between p-7 md:p-8 rounded-2xl">
      {/* Top Header & Content Body */}
      <div className="space-y-6 relative z-10">
        {/* Top Label & Badge */}
        <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
          <span className="text-[11px] font-mono tracking-wider uppercase text-gray-400 font-semibold">
            {isRadar ? "INBOUNDCHECK RADAR AUDIT" : "STORE FRONT REPORT"}
          </span>
          <span className="text-[10px] font-mono font-bold px-2.5 py-1 rounded-full border bg-emerald-500/15 text-emerald-400 border-emerald-500/30 flex items-center gap-1.5 shadow-[0_0_12px_rgba(16,185,129,0.15)]">
            {isRadar ? (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                DELIVERABILITY BLINDSPOT
              </>
            ) : (
              <>
                <CheckCircle2 size={12} className="text-emerald-400" />
                SHOPIFY STATUS: NORMAL
              </>
            )}
          </span>
        </div>

        {/* Title & Subtitle */}
        <div>
          <h3 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
            {isRadar ? "240 Receipts in Spam" : "1,000 Orders Placed"}
          </h3>
          <p className="text-xs sm:text-sm text-gray-400 font-sans mt-1">
            {isRadar
              ? "Blocked by Gmail & Yahoo 2024 filters"
              : "Store receipts dispatched automatically"}
          </p>
        </div>

        {/* Key Metrics / Details Grid */}
        <div className="space-y-2.5 font-mono text-xs pt-1">
          {isRadar ? (
            <>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Spam Placement</span>
                <span className="text-emerald-400 font-bold">24% of Total Orders</span>
              </div>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Customer Disputes</span>
                <span className="text-white font-semibold">42 &ldquo;Where&apos;s my order?&rdquo; tickets</span>
              </div>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Monthly GMV at Risk</span>
                <span className="text-emerald-400 font-bold">-$4,200.00</span>
              </div>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Root Cause</span>
                <span className="text-amber-300 font-semibold">Missing SPF / Broken DKIM</span>
              </div>
            </>
          ) : (
            <>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Tracking Emails</span>
                <span className="text-white font-semibold">1,000 Dispatched</span>
              </div>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Store Health</span>
                <span className="text-emerald-400 font-semibold">100% (Assumed)</span>
              </div>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Customer Support</span>
                <span className="text-white font-semibold">Normal Volume</span>
              </div>
              <div className="p-3.5 bg-[#090D11]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span className="text-gray-400">Shopify Notification</span>
                <span className="text-emerald-400 font-semibold flex items-center gap-1.5">
                  <CheckCircle2 size={13} /> Sent Successfully
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Bottom Summary Footnote */}
      <div className="pt-6 mt-6 border-t border-white/[0.08] relative z-10">
        <p className="text-xs text-gray-400 font-sans italic leading-relaxed">
          {isRadar
            ? "“InboundCheck eliminates this blindspot with 24/7 proactive DNS and deliverability monitoring.”"
            : "“Everything looks green in Shopify admin. Merchants assume deliveries are 100% successful.”"}
        </p>
      </div>
    </div>
  );
}

export function ShopifyAuditPasses() {
  return (
    <div className="flex flex-col md:flex-row items-stretch justify-center gap-8 w-full">
      <ShopifyAuditCard type="storefront" />
      <ShopifyAuditCard type="radar" />
    </div>
  );
}

export default ShopifyAuditPasses;
