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
import { ApiError, formatApiErrorMessage } from "@/lib/apiResource";

interface SubscriptionInfo {
  tier: "starter" | "growth" | "enterprise" | string;
  subscription_status: string;
  has_stripe_customer: boolean;
  domain_count: number;
  domain_limit: number;
  current_period_end: string | null;
}

interface PlanTier {
  id: "starter" | "growth" | "agency" | "enterprise";
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
    price: "$9",
    period: "/ month",
    tagline: "Continuous DNS monitoring and instant failure alerts for single-store DTC brands.",
    domainLimitText: "1 Monitored Domain Cap",
    features: [
      "1 Monitored Domain",
      "24/7 Continuous DNS & 10-RBL Blacklist Radar",
      "Instant Telegram Failure Alerts",
      "3-Day Free Trial",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    price: "$29",
    period: "/ month",
    badge: "Most Popular",
    isPopular: true,
    tagline: "Multi-domain governance, automated DNS repair, and store order sync.",
    domainLimitText: "Up to 3 Monitored Domains",
    features: [
      "Up to 3 Monitored Domains",
      "Shopify Store OAuth Sync & Alignment",
      "1-Click DNS Auto-Remediation (Cloudflare & GoDaddy APIs)",
      "Revenue & Dispute Risk Analytics (Protected GMV / At-Risk GMV)",
      "3-Day Free Trial",
    ],
  },
  {
    id: "agency",
    name: "Agency",
    price: "$79",
    period: "/ month",
    badge: "High-Volume Scaling",
    tagline: "Expanded capacity and white-label reporting for agencies & high-volume merchants.",
    domainLimitText: "Up to 20 Monitored Domains",
    features: [
      "Up to 20 Monitored Domains",
      "Multi-Store Management",
      "Priority Audit Queue & White-Label Reporting Exports",
      "3-Day Free Trial",
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

  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [checkoutSuccessMessage, setCheckoutSuccessMessage] = useState<string | null>(null);

  // Clean URL params if returning from checkout with unescaped or mock template strings
  useEffect(() => {
    if (typeof window === "undefined") return;

    try {
      const url = new URL(window.location.href);
      const sessionId = url.searchParams.get("session_id");
      const upgraded = url.searchParams.get("upgraded");
      const checkoutStatus = url.searchParams.get("checkout");

      if (sessionId || upgraded || checkoutStatus) {
        if (sessionId && (sessionId.includes("{CHECKOUT_SESSION_ID}") || sessionId.includes("%7BCHECKOUT_SESSION_ID%7D"))) {
          console.warn("[CHECKOUT_CLEANUP] Detected unexpanded template session_id in URL, cleaning up query string...");
          url.searchParams.delete("session_id");
          window.history.replaceState({}, document.title, url.pathname + (url.search ? url.search : ""));
        } else if (upgraded || checkoutStatus === "success") {
          setCheckoutSuccessMessage(`Successfully updated subscription to ${upgraded ? upgraded.toUpperCase() : "the selected"} plan.`);
        }
      }
    } catch (e) {
      console.error("Failed to parse window URL params:", e);
    }
  }, []);

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
          message: err?.message || "Failed to load billing invoices",
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
    setCheckoutError(null);
    setCheckoutSuccessMessage(null);

    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const successUrl = `${origin}/dashboard/billing?session_id={CHECKOUT_SESSION_ID}&upgraded=${planTier}`;
    const cancelUrl = `${origin}/dashboard/billing`;

    try {
      const res = await apiFetch("/api/v1/billing/checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_tier: planTier,
          price_id: planTier,
          success_url: successUrl,
          cancel_url: cancelUrl,
        }),
      });

      // Extract response headers for deep diagnostic logging
      const responseHeaders: Record<string, string> = {};
      try {
        res.headers.forEach((val, key) => {
          responseHeaders[key] = val;
        });
      } catch {
        // Suppress headers iteration error
      }

      if (res.status === 401) {
        console.warn("[CHECKOUT_ERROR] User unauthorized for checkout session (HTTP 401). Redirecting to login...", {
          status: 401,
          headers: responseHeaders,
        });
        setCheckoutError("Your session has expired. Please sign in to upgrade your subscription.");
        if (typeof window !== "undefined") {
          window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
        }
        return;
      }

      let data: any = {};
      let rawText = "";
      try {
        rawText = await res.text();
        data = JSON.parse(rawText);
      } catch {
        data = { rawText };
      }

