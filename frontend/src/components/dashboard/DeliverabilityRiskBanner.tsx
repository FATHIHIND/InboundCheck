"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ShieldCheck,
  RefreshCw,
  ArrowRight,
  ShieldAlert,
  DollarSign
} from "lucide-react";
import { apiFetch } from "@/lib/api";

export interface DeliverabilityRiskData {
  domain: string;
  expected_risk_cents: number;
  expected_risk_formatted: string;
  monthly_gmv_cents: number;
  monthly_gmv_formatted: string;
  impairment_probability: number;
  customer_impact_factor: number;
  confidence_band: "high" | "medium" | "low";
  band_details?: {
    band: string;
    margin_error_pct: number;
    lower_bound_cents: number;
    upper_bound_cents: number;
    lower_bound_formatted: string;
    upper_bound_formatted: string;
    explanation: string;
  };
  breakdown?: {
    order_count: number;
    average_order_value_cents: number;
    monthly_gmv_cents: number;
    impairment_probability: number;
    customer_impact_factor: number;
    deliverability_score: number;
    dmarc_penalty: number;
    spf_penalty: number;
    dkim_penalty: number;
    rbl_penalty: number;
  };
  calculated_at?: string;
  recommendation?: string;
}

interface DeliverabilityRiskBannerProps {
  domain?: string;
  onOpenWizard?: () => void;
  className?: string;
}

