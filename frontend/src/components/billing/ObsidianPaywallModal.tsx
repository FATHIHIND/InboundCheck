"use client";

import React, { useState } from "react";
import { Check, Sparkles, ShieldAlert, ArrowRight, Loader2, Zap, ShieldCheck } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface ObsidianPaywallModalProps {
  onPlanSelected?: (planTier: string) => void;
}

interface TierDefinition {
  id: "starter" | "growth" | "enterprise";
  name: string;
  price: string;
  period: string;
  tagline: string;
  domainLimit: string;
  isPopular?: boolean;
  features: string[];
}

const TIERS: TierDefinition[] = [
  {
    id: "starter",
    name: "Starter",
    price: "$29",
    period: "/mo",
    tagline: "Essential deliverability surveillance for single-store DTC brands.",
    domainLimit: "1 Monitored Domain Cap",
    features: [
      "1 Monitored Apex Domain Cap",
      "Manual DNS Record Snippets",
      "Basic Telegram Bot Alerts",
      "Daily Multi-Resolver Diagnostics",
      "Weekly Health Summary",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    price: "$79",
    period: "/mo",
    tagline: "High-precision governance for expanding DTC brands & multi-brand setups.",
    domainLimit: "3 Monitored Domains Cap",
    isPopular: true,
    features: [
      "3 Monitored Apex Domains Cap",
      "RFC 7208 SPF Merge Engine (10-Lookup Cap)",
      "1-Click DNS Auto-Fix (Cloudflare / GoDaddy)",
      "48-72h Predictive Risk Forecast",
      "Real-Time Multi-channel Failover Alerts",
      "10 Authoritative Blacklist Radar Scanners",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "$199",
    period: "/mo",
    tagline: "Mission-critical deliverability SLA for enterprise DTC conglomerates.",
    domainLimit: "Unlimited Domains",
    features: [
      "Unlimited Monitored Apex Domains",
      "Developer API Keys & Custom Webhooks",
      "Real-Time Worker Priority & 15m Sweeps",
      "AI Content Lab & Cryptographic Optimizer",
      "Dedicated Deliverability Architect SLA",
      "Custom Return-Path & BIMI Certification",
    ],
  },
];

export function ObsidianPaywallModal({ onPlanSelected }: ObsidianPaywallModalProps) {
  const [loadingTier, setLoadingTier] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleCheckout = async (planTier: string) => {
    setLoadingTier(planTier);
    setErrorMessage(null);
    try {
      if (onPlanSelected) {
        onPlanSelected(planTier);
      }
      const res = await apiFetch("/api/v1/billing/create-checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_tier: planTier,
          price_id: planTier,
          success_url: `${window.location.origin}/dashboard/billing?checkout=success&plan=${planTier}`,
          cancel_url: `${window.location.origin}/dashboard/billing?checkout=cancelled`,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
          return;
        }
      }
      const errData = await res.json().catch(() => ({}));
      setErrorMessage(errData.detail || "Unable to initiate Stripe checkout. Please try again.");
    } catch (err: any) {
      setErrorMessage(err?.message || "Network communication error with Stripe checkout service.");
    } finally {
      setLoadingTier(null);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-title"
      className="fixed inset-0 z-50 overflow-y-auto bg-black/90 backdrop-blur-xl flex items-center justify-center p-4 sm:p-6"
    >
      <div className="relative w-full max-w-5xl rounded-2xl bg-[#09090C] border border-emerald-500/30 shadow-[0_0_50px_rgba(16,185,129,0.15)] p-6 sm:p-10 space-y-8 text-white my-8">
        {/* Modal Header */}
        <div className="text-center space-y-3 max-w-2xl mx-auto">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-mono uppercase tracking-wider">
            <ShieldAlert size={14} className="text-red-400" />
            <span>3-Day Free Trial Expired</span>
          </div>

          <h2 id="paywall-title" className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
            Choose a Plan to Maintain Continuous Inbox Protection
          </h2>
          <p className="text-sm text-zinc-400">
            Your 3-day trial period has ended. Select an enterprise subscription tier below to re-enable live DNS governance, SPF consolidation, blacklist radar, and Shopify webhook failover.
          </p>

          {errorMessage && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs text-center font-mono">
              {errorMessage}
            </div>
          )}
        </div>

        {/* 3 Tier Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TIERS.map((tier) => {
            const isLoading = loadingTier === tier.id;
            return (
              <div
                key={tier.id}
                className={`relative rounded-xl flex flex-col justify-between p-6 transition-all duration-200 ${
                  tier.isPopular
                    ? "bg-[#0E1713] border-2 border-emerald-500/60 shadow-[0_0_30px_rgba(16,185,129,0.2)]"
                    : "bg-[#0E0E12] border border-white/[0.08] hover:border-white/[0.15]"
                }`}
              >
                {tier.isPopular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-emerald-500 text-black font-bold text-[11px] uppercase tracking-wider flex items-center gap-1 shadow-[0_0_12px_rgba(16,185,129,0.4)]">
                    <Sparkles size={12} />
                    <span>Most Popular</span>
                  </div>
                )}

                <div className="space-y-4">
                  <div>
                    <h3 className="text-lg font-bold text-white tracking-tight">{tier.name}</h3>
                    <p className="text-xs text-zinc-400 mt-1 min-h-[32px]">{tier.tagline}</p>
                  </div>

                  <div className="pt-2 pb-1 border-b border-white/[0.08]">
                    <div className="flex items-baseline gap-1">
                      <span className="text-3xl font-extrabold text-white tracking-tight font-mono">
                        {tier.price}
                      </span>
                      <span className="text-xs text-zinc-400 font-mono">{tier.period}</span>
                    </div>
                    <span className="inline-block mt-2 text-[11px] font-mono font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                      {tier.domainLimit}
                    </span>
                  </div>

                  {/* Bullet list */}
                  <ul className="space-y-2.5 pt-2 text-xs text-zinc-300 font-sans">
                    {tier.features.map((feat, idx) => (
                      <li key={idx} className="flex items-start gap-2">
                        <Check size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                        <span>{feat}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Checkout Trigger */}
                <div className="pt-6 mt-4 border-t border-white/[0.08]">
                  <button
                    type="button"
                    disabled={Boolean(loadingTier)}
                    onClick={() => handleCheckout(tier.id)}
                    className={`w-full py-2.5 px-4 rounded-lg font-semibold text-xs transition-all flex items-center justify-center gap-2 cursor-pointer ${
                      tier.isPopular
                        ? "bg-emerald-500 hover:bg-emerald-400 text-black shadow-[0_0_15px_rgba(16,185,129,0.35)] hover:shadow-[0_0_22px_rgba(16,185,129,0.5)]"
                        : "bg-white/[0.08] hover:bg-white/[0.14] text-white border border-white/[0.1]"
                    }`}
                  >
                    {isLoading ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        <span>Redirecting to Stripe...</span>
                      </>
                    ) : (
                      <>
                        <span>Activate {tier.name}</span>
                        <ArrowRight size={13} />
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Security / Guarantee Badge */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-6 pt-4 text-xs text-zinc-400 border-t border-white/[0.08]">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} className="text-emerald-400" />
            <span>256-bit Encrypted Stripe Checkout</span>
          </div>
          <div className="flex items-center gap-2">
            <Zap size={16} className="text-emerald-400" />
            <span>Instant Provisioning & Domain Unlocking</span>
          </div>
        </div>
      </div>
    </div>
  );
}