      if (!res.ok) {
        const errorObj = {
          status: res.status,
          statusText: res.statusText,
          headers: responseHeaders,
          body: data,
        };
        console.error("[CHECKOUT_ERROR]", errorObj);

        const errorMsg = formatApiErrorMessage(data.detail || data.message || data) || `Checkout initiation failed (HTTP ${res.status}: ${res.statusText || "Server Error"}).`;
        setCheckoutError(errorMsg);
        return;
      }

      // Successful checkout response
      const redirectUrl = data.url || data.checkout_url;
      if (redirectUrl) {
        // Defensive check: if redirect URL is an unexpanded template string returning to self, handle cleanly
        if (redirectUrl.includes("{CHECKOUT_SESSION_ID}") || redirectUrl.includes("%7BCHECKOUT_SESSION_ID%7D")) {
          console.warn("[CHECKOUT_WARNING] Backend returned unexpanded template redirect URL:", redirectUrl);
          const sanitizedUrl = redirectUrl.replace("{CHECKOUT_SESSION_ID}", "direct").replace("%7BCHECKOUT_SESSION_ID%7D", "direct");
          window.location.href = sanitizedUrl;
          return;
        }

        window.location.href = redirectUrl;
        return;
      }

      const emptyUrlError = "Stripe checkout session was created, but no checkout redirect URL was provided by the payment engine.";
      console.error("[CHECKOUT_ERROR]", {
        status: res.status,
        headers: responseHeaders,
        body: data,
        message: emptyUrlError,
      });
      setCheckoutError(emptyUrlError);
    } catch (err: any) {
      console.error("[CHECKOUT_ERROR] Unhandled exception in checkout initiation:", {
        message: err?.message || String(err),
        stack: err?.stack,
        error: err,
      });
      setCheckoutError(err?.message ? `Checkout error: ${err.message}` : "A network error occurred while connecting to the checkout service. Please verify your connection.");
    } finally {
      setLoadingTier(null);
    }
  };

  const handleOpenStripePortal = async () => {
    setIsLoadingPortal(true);
    setPortalNotice(null);
    setCheckoutError(null);
    try {
      const res = await apiFetch("/api/v1/billing/customer-portal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          return_url: `${window.location.origin}/dashboard/billing`,
        }),
      });

      if (res.status === 401) {
        console.warn("User unauthorized for customer portal. Redirecting to login...");
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
        return;
      }

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const portalUrl = data.url || data.portal_url;
        if (portalUrl && data.has_customer) {
          window.open(portalUrl, "_blank");
          return;
        } else if (data.message) {
          setPortalNotice(data.message);
          return;
        }
      }
      setPortalNotice("No active Stripe customer found. Select a plan below to activate your subscription.");
    } catch (portalErr) {
      console.error("[PORTAL_ERROR]", portalErr);
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
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2.5">
            <CreditCard className="w-5 h-5 text-emerald-600" />
            Subscription &amp; Usage
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Manage your merchant plan, monitored domain quotas, and Stripe customer portal settings.
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenStripePortal}
          disabled={isLoadingPortal}
          className="min-h-[44px] bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 font-semibold px-4 py-2 rounded-md shadow-2xs transition-all text-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50 font-mono"
        >
          {isLoadingPortal ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-600" />
          ) : (
            <ExternalLink className="w-3.5 h-3.5 text-emerald-600" />
          )}
          {isLoadingPortal ? "Opening Portal..." : "Manage Subscription"}
        </button>
      </div>

      {checkoutError && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl flex items-start gap-3 text-rose-800 text-xs font-mono animate-fadeIn shadow-2xs">
          <AlertCircle className="w-5 h-5 shrink-0 text-rose-600 mt-0.5" />
          <div className="space-y-1">
            <div className="font-bold text-rose-900">Unable to Initiate Checkout</div>
            <div className="leading-relaxed">{checkoutError}</div>
          </div>
        </div>
      )}

      {checkoutSuccessMessage && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center gap-3 text-emerald-800 text-xs font-mono animate-fadeIn shadow-2xs">
          <CheckCircle2 className="w-5 h-5 shrink-0 text-emerald-600" />
          <span>{checkoutSuccessMessage}</span>
        </div>
      )}

      {portalNotice && (
        <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl flex items-center gap-2 text-amber-800 text-xs font-mono shadow-2xs">
          <AlertCircle className="w-4 h-4 shrink-0 text-amber-600" />
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
            : currentTierNormalized === "agency"
            ? "$79.00 / mo"
            : currentTierNormalized === "growth"
            ? "$29.00 / mo"
            : "$9.00 / mo"
        }
        trendText={
          subInfo.current_period_end
            ? `Renews ${new Date(subInfo.current_period_end).toLocaleDateString()}`
            : "Active billing period"
        }
        icon={<Zap className="w-5 h-5 text-emerald-600" />}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs mt-4">
          {/* Quota Meter 1 */}
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-slate-600">Domain Quota</span>
              <span className="text-slate-900 font-bold">
                {subInfo.domain_count} / {subInfo.domain_limit >= 900 ? "Unlimited" : subInfo.domain_limit}
              </span>
            </div>
            <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
              <div
                className={`h-1.5 rounded-full transition-all duration-500 ${
                  quotaPercent >= 100 ? "bg-amber-500" : "bg-emerald-600"
                }`}
                style={{ width: `${quotaPercent}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-slate-500">
              <span>{quotaPercent}% consumed</span>
              <span className="text-emerald-700 font-semibold">
                {subInfo.domain_limit >= 900
                  ? "Unlimited slots"
                  : `${Math.max(0, subInfo.domain_limit - subInfo.domain_count)} slots left`}
              </span>
            </div>
          </div>

          {/* Meter 2 */}
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
            <span className="text-[10px] text-slate-500 uppercase font-semibold block">Audit Frequency</span>
            <span className="text-slate-900 font-bold block">
              {currentTierNormalized === "enterprise"
                ? "15-Minute Critical Sweeps"
                : currentTierNormalized === "agency"
                ? "30-Minute Priority Sweeps"
                : currentTierNormalized === "growth"
                ? "Hourly Automated Audits"
                : "Continuous DNS & RBL Radar"}
            </span>
            <span className="text-[10px] text-emerald-700 font-semibold block">Google & Yahoo 2024 Compliant</span>
          </div>

          {/* Meter 3 */}
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
            <span className="text-[10px] text-slate-500 uppercase font-semibold block">Incident Monitoring</span>
            <span className="text-slate-900 font-bold block">
              {currentTierNormalized === "starter" ? "Instant Telegram Alerts" : "Multi-Channel & Telegram Alerts"}
            </span>
            <span className="text-[10px] text-emerald-700 font-semibold block">Zero Transactional Receipt Loss</span>
          </div>
        </div>
      </GlassEmeraldCard>

      {/* 2. Three-Tier Subscription Matrix */}
      <div>
        <div className="mb-4">
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-600" />
            Available Subscription Tiers
          </h2>
          <p className="text-xs text-slate-500 font-mono">
            Upgrade or switch your tier anytime with immediate pro-rata billing reconciliation. All plans include a 3-day free trial.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {PLAN_TIERS.map((tier) => {
            const isCurrent = currentTierNormalized === tier.id;
            const tierOrder: Record<string, number> = { starter: 1, growth: 2, agency: 3, enterprise: 4 };
            const currentRank = tierOrder[currentTierNormalized] || 1;
            const targetRank = tierOrder[tier.id] || 1;
            const isUpgrade = targetRank > currentRank;

            return (
              <div
                key={tier.id}
                className={`relative rounded-xl p-5 font-mono flex flex-col justify-between transition-all duration-300 bg-white ${
                  isCurrent
                    ? "border-2 border-emerald-600 shadow-sm"
                    : tier.isPopular
                    ? "border-2 border-emerald-600 shadow-xs"
                    : "border border-slate-200 shadow-xs hover:border-slate-300"
                }`}
              >
                {tier.badge && (
                  <div className="absolute -top-2.5 right-4 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-600 text-white shadow-2xs">
                    {tier.badge}
                  </div>
                )}

                <div>
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-slate-900">{tier.name}</h3>
                    {isCurrent && (
                      <span className="text-[10px] uppercase font-bold text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                        Current Tier
                      </span>
                    )}
                  </div>

                  <div className="mt-3 flex items-baseline gap-1">
                    <span className="text-2xl font-black text-slate-950 font-mono">{tier.price}</span>
                    <span className="text-xs text-slate-500">{tier.period}</span>
                  </div>

                  <p className="text-[11px] text-slate-600 mt-2 min-h-[32px] leading-relaxed font-sans">
                    {tier.tagline}
                  </p>

                  <div className="mt-4 pt-4 border-t border-slate-200 space-y-2 text-xs">
                    <div className="text-[11px] font-bold text-emerald-700 flex items-center gap-1.5">
                      <Globe className="w-3.5 h-3.5 text-emerald-600" />
                      {tier.domainLimitText}
                    </div>

                    <ul className="space-y-2 mt-3 text-[11px] text-slate-600 font-sans">
                      {tier.features.map((feature, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <Check className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-0.5" />
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-200">
                  {isCurrent ? (
                    <button
                      type="button"
                      disabled
                      className="w-full py-2.5 px-4 rounded-md text-xs font-bold text-emerald-800 bg-emerald-50 border border-emerald-200 cursor-default flex items-center justify-center gap-1.5"
                    >
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      Active Tier
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleCheckout(tier.id)}
                      disabled={loadingTier !== null}
                      className={`w-full py-2.5 px-4 rounded-md text-xs font-semibold flex items-center justify-center gap-1.5 transition cursor-pointer disabled:opacity-50 shadow-xs ${
                        tier.isPopular || isUpgrade
                          ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                          : "bg-white hover:bg-slate-50 text-slate-700 border border-slate-300"
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
        subtitle="Bank-grade encrypted billing synchronized directly with Stripe"
        badgeText="Webhook Active"
        badgeVariant="emerald"
        icon={<Clock className="w-5 h-5 text-emerald-600" />}
      >
        <div className="p-4 bg-slate-50 rounded-lg border border-slate-200 space-y-3 font-mono text-xs text-slate-700">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-slate-500 font-semibold">Webhook Endpoint Status:</span>
            <span className="text-emerald-800 font-semibold flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              Instant real-time payment confirmation and invoice synchronization
            </span>
          </div>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-slate-500 font-semibold">Payment Processing Engine:</span>
            <span className="text-slate-900 font-semibold">Stripe Subscriptions & Customer Portal (Direct API Integration)</span>
          </div>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-slate-500 font-semibold">Need Custom Invoice or Enterprise Wire?</span>
            <button
              type="button"
              onClick={handleOpenStripePortal}
              className="text-emerald-700 hover:text-emerald-800 underline font-semibold cursor-pointer text-xs"
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
        icon={<Clock className="w-5 h-5 text-emerald-600" />}
      >
        {isLoadingInvoices ? (
          <div className="py-12 flex flex-col items-center justify-center gap-2 font-mono text-xs text-slate-500">
            <RefreshCw className="w-5 h-5 animate-spin text-emerald-600" />
            <span>Retrieving live Stripe invoices...</span>
          </div>
        ) : invoiceError ? (
          <OperationalErrorCard
            title="Invoice History Temporarily Unavailable"
            error={invoiceError}
            compact
          />
        ) : invoices.length === 0 ? (
          <div className="text-center py-10 px-4 bg-slate-50 rounded-lg border border-slate-200 space-y-2 font-mono">
            <Clock className="w-6 h-6 text-slate-400 mx-auto" />
            <div className="text-xs text-slate-800 font-bold">No Invoices Generated Yet</div>
            <div className="text-[11px] text-slate-500 max-w-sm mx-auto">
              Official PDF invoices and payment receipts will populate here automatically once your subscription billing cycle completes.
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-slate-200 bg-white shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono border-collapse">
                <thead className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono uppercase tracking-wider text-slate-500 font-semibold">
                  <tr>
                    <th className="py-3 px-4 font-semibold text-left">Invoice Number</th>
                    <th className="py-3 px-4 font-semibold text-left">Billing Period</th>
                    <th className="py-3 px-4 font-semibold text-right">Amount</th>
                    <th className="py-3 px-4 font-semibold text-left">Status</th>
                    <th className="py-3 px-4 font-semibold text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {invoices.map((inv) => (
                    <tr key={inv.id} className="hover:bg-slate-50/70 transition-colors">
                      <td className="py-3.5 px-4 text-xs font-mono font-bold text-slate-900">{inv.invoice_number}</td>
                      <td className="py-3.5 px-4 text-xs font-mono text-slate-500">{inv.billing_period}</td>
                      <td className="py-3.5 px-4 text-xs font-mono font-bold text-slate-900 text-right tabular-nums">{inv.amount}</td>
                      <td className="py-3.5 px-4 text-xs font-mono">
                        <span className="text-[10px] font-mono font-semibold uppercase px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 inline-flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          {inv.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-xs font-mono text-right">
                        {inv.pdf_url && inv.pdf_url !== "#" ? (
                          <a
                            href={inv.pdf_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="px-3 py-1.5 bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 rounded-md text-xs font-semibold inline-flex items-center gap-1.5 transition cursor-pointer shadow-2xs"
                          >
                            <Download className="w-3 h-3 text-emerald-600" />
                            View PDF
                          </a>
                        ) : (
                          <span className="text-slate-400 text-xs font-mono">Processing</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </GlassEmeraldCard>
    </div>
  );
}
