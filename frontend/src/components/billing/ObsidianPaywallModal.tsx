"use client";

import React, { useState, useEffect } from "react";
import { Check, Sparkles, ShieldAlert, ArrowRight, Loader2, Zap, ShieldCheck, Building2 } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface ObsidianPaywallModalProps {
  onPlanSelected?: (planTier: string) => void;
  onClose?: () => void;
}

interface TierDefinition {
  id: "starter" | "growth" | "agency";
  name: string;
  monthlyPrice: string;
  annualPrice: string;
  period: string;
  annualSavings: string;
  tagline: string;
  domainLimit: string;
  isPopular?: boolean;
  features: string[];
}

const TIERS: TierDefinition[] = [
  {
    id: "starter",
    name: "Starter",
    monthlyPrice: "$9",
    annualPrice: "$7",
    period: "/ month",
    annualSavings: "Save $24/yr",
    tagline: "Essential 24/7 deliverability surveillance for single-store DTC brands.",
    domainLimit: "1 Active Store Monitored",
    features: [
      "1 Active Store Sending Domain Cap",
      "24/7 Continuous DNS & 10-RBL Blacklist Radar",
      "Instant Telegram & Slack Incident Alerts",
      "Multi-Resolver Automated Diagnostic Audits",
      "3-Day Risk-Free Trial Guarantee",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    monthlyPrice: "$29",
    annualPrice: "$23",
    period: "/ month",
    annualSavings: "Save $72/yr",
    tagline: "Multi-domain governance, automated DNS repair, and store order sync.",
    domainLimit: "Up to 3 Active Stores",
    isPopular: true,
    features: [
      "Up to 3 Active Store Sending Domains",
      "1-Click DNS Auto-Remediation (Cloudflare & GoDaddy)",
      "Shopify OAuth Order Sync & Alignment",
      "Revenue Risk Engine & Protected GMV ($2,400/wk)",
      "48-72h Predictive Blacklist Risk Forecast",
      "Smart SPF Multi-App Record Consolidation",
    ],
  },
  {
    id: "agency",
    name: "Agency",
    monthlyPrice: "$79",
    annualPrice: "$63",
    period: "/ month",
    annualSavings: "Save $192/yr",
    tagline: "Expanded capacity, multi-store management, and white-label reporting.",
    domainLimit: "Up to 20 Active Stores",
    features: [
      "Up to 20 Active Store Sending Domains",
      "Multi-Store Management Hub & Team Controls",
      "Priority 15-Minute Dedicated Radar Sweeps",
      "White-Label PDF Deliverability Audit Exports",
      "Dedicated Priority Queue & Failover Dispatch",
      "Automated Zone Auto-Patching & Backups",
    ],
  },
];

export function ObsidianPaywallModal({ onPlanSelected, onClose }: ObsidianPaywallModalProps) {
  const [billingCycle, setBillingCycle] = useState<"monthly" | "annual">("monthly");
  const [loadingTier, setLoadingTier] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [targetDomain, setTargetDomain] = useState<string>("");

  // Retrieve pending or queried domain for seamless funnel persistence
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const urlDomain = urlParams.get("domain");
      const sessionDomain = sessionStorage.getItem("inboundcheck_pending_domain");
      const localDomain = localStorage.getItem("inboundcheck_pending_domain");
      const resolved = urlDomain || sessionDomain || localDomain || "";
      if (resolved) {
        setTargetDomain(resolved.trim().toLowerCase());
      }
    } catch {
      // Suppress storage exceptions in private mode
    }
  }, []);

  const handleCheckout = async (planTier: string) => {
    setLoadingTier(planTier);
    setErrorMessage(null);
    try {
      if (onPlanSelected) {
        onPlanSelected(planTier);
      }

      const domainQuery = targetDomain ? `&domain=${encodeURIComponent(targetDomain)}` : "";
      const cycleQuery = `&cycle=${billingCycle}`;
      const successUrl = `${window.location.origin}/dashboard/billing?checkout=success&plan=${planTier}${cycleQuery}${domainQuery}`;
      const cancelUrl = `${window.location.origin}/dashboard/billing?checkout=cancelled${domainQuery}`;

      const res = await apiFetch("/api/v1/billing/checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_tier: planTier,
          price_id: planTier,
          billing_cycle: billingCycle,
          domain: targetDomain || undefined,
          success_url: successUrl,
          cancel_url: cancelUrl,
        }),
      });

      if (res.status === 401) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
        return;
      }

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const checkoutUrl = data.url || data.checkout_url;
        if (checkoutUrl) {
          window.location.href = checkoutUrl;
          return;
        }
      }
      setErrorMessage(data.detail || "Unable to initiate secure checkout. Please try again.");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Network communication error with secure checkout service.";
      setErrorMessage(message);
    } finally {
      setLoadingTier(null);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-title"
      className="fixed inset-0 z-50 overflow-y-auto bg-black/90 backdrop-blur-xl flex items-center justify-center p-4 sm:p-6 animate-fadeIn"
    >
      <div className="relative w-full max-w-5xl rounded-2xl bg-[#0A0A0C] border border-emerald-500/30 shadow-[0_0_60px_rgba(16,185,129,0.15)] p-6 sm:p-10 space-y-8 text-white my-8">
        {/* Subtle Ambient Radial Glow */}
        <div className="absolute -top-32 -right-32 w-80 h-80 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-32 -left-32 w-80 h-80 rounded-full bg-emerald-500/5 blur-3xl pointer-events-none" />

        {/* Modal Header: High-Impact GMV Protection & ROI Framing */}
        <div className="text-center space-y-3.5 max-w-2xl mx-auto relative z-10">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-mono font-bold uppercase tracking-wider shadow-[0_0_20px_rgba(16,185,129,0.2)]">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>37.3x Average GMV Protection ROI</span>
          </div>

          <h2 id="paywall-title" className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight text-white leading-tight">
            Protect Up to <span className="text-emerald-400 font-mono">$2,400/wk</span> in Silent Spam Revenue Loss
          </h2>
          
          <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed">
            {targetDomain ? (
              <>
                Unreceived order receipts on <span className="text-white font-mono font-semibold">{targetDomain}</span> cause customer dispute spikes and silent revenue leakage. Select an institutional tier to unlock continuous DNS governance and 1-click auto-patching.
              </>
            ) : (
              <>
                Your trial period has concluded. Select an institutional tier below to maintain continuous inbox placement, unblock 1-click DNS remediation, and protect your store GMV.
              </>
            )}
          </p>

          {/* Billing Cycle Toggle: Monthly vs Annual (20% Savings) */}
          <div className="pt-2 flex items-center justify-center gap-3">
            <span className={`text-xs font-medium ${billingCycle === "monthly" ? "text-white font-semibold" : "text-zinc-500"}`}>
              Monthly
            </span>
            <button
              type="button"
              onClick={() => setBillingCycle((prev) => (prev === "monthly" ? "annual" : "monthly"))}
              className="relative w-12 h-6 rounded-full bg-[#1A1A22] border border-white/10 transition-colors p-0.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              aria-label="Toggle annual or monthly billing"
            >
              <div
                className={`w-4.5 h-4.5 rounded-full bg-emerald-400 transition-transform duration-200 ${
                  billingCycle === "annual" ? "translate-x-6" : "translate-x-0.5"
                }`}
              />
            </button>
            <div className="flex items-center gap-1.5">
              <span className={`text-xs font-medium ${billingCycle === "annual" ? "text-white font-semibold" : "text-zinc-500"}`}>
                Annual
              </span>
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                SAVE 20%
              </span>
            </div>
          </div>

          {errorMessage && (
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs text-center font-mono">
              {errorMessage}
            </div>
          )}
        </div>

        {/* 3 Tier Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 relative z-10">
          {TIERS.map((tier) => {
            const isLoading = loadingTier === tier.id;
            const displayPrice = billingCycle === "annual" ? tier.annualPrice : tier.monthlyPrice;

            return (
              <div
                key={tier.id}
                className={`relative rounded-2xl flex flex-col justify-between p-6 sm:p-7 transition-all duration-300 ${
                  tier.isPopular
                    ? "bg-[#0E1217] border-2 border-emerald-500/70 shadow-[0_0_40px_rgba(16,185,129,0.25)] md:-translate-y-2"
                    : "bg-[#0A0A0C] border border-white/[0.08] hover:border-emerald-500/30"
                }`}
              >
                {tier.isPopular && (
                  <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-3.5 py-0.5 rounded-full bg-emerald-500 text-black font-extrabold text-[10px] uppercase tracking-wider flex items-center gap-1 shadow-[0_0_15px_rgba(16,185,129,0.5)]">
                    <Sparkles className="w-3 h-3 fill-current" />
                    <span>Most Popular</span>
                  </div>
                )}

                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-bold text-white tracking-tight">{tier.name}</h3>
                      <p className="text-xs text-zinc-400 mt-1 min-h-[32px] leading-relaxed">{tier.tagline}</p>
                    </div>
                  </div>

                  <div className="pt-2 pb-3 border-b border-white/[0.08]">
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight font-mono">
                        {displayPrice}
                      </span>
                      <span className="text-xs text-zinc-400 font-mono">{tier.period}</span>
                    </div>
                    {billingCycle === "annual" && (
                      <div className="text-[11px] font-mono text-emerald-400 mt-0.5 font-medium">
                        {tier.annualSavings}
                      </div>
                    )}
                    <span className="inline-block mt-2.5 text-[10px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/30">
                      {tier.domainLimit}
                    </span>
                  </div>

                  {/* Bullet list */}
                  <ul className="space-y-2.5 pt-1 text-xs text-zinc-300 font-sans">
                    {tier.features.map((feat, idx) => (
                      <li key={idx} className="flex items-start gap-2.5">
                        <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                        <span className="leading-snug">{feat}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Checkout Trigger Button */}
                <div className="pt-6 mt-6 border-t border-white/[0.08]">
                  <button
                    type="button"
                    disabled={Boolean(loadingTier)}
                    onClick={() => handleCheckout(tier.id)}
                    className={`w-full min-h-[44px] py-3 px-4 rounded-xl font-bold text-xs transition-all flex items-center justify-center gap-2 cursor-pointer active:scale-95 disabled:opacity-60 ${
                      tier.isPopular
                        ? "bg-emerald-500 hover:bg-emerald-400 text-black shadow-[0_0_20px_rgba(16,185,129,0.35)] hover:shadow-[0_0_25px_rgba(16,185,129,0.5)]"
                        : "bg-white/[0.08] hover:bg-white/[0.14] text-white border border-white/[0.1] hover:border-emerald-500/30"
                    }`}
                  >
                    {isLoading ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Connecting to Stripe...</span>
                      </>
                    ) : (
                      <>
                        <span>Activate {tier.name} Protection</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Enterprise Anchor Link */}
        <div className="text-center pt-2 relative z-10">
          <p className="text-xs text-zinc-400">
            Need 20+ stores, dedicated IP probing, or custom SLA?{" "}
            <a
              href="mailto:enterprise@inboundcheck.com?subject=Enterprise%20InboundCheck%20Inquiry"
              className="text-emerald-400 hover:text-emerald-300 font-semibold underline underline-offset-4 decoration-emerald-500/50 hover:decoration-emerald-400 transition-colors inline-flex items-center gap-1"
            >
              <Building2 className="w-3.5 h-3.5" />
              <span>Contact Enterprise Team</span>
            </a>
          </p>
        </div>

        {/* Security & Instant Activation Guarantee */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-6 pt-4 text-xs text-zinc-400 border-t border-white/[0.08] relative z-10">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>256-bit Encrypted Stripe Checkout</span>
          </div>
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-emerald-400" />
            <span>Instant Provisioning &amp; Live Domain Unlocking</span>
          </div>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors cursor-pointer"
            >
              Dismiss
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