export const DeliverabilityRiskBanner: React.FC<DeliverabilityRiskBannerProps> = ({
  domain,
  onOpenWizard,
  className = "",
}) => {
  const [data, setData] = useState<DeliverabilityRiskData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [_error, setError] = useState<string | null>(null);

  const fetchRisk = useCallback(async () => {
    if (!domain || !domain.trim()) {
      setData(null);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const queryParam = `?domain=${encodeURIComponent(domain.trim())}`;
      const res = await apiFetch(`/api/v1/analytics/revenue-at-risk${queryParam}`);
      if (!res.ok) {
        throw new Error(`Failed to load revenue risk (HTTP ${res.status})`);
      }
      const json: DeliverabilityRiskData = await res.json();
      setData(json);
    } catch (err: any) {
      console.error("Error fetching revenue risk:", err);
      setError(err?.message || "Failed to calculate revenue at risk");
    } finally {
      setIsLoading(false);
    }
  }, [domain]);

  useEffect(() => {
    fetchRisk();
  }, [fetchRisk]);

  if (isLoading) {
    return (
      <div
        className={`rounded-lg border border-slate-200 bg-white p-5 shadow-xs animate-pulse ${className}`}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-slate-100" />
            <div className="space-y-2">
              <div className="h-4 w-44 bg-slate-200 rounded" />
              <div className="h-3 w-64 bg-slate-100 rounded" />
            </div>
          </div>
          <div className="h-9 w-36 bg-slate-200 rounded-md" />
        </div>
      </div>
    );
  }

  const hasRealStore = Boolean(
    domain &&
    domain.trim() !== "" &&
    data &&
    data.domain &&
    data.domain !== "yourstore.com" &&
    data.monthly_gmv_cents > 0
  );

  // When no verified store/domain is connected or no order data exists, render clean onboarding prompt
  if (!hasRealStore || !data) {
    return (
      <div
        className={`rounded-lg border border-slate-200 bg-white p-5 shadow-xs ${className}`}
      >
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 flex items-center justify-center shrink-0">
              <DollarSign className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-slate-900 tracking-tight">
                  Connect your store to calculate revenue at risk
                </h3>
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-semibold">
                  Setup Required
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Protect order confirmations and recover lost checkout revenue under Google &amp; Yahoo 2024 Bulk Sender Requirements.
              </p>
            </div>
          </div>

          <Link
            href="/dashboard/shopify"
            className="inline-flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-4 py-2 rounded-md text-xs transition-colors shadow-xs shrink-0"
          >
            <span>Connect Shopify Store</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    );
  }

  const isHighRisk = data.expected_risk_cents > 100000; // > $1,000 at risk
  const isZeroRisk = data.expected_risk_cents === 0;

  const bandColor =
    data.confidence_band === "high"
      ? "text-emerald-700 border-emerald-200 bg-emerald-50"
      : data.confidence_band === "medium"
      ? "text-amber-700 border-amber-200 bg-amber-50"
      : "text-rose-700 border-rose-200 bg-rose-50";

  return (
    <div
      className={`rounded-lg border transition-all ${
        isZeroRisk
          ? "border-emerald-200 bg-emerald-50/40"
          : isHighRisk
          ? "border-rose-200 bg-rose-50/40"
          : "border-amber-200 bg-amber-50/40"
      } p-5 shadow-xs ${className}`}
    >
      <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left Section: Core Risk Metric & Narrative */}
        <div className="flex items-start sm:items-center gap-3.5">
          <div
            className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 border ${
              isZeroRisk
                ? "border-emerald-200 bg-emerald-100 text-emerald-700"
                : isHighRisk
                ? "border-rose-200 bg-rose-100 text-rose-700"
                : "border-amber-200 bg-amber-100 text-amber-700"
            }`}
          >
            {isZeroRisk ? (
              <ShieldCheck className="w-5 h-5" />
            ) : isHighRisk ? (
              <ShieldAlert className="w-5 h-5" />
            ) : (
              <AlertTriangle className="w-5 h-5" />
            )}
          </div>

          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs uppercase tracking-wider font-semibold text-slate-500 font-mono">
                {isZeroRisk ? "Protected Revenue Diagnostic" : "⚠ At-Risk Revenue Alert"}
              </span>
              <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border font-mono ${bandColor}`}>
                Confidence: {data.confidence_band} {data.band_details ? `(±${data.band_details.margin_error_pct}%)` : ""}
              </span>
              <span className="text-xs text-slate-600 font-mono font-medium">
                {data.domain}
              </span>
            </div>

            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-xl font-bold font-mono tracking-tight text-slate-900">
                {data.expected_risk_formatted}
              </span>
              <span className="text-xs text-slate-600">
                {isZeroRisk
                  ? "protected monthly email revenue"
                  : "estimated monthly orders at risk of silent spam drop"}
              </span>
            </div>

            <p className="text-xs text-slate-500 line-clamp-1">
              {data.recommendation || "Google & Yahoo 2024 Bulk Sender Requirements: Prevent Customer Support Disputes & Recover Lost Checkout Revenue."}
            </p>
          </div>
        </div>

        {/* Right Section: Quantitative Breakdown & CTA */}
        <div className="flex flex-wrap items-center justify-between lg:justify-end gap-3 pt-2 lg:pt-0 border-t lg:border-t-0 border-slate-200/60">
          {data.breakdown && (
            <div className="hidden sm:flex items-center gap-4 text-xs font-mono text-slate-600 px-3 py-1.5 rounded-md bg-white border border-slate-200 shadow-2xs">
              <div>
                <span className="text-slate-400 block text-[10px] uppercase">Orders</span>
                <span className="text-slate-900 font-semibold">{data.breakdown.order_count.toLocaleString()}</span>
              </div>
              <div className="w-[1px] h-6 bg-slate-200" />
              <div>
                <span className="text-slate-400 block text-[10px] uppercase">Impairment</span>
                <span
                  className={`font-semibold ${
                    data.breakdown.impairment_probability > 0.1 ? "text-amber-700" : "text-emerald-700"
                  }`}
                >
                  {(data.breakdown.impairment_probability * 100).toFixed(1)}%
                </span>
              </div>
              <div className="w-[1px] h-6 bg-slate-200" />
              <div>
                <span className="text-slate-400 block text-[10px] uppercase">Score</span>
                <span
                  className={`font-semibold ${
                    data.breakdown.deliverability_score >= 85
                      ? "text-emerald-700"
                      : data.breakdown.deliverability_score >= 60
                      ? "text-amber-700"
                      : "text-rose-700"
                  }`}
                >
                  {data.breakdown.deliverability_score}/100
                </span>
              </div>
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchRisk()}
              title="Refresh revenue analysis"
              className="p-2 rounded-md bg-white hover:bg-slate-50 text-slate-600 hover:text-slate-900 border border-slate-300 shadow-2xs transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            {onOpenWizard && (
              <button
                type="button"
                onClick={onOpenWizard}
                className="h-9 px-4 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-md shadow-xs transition-colors"
              >
                {isZeroRisk ? "Review DNS Records" : "Protect Store Revenue"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default DeliverabilityRiskBanner;
