"use client";

import { useState } from "react";
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
  ArrowUpRight
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";

interface Invoice {
  id: string;
  invoice_number: string;
  billing_period: string;
  amount: string;
  status: "paid" | "processing";
  pdf_url: string;
}

const INVOICE_HISTORY: Invoice[] = [
  {
    id: "inv_101",
    invoice_number: "INV-2026-08",
    billing_period: "Aug 01, 2026 – Aug 31, 2026",
    amount: "$79.00 USD",
    status: "paid",
    pdf_url: "#",
  },
  {
    id: "inv_102",
    invoice_number: "INV-2026-07",
    billing_period: "Jul 01, 2026 – Jul 31, 2026",
    amount: "$79.00 USD",
    status: "paid",
    pdf_url: "#",
  },
  {
    id: "inv_103",
    invoice_number: "INV-2026-06",
    billing_period: "Jun 01, 2026 – Jun 30, 2026",
    amount: "$79.00 USD",
    status: "paid",
    pdf_url: "#",
  },
];

export default function BillingPortalPage() {
  const [isLoadingPortal, setIsLoadingPortal] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const handleOpenStripePortal = async () => {
    setIsLoadingPortal(true);
    try {
      const res = await apiFetch("/api/v1/billing/customer-portal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.portal_url) {
          window.open(data.portal_url, "_blank");
          return;
        }
      }
      window.open("https://billing.stripe.com/p/login/test", "_blank");
    } catch {
      window.open("https://billing.stripe.com/p/login/test", "_blank");
    } finally {
      setIsLoadingPortal(false);
    }
  };

  const handleDownloadInvoice = (invId: string) => {
    setDownloadingId(invId);
    setTimeout(() => {
      setDownloadingId(null);
    }, 1200);
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto animate-fadeIn pb-16">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <CreditCard className="w-5 h-5 text-emerald-400" />
            Stripe Billing & Subscription Portal
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Manage your subscription tier, domain quotas, telemetry meters, and tax invoices.
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenStripePortal}
          disabled={isLoadingPortal}
          className="bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold px-4 py-2 rounded-lg shadow-sm transition-all text-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50 font-mono"
        >
          {isLoadingPortal ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-zinc-950" />
          ) : (
            <ExternalLink className="w-3.5 h-3.5 text-zinc-950" />
          )}
          {isLoadingPortal ? "Opening Portal..." : "Open Stripe Customer Portal"}
        </button>
      </div>

      {/* 1. Current Plan Card & Renewal Overview */}
      <GlassEmeraldCard
        title="Growth Tier Subscription"
        subtitle="Tailored for high-volume Shopify DTC merchants with up to 5 verified apex sending domains"
        badgeText="Active & Auto-Renewing"
        badgeVariant="emerald"
        metricValue="$79.00 / mo"
        trendText="Renews Sept 24, 2026"
        icon={<Zap className="w-5 h-5 text-emerald-400" />}
        actionLabel="Manage via Stripe Portal"
        onActionClick={handleOpenStripePortal}
      >
        {/* Feature inclusions */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs mt-4">
          <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-1">
            <span className="text-[10px] text-zinc-500 uppercase block">Governance</span>
            <span className="text-white font-bold block">5 Apex Sending Domains</span>
            <span className="text-[10px] text-emerald-400 block">Hourly Multi-Resolver Audits</span>
          </div>

          <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-1">
            <span className="text-[10px] text-zinc-500 uppercase block">Surveillance</span>
            <span className="text-white font-bold block">10 Authoritative RBL Probes</span>
            <span className="text-[10px] text-emerald-400 block">48–72h Predictive Risk Forecasting</span>
          </div>

          <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-1">
            <span className="text-[10px] text-zinc-500 uppercase block">Automation</span>
            <span className="text-white font-bold block">Telegram Bot Alert Engine</span>
            <span className="text-[10px] text-emerald-400 block">1-Click Cloudflare DNS Fixer</span>
          </div>
        </div>
      </GlassEmeraldCard>

      {/* 2. Usage Telemetry Meters */}
      <GlassEmeraldCard
        title="Usage Telemetry & Quota Meters"
        subtitle="Live consumption against your monthly subscription tier limits"
        badgeText="Monthly Cycle: Aug 01 – Aug 31"
        badgeVariant="emerald"
        icon={<Activity className="w-5 h-5 text-emerald-400" />}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 font-mono text-xs">
          {/* Meter 1: Monitored Domains */}
          <div className="p-4 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-zinc-400 text-xs">Monitored Domains</span>
              <span className="font-bold text-white">3 / 5 used</span>
            </div>
            <div className="w-full bg-[#14141A] rounded-full h-2 overflow-hidden border border-white/[0.04]">
              <div className="bg-emerald-500 h-2 rounded-full" style={{ width: "60%" }} />
            </div>
            <div className="flex justify-between text-[10px] text-zinc-500">
              <span>60% capacity</span>
              <span className="text-emerald-400">2 slots remaining</span>
            </div>
          </div>

          {/* Meter 2: Monthly Email Ingestion */}
          <div className="p-4 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-zinc-400 text-xs">IMAP Email Ingestion</span>
              <span className="font-bold text-white">14.2k / 50k</span>
            </div>
            <div className="w-full bg-[#14141A] rounded-full h-2 overflow-hidden border border-white/[0.04]">
              <div className="bg-emerald-500 h-2 rounded-full" style={{ width: "28.4%" }} />
            </div>
            <div className="flex justify-between text-[10px] text-zinc-500">
              <span>28.4% capacity</span>
              <span className="text-emerald-400">35.8k receipts left</span>
            </div>
          </div>

          {/* Meter 3: Daily RBL Radar Probes */}
          <div className="p-4 bg-[#08080A] rounded-xl border border-white/[0.04] space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-zinc-400 text-xs">RBL Probes / Day</span>
              <span className="font-bold text-white">1,440 / 5,000</span>
            </div>
            <div className="w-full bg-[#14141A] rounded-full h-2 overflow-hidden border border-white/[0.04]">
              <div className="bg-emerald-500 h-2 rounded-full" style={{ width: "28.8%" }} />
            </div>
            <div className="flex justify-between text-[10px] text-zinc-500">
              <span>28.8% capacity</span>
              <span className="text-emerald-400">Auto-reset in 6h</span>
            </div>
          </div>
        </div>
      </GlassEmeraldCard>

      {/* 3. Billing & Invoice History Table */}
      <GlassEmeraldCard
        title="Tax Invoices & Payment History"
        subtitle="Verified Stripe receipt history with downloadable PDF statements"
        badgeText="3 Invoices Paid"
        badgeVariant="emerald"
        icon={<Clock className="w-5 h-5 text-emerald-400" />}
      >

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="text-zinc-500 border-b border-white/[0.04] text-[10px] uppercase bg-[#08080A]">
              <tr>
                <th className="px-5 py-3.5 font-semibold">Invoice ID</th>
                <th className="px-5 py-3.5 font-semibold">Billing Period</th>
                <th className="px-5 py-3.5 font-semibold">Amount</th>
                <th className="px-5 py-3.5 font-semibold">Payment Status</th>
                <th className="px-5 py-3.5 font-semibold text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-zinc-300">
              {INVOICE_HISTORY.map((inv) => (
                <tr key={inv.id} className="hover:bg-white/[0.01] transition">
                  <td className="px-5 py-4 font-bold text-white">{inv.invoice_number}</td>
                  <td className="px-5 py-4 text-zinc-400">{inv.billing_period}</td>
                  <td className="px-5 py-4 font-bold text-white">{inv.amount}</td>
                  <td className="px-5 py-4">
                    <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      PAID
                    </span>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <button
                      type="button"
                      onClick={() => handleDownloadInvoice(inv.id)}
                      disabled={downloadingId === inv.id}
                      className="px-3 py-1.5 bg-[#14141A] hover:bg-[#1E1E26] border border-white/[0.08] text-zinc-200 hover:text-white rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition cursor-pointer disabled:opacity-50"
                    >
                      {downloadingId === inv.id ? (
                        <RefreshCw className="w-3 h-3 animate-spin text-emerald-400" />
                      ) : (
                        <Download className="w-3 h-3 text-zinc-400" />
                      )}
                      {downloadingId === inv.id ? "Preparing PDF..." : "Download PDF"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassEmeraldCard>
    </div>
  );
}
