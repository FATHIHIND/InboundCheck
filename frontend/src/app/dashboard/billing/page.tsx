"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import {
  CreditCard,
  ShieldCheck,
  CheckCircle2,
  ExternalLink,
  Download,
  Activity,
  Layers,
  Zap,
  Globe,
  RefreshCw,
  Clock,
  Sparkles,
  ArrowUpRight,
  AlertCircle,
  Check,
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { OperationalErrorCard } from "@/components/operational/OperationalErrorCard";
import { ApiError } from "@/lib/apiResource";

interface SubscriptionInfo {
  tier: "starter" | "growth" | "enterprise" | string;
  subscription_status: string;
  has_stripe_customer: boolean;
  domain_count: number;
  domain_limit: number;
  current_period_end: string | null;
}

interface PlanTier {
  id: "starter" | "growth" | "enterprise";
  name: string;
  price: string;
  period: string;
  badge?: string;
  isPopular?: boolean;
  tagline: string;
  domainLimitText: string;
  features: string[];
}

const PLAN_TIERS: PlanTier[] = [
  {
    id: "starter",
    name: "Starter",
    price: "$29",
    period: "/ month",
    tagline: "Essential deliverability surveillance for single-store DTC brands.",
    domainLimitText: "1 Monitored Apex Domain",
    features: [
      "1 Monitored Apex Domain",
      "Real-Time SPF / DKIM / DMARC Scorer",
      "Daily Multi-Resolver Health Probes",
      "1-Click DNS Fix Snippets",
      "Weekly Email Deliverability Digest",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    price: "$79",
    period: "/ month",
    badge: "Most Popular",
    isPopular: true,
    tagline: "High-precision governance for expanding DTC merchants & multi-brand setups.",
    domainLimitText: "5 Monitored Apex Domains",
    features: [
      "Up to 5 Monitored Apex Domains",
      "Hourly Multi-Resolver Diagnostic Audits",
      "10 Authoritative RBL Blacklist Probes",
      "Real-Time Telegram Bot Alert Engine",
      "1-Click Cloudflare & GoDaddy DNS Fixer",
      "Omnichannel Fallback Failover Routing",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "$199",
    period: "/ month",
    badge: "Maximum Governance",
    tagline: "Uncompromised deliverability SLA for enterprise brands & DTC conglomerates.",
    domainLimitText: "Unlimited Monitored Domains",
    features: [
      "Unlimited Monitored Apex Domains",
      "15-Minute Critical Deliverability Sweeps",
      "AI Content Lab & Cryptographic Optimizer",
      "Dedicated Deliverability Architect Review",
      "Custom Webhooks & REST API Access",
      "99.9% Transactional Delivery SLA",
    ],
  },
];

interface InvoiceItem {
  id: string;
  invoice_number: string;
  billing_period: string;
  amount: string;
  status: string;
  pdf_url: string;
  created_at?: number;
}

export default function BillingPortalPage() {
  const [subInfo, setSubInfo] = useState<SubscriptionInfo>({
    tier: "starter",
    subscription_status: "active",
    has_stripe_customer: false,
    domain_count: 0,
    domain_limit: 1,
    current_period_end: null,
  });
  const [invoices, setInvoices] = useState<InvoiceItem[]>([]);
  const [isLoadingInvoices, setIsLoadingInvoices] = useState(true);
  const [invoiceError, setInvoiceError] = useState<ApiError | null>(null);
  const [isLoadingSub, setIsLoadingSub] = useState(true);
  const [loadingTier, setLoadingTier] = useState<string | null>(null);
  const [isLoadingPortal, setIsLoadingPortal] = useState(false);
  const [portalNotice, setPortalNotice] = useState<string | null>(null);

  useEffect(() => {
    async function loadSubscription() {
      try {
        const res = await apiFetch("/api/v1/billing/subscription");
        if (res.ok) {
          const data = await res.json();
          setSubInfo({
            tier: data.tier || "starter",
            subscription_status: data.subscription_status || "active",
            has_stripe_customer: Boolean(data.has_stripe_customer),
            domain_count: data.domain_count || 0,
            domain_limit: data.domain_limit || 1,
            current_period_end: data.current_period_end || null,
          });
        }
      } catch (err) {
        console.error("Failed to load subscription info:", err);
      } finally {
        setIsLoadingSub(false);
      }
    }

    async function loadInvoices() {
      setIsLoadingInvoices(true);
      setInvoiceError(null);
      try {
        const res = await apiFetch("/api/v1/billing/invoices");
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data.invoices)) {
            setInvoices(data.invoices);
          }
        } else {
          const body = await res.json().catch(() => ({}));
          setInvoiceError({
            message: body.detail || "Unable to retrieve Stripe invoice history",
            status: res.status,
            retryable: true,
            endpoint: "/api/v1/billing/invoices",
          });
        }
      } catch (err: any) {
        setInvoiceError({
          message: err?.message || "Failed to reach Stripe billing telemetry service",
          retryable: true,
          endpoint: "/api/v1/billing/invoices",
        });
      } finally {
        setIsLoadingInvoices(false);
      }
    }

    loadSubscription();
    loadInvoices();
  }, []);

  const handleCheckout = async (planTier: string) => {
    setLoadingTier(planTier);
    setPortalNotice(null);
    try {
      const res = await apiFetch("/api/v1/billing/checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_tier: planTier,
          success_url: `${window.location.origin}/dashboard/billing?session_id={CHECKOUT_SESSION_ID}&upgraded=${planTier}`,
          cancel_url: `${window.location.origin}/dashboard/billing`,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
          return;
        }
      }
      setPortalNotice("Could not initiate Stripe checkout session. Please check your credentials.");
    } catch (err) {
      setPortalNotice("Network exception initiating checkout session.");
    } finally {
      setLoadingTier(null);
    }
  };

  const handleOpenStripePortal = async () => {
    setIsLoadingPortal(true);
    setPortalNotice(null);
    try {
      const res = await apiFetch("/api/v1/billing/customer-portal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          return_url: `${window.location.origin}/dashboard/billing`,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.portal_url && data.has_customer) {
          window.open(data.portal_url, "_blank");
          return;
        } else if (data.message) {
          setPortalNotice(data.message);
          return;
        }
      }
      setPortalNotice("No active Stripe customer found. Select a plan below to activate your subscription.");
    } catch {
      setPortalNotice("Failed to reach billing portal service.");
    } finally {
      setIsLoadingPortal(false);
    }
  };

  const currentTierNormalized = (subInfo.tier || "starter").toLowerCase();
  const quotaPercent = Math.min(100, Math.round((subInfo.domain_count / Math.max(1, subInfo.domain_limit)) * 100));

  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-fadeIn pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <CreditCard className="w-5 h-5 text-emerald-400" />
            Stripe Billing & Subscription Governance
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5 font-mono">
            Manage your merchant tier, sending domain quotas, and Stripe customer portal settings.
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenStripePortal}
          disabled={isLoadingPortal}
          className="bg-[#14141A] hover:bg-[#1E1E26] border border-emerald-500/30 text-emerald-400 font-semibold px-4 py-2 rounded-lg shadow-sm transition-all text-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50 font-mono"
        >
          {isLoadingPortal ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-400" />
          ) : (
            <ExternalLink className="w-3.5 h-3.5 text-emerald-400" />
          )}
          {isLoadingPortal ? "Opening Portal..." : "Manage Billing & Tax Invoices"}
        </button>
      </div>

      {portalNotice && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center gap-2 text-amber-300 text-xs font-mono">
          <AlertCircle className="w-4 h-4 shrink-0 text-amber-400" />
          <span>{portalNotice}</span>
        </div>
      )}

      {/* 1. Current Active Tier & Usage Overview */}
      <GlassEmeraldCard
        title={`${currentTierNormalized.toUpperCase()} PLAN — ACTIVE`}
        subtitle="Live multi-tenant deliverability governance and DNS surveillance subscription"
        badgeText={subInfo.subscription_status.toUpperCase()}
        badgeVariant="emerald"
        metricValue={
          currentTierNormalized === "enterprise"
            ? "$199.00 / mo"
            : currentTierNormalized === "growth"
            ? "$79.00 / mo"
            : "$29.00 / mo"
        }
        trendText={
          subInfo.current_period_end
            ? `Renews ${new Date(subInfo.current_period_end).toLocaleDateString()}`
            : "Active billing period"
        }
        icon={<Zap className="w-5 h-5 text-emerald-400" />}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs mt-4">
          {/* Quota Meter 1 */}
          <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-zinc-400">Domain Quota</span>
              <span className="text-white font-bold">
                {subInfo.domain_count} / {subInfo.domain_limit >= 900 ? "Unlimited" : subInfo.domain_limit}
              </span>
            </div>
            <div className="w-full bg-[#14141A] rounded-full h-1.5 overflow-hidden border border-white/[0.04]">
              <div
                className={`h-1.5 rounded-full transition-all duration-500 ${
                  quotaPercent >= 100 ? "bg-amber-400" : "bg-emerald-500"
                }`}
                style={{ width: `${quotaPercent}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-zinc-500">
              <span>{quotaPercent}% consumed</span>
              <span className="text-emerald-400">
                {subInfo.domain_limit >= 900
                  ? "Unlimited slots"
                  : `${Math.max(0, subInfo.domain_limit - subInfo.domain_count)} slots left`}
              </span>
            </div>
          </div>

          {/* Meter 2 */}
          <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-1">
            <span className="text-[10px] text-zinc-500 uppercase block">Audit Frequency</span>
            <span className="text-white font-bold block">
              {currentTierNormalized === "enterprise"
                ? "15-Minute Critical Sweeps"
                : currentTierNormalized === "growth"
                ? "Hourly Automated Audits"
                : "Daily Proactive Audits"}
            </span>
            <span className="text-[10px] text-emerald-400 block">RFC 1035 & Google/Yahoo 2024</span>
          </div>

          {/* Meter 3 */}
          <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-1">
            <span className="text-[10px] text-zinc-500 uppercase block">Failover Protection</span>
            <span className="text-white font-bold block">
              {currentTierNormalized === "starter" ? "Standard Alerts" : "Omnichannel WhatsApp / SMS"}
            </span>
            <span className="text-[10px] text-emerald-400 block">Zero Transactional Receipt Loss</span>
          </div>
        </div>
      </GlassEmeraldCard>

      {/* 2. Three-Tier Subscription Matrix */}
      <div>
        <div className="mb-4">
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-400" />
            Available Subscription Tiers
          </h2>
          <p className="text-xs text-zinc-400 font-mono">
            Upgrade or switch your tier anytime with immediate pro-rata billing reconciliation.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {PLAN_TIERS.map((tier) => {
            const isCurrent = currentTierNormalized === tier.id;
            const isUpgrade =
              (currentTierNormalized === "starter" && (tier.id === "growth" || tier.id === "enterprise")) ||
              (currentTierNormalized === "growth" && tier.id === "enterprise");

            return (
              <div
                key={tier.id}
                className={`relative rounded-2xl p-5 font-mono flex flex-col justify-between transition-all duration-300 ${
                  isCurrent
                    ? "bg-[#0A100D] border-2 border-emerald-500 shadow-[0_0_25px_rgba(16,185,129,0.15)]"
                    : tier.isPopular
                    ? "bg-[#0C0D12] border border-emerald-500/40 hover:border-emerald-500/70"
                    : "bg-[#0C0D12] border border-white/[0.06] hover:border-white/[0.15]"
                }`}
              >
                {tier.badge && (
                  <div className="absolute -top-2.5 right-4 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-500 text-zinc-950 shadow-sm">
                    {tier.badge}
                  </div>
                )}

                <div>
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-white">{tier.name}</h3>
                    {isCurrent && (
                      <span className="text-[10px] uppercase font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                        Current Tier
                      </span>
                    )}
                  </div>

                  <div className="mt-3 flex items-baseline gap-1">
                    <span className="text-2xl font-black text-white">{tier.price}</span>
                    <span className="text-xs text-zinc-400">{tier.period}</span>
                  </div>

                  <p className="text-[11px] text-zinc-400 mt-2 min-h-[32px] leading-relaxed">
                    {tier.tagline}
                  </p>

                  <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-2 text-xs">
                    <div className="text-[11px] font-bold text-emerald-400 flex items-center gap-1.5">
                      <Globe className="w-3.5 h-3.5" />
                      {tier.domainLimitText}
                    </div>

                    <ul className="space-y-2 mt-3 text-[11px] text-zinc-300">
                      {tier.features.map((feature, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-white/[0.04]">
                  {isCurrent ? (
                    <button
                      type="button"
                      disabled
                      className="w-full py-2.5 px-4 rounded-xl text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 cursor-default flex items-center justify-center gap-1.5"
                    >
                      <CheckCircle2 className="w-4 h-4" />
                      Active Tier
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleCheckout(tier.id)}
                      disabled={loadingTier !== null}
                      className={`w-full py-2.5 px-4 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition cursor-pointer disabled:opacity-50 ${
                        tier.isPopular || isUpgrade
                          ? "bg-emerald-500 hover:bg-emerald-400 text-zinc-950 shadow-md shadow-emerald-500/20"
                          : "bg-[#14141A] hover:bg-[#1E1E26] text-white border border-white/[0.08]"
                      }`}
                    >
                      {loadingTier === tier.id ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          Initiating Stripe...
                        </>
                      ) : (
                        <>
                          {isUpgrade ? `Upgrade to ${tier.name}` : `Switch to ${tier.name}`}
                          <ArrowUpRight className="w-3.5 h-3.5" />
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. Reconciled Receipts & Invoicing Info */}
      <GlassEmeraldCard
        title="Automated Stripe Webhook Reconciliation"
        subtitle="Cryptographically verified via timestamped HMAC-SHA256 signatures with 24h idempotency deduplication"
        badgeText="Webhook Active"
        badgeVariant="emerald"
        icon={<Clock className="w-5 h-5 text-emerald-400" />}
      >
        <div className="p-4 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-3 font-mono text-xs text-zinc-300">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-zinc-400">Webhook Endpoint Status:</span>
            <span className="text-emerald-400 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Listening on /api/v1/billing/webhook (±300s replay tolerance)
            </span>
          </div>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-zinc-400">Payment Processing Engine:</span>
            <span className="text-white">Stripe Subscriptions & Customer Portal (Direct API Integration)</span>
          </div>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-zinc-400">Need Custom Invoice or Enterprise Wire?</span>
            <button
              type="button"
              onClick={handleOpenStripePortal}
              className="text-emerald-400 hover:text-emerald-300 underline cursor-pointer text-xs"
            >
              Open Customer Portal for PDF Receipts & VAT Details &rarr;
            </button>
          </div>
        </div>
      </GlassEmeraldCard>

      {/* 4. Live Tax Invoices & Payment History */}
      <GlassEmeraldCard
        title="Tax Invoices & Payment History"
        subtitle="Cryptographically verified Stripe payment receipts with downloadable PDF statements"
        badgeText={`${invoices.length} Invoices`}
        badgeVariant="emerald"
        icon={<Clock className="w-5 h-5 text-emerald-400" />}
      >
        {isLoadingInvoices ? (
          <div className="py-12 flex flex-col items-center justify-center gap-2 font-mono text-xs text-zinc-400">
            <RefreshCw className="w-5 h-5 animate-spin text-emerald-400" />
            <span>Retrieving live Stripe invoices...</span>
          </div>
        ) : invoiceError ? (
          <OperationalErrorCard
            title="Stripe Invoice Telemetry Unavailable"
            error={invoiceError}
            compact
          />
        ) : invoices.length === 0 ? (
          <div className="text-center py-10 px-4 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-2 font-mono">
            <Clock className="w-6 h-6 text-zinc-600 mx-auto" />
            <div className="text-xs text-zinc-300 font-bold">No Invoices Generated Yet</div>
            <div className="text-[11px] text-zinc-500 max-w-sm mx-auto">
              Official PDF invoices and payment receipts will populate here automatically once your subscription billing cycle completes.
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-zinc-500 border-b border-white/[0.04] text-[10px] uppercase bg-[#08080A]">
                <tr>
                  <th className="px-5 py-3.5 font-semibold">Invoice Number</th>
                  <th className="px-5 py-3.5 font-semibold">Billing Period</th>
                  <th className="px-5 py-3.5 font-semibold">Amount</th>
                  <th className="px-5 py-3.5 font-semibold">Status</th>
                  <th className="px-5 py-3.5 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04] text-zinc-300">
                {invoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-white/[0.01] transition">
                    <td className="px-5 py-4 font-bold text-white">{inv.invoice_number}</td>
                    <td className="px-5 py-4 text-zinc-400">{inv.billing_period}</td>
                    <td className="px-5 py-4 font-bold text-white">{inv.amount}</td>
                    <td className="px-5 py-4">
                      <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" />
                        {inv.status.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-right">
                      {inv.pdf_url && inv.pdf_url !== "#" ? (
                        <a
                          href={inv.pdf_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="px-3 py-1.5 bg-[#14141A] hover:bg-[#1E1E26] border border-white/[0.08] text-zinc-200 hover:text-white rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition cursor-pointer"
                        >
                          <Download className="w-3 h-3 text-emerald-400" />
                          View PDF
                        </a>
                      ) : (
                        <span className="text-zinc-600 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassEmeraldCard>
    </div>
  );
}
