"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  AlertTriangle,
  ShieldCheck,
  TrendingDown,
  Sparkles,
  RefreshCw,
  ArrowRight,
  ShieldAlert,
  Info,
  DollarSign
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

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
  const [error, setError] = useState<string | null>(null);

  const fetchRisk = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const queryParam = domain ? `?domain=${encodeURIComponent(domain)}` : "";
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
        className={`relative overflow-hidden rounded-2xl border border-white/10 bg-[#0E0E12]/80 backdrop-blur-xl p-5 shadow-2xl animate-pulse ${className}`}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/5" />
            <div className="space-y-2">
              <div className="h-4 w-44 bg-white/10 rounded" />
              <div className="h-3 w-64 bg-white/5 rounded" />
            </div>
          </div>
          <div className="h-10 w-36 bg-white/10 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return null; // Gracefully degrade if no data or initial calculation not present
  }

  const isHighRisk = data.expected_risk_cents > 100000; // > $1,000 at risk
  const isZeroRisk = data.expected_risk_cents === 0;

  const bandColor =
    data.confidence_band === "high"
      ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
      : data.confidence_band === "medium"
      ? "text-amber-400 border-amber-500/30 bg-amber-500/10"
      : "text-rose-400 border-rose-500/30 bg-rose-500/10";

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border transition-all duration-300 ${
        isZeroRisk
          ? "border-emerald-500/30 bg-gradient-to-r from-[#0E1512] via-[#0E0E12] to-[#0A0F0D]"
          : isHighRisk
          ? "border-rose-500/30 bg-gradient-to-r from-[#170E10] via-[#0E0E12] to-[#140D0E]"
          : "border-amber-500/30 bg-gradient-to-r from-[#17140E] via-[#0E0E12] to-[#120F0A]"
      } p-5 backdrop-blur-xl shadow-2xl ${className}`}
    >
      {/* Background Accent Ambient Glow */}
      <div
        className={`absolute -right-16 -top-16 w-64 h-64 rounded-full blur-3xl pointer-events-none opacity-20 ${
          isZeroRisk ? "bg-emerald-500" : isHighRisk ? "bg-rose-500" : "bg-amber-500"
        }`}
      />

      <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-5">
        {/* Left Section: Core Risk Metric & Narrative */}
        <div className="flex items-start sm:items-center gap-4">
          <div
            className={`w-12 h-12 rounded-xl flex items-center justify-center shrink-0 border ${
              isZeroRisk
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                : isHighRisk
                ? "border-rose-500/40 bg-rose-500/10 text-rose-400"
                : "border-amber-500/40 bg-amber-500/10 text-amber-400"
            }`}
          >
            {isZeroRisk ? (
              <ShieldCheck className="w-6 h-6" />
            ) : isHighRisk ? (
              <ShieldAlert className="w-6 h-6" />
            ) : (
              <AlertTriangle className="w-6 h-6" />
            )}
          </div>

          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs uppercase tracking-wider font-semibold text-zinc-400">
                Revenue-at-Risk Diagnostic
              </span>
              <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border font-mono ${bandColor}`}>
                Confidence: {data.confidence_band} {data.band_details ? `(±${data.band_details.margin_error_pct}%)` : ""}
              </span>
              <span className="text-xs text-zinc-500 font-mono">
                {data.domain}
              </span>
            </div>

            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-white">
                {data.expected_risk_formatted}
              </span>
              <span className="text-xs text-zinc-400">
                {isZeroRisk
                  ? "protected monthly email revenue"
                  : "estimated monthly orders at risk of silent spam drop"}
              </span>
            </div>

            <p className="text-xs text-zinc-400 line-clamp-1">
              {data.recommendation}
            </p>
          </div>
        </div>

        {/* Right Section: Quantitative Breakdown & CTA */}
        <div className="flex flex-wrap items-center justify-between lg:justify-end gap-3 pt-2 lg:pt-0 border-t lg:border-t-0 border-white/5">
          {data.breakdown && (
            <div className="hidden sm:flex items-center gap-4 text-xs font-mono text-zinc-400 px-3 py-1.5 rounded-xl bg-black/40 border border-white/5">
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Orders</span>
                <span className="text-white font-semibold">{data.breakdown.order_count.toLocaleString()}</span>
              </div>
              <div className="w-[1px] h-6 bg-white/10" />
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Impairment</span>
                <span
                  className={`font-semibold ${
                    data.breakdown.impairment_probability > 0.1 ? "text-amber-400" : "text-emerald-400"
                  }`}
                >
                  {(data.breakdown.impairment_probability * 100).toFixed(1)}%
                </span>
              </div>
              <div className="w-[1px] h-6 bg-white/10" />
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Score</span>
                <span
                  className={`font-semibold ${
                    data.breakdown.deliverability_score >= 85
                      ? "text-emerald-400"
                      : data.breakdown.deliverability_score >= 60
                      ? "text-amber-400"
                      : "text-rose-400"
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
              className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white border border-white/10 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            {onOpenWizard && (
              <EmeraldHoverButton
                size="sm"
                variant="primary"
                onClick={onOpenWizard}
                icon={<Sparkles className="w-4 h-4 text-emerald-400" />}
              >
                Zero-Spam Wizard
              </EmeraldHoverButton>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
