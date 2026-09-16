"use client";

import React, { useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  Radio,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Copy,
  Check,
  Zap,
  Mail,
  Send,
  ShieldCheck,
  Inbox,
  ArrowRight,
  ExternalLink,
  Sparkles,
  Info,
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

export type PlacementStatus = "inbox" | "spam" | "promotions" | "missing" | "error";
export type TargetProvider = "gmail" | "yahoo" | "outlook";

export interface SeedEmailHeaderInfo {
  message_id?: string | null;
  from_address?: string | null;
  to_address?: string | null;
  subject?: string | null;
  spf_result?: string | null;
  dkim_result?: string | null;
  dmarc_result?: string | null;
  received_date?: string | null;
}

export interface ProviderPlacement {
  provider: TargetProvider;
  placement: PlacementStatus;
  folder_name: string;
  latency_ms: number;
  headers?: SeedEmailHeaderInfo | null;
  error_detail?: string | null;
}

export interface SeedPlacementResult {
  tracking_token: string;
  test_email_address: string;
  store_domain: string;
  overall_placement: string;
  providers: ProviderPlacement[];
  inbox_rate_pct: number;
  spam_rate_pct: number;
  promotions_rate_pct: number;
  missing_count: number;
  executed_at: string;
  execution_time_ms: number;
  recommendations: string[];
}

export interface GenerateSeedResponse {
  tracking_token: string;
  seed_email_address: string;
  store_domain: string;
  subject_tag: string;
  instructions: string;
  expires_in_seconds: number;
}

interface SeedTestingViewProps {
  domain: string;
}

export const SeedTestingView: React.FC<SeedTestingViewProps> = ({ domain }) => {
  const [isGenerating, setIsGenerating] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [seedData, setSeedData] = useState<GenerateSeedResponse | null>(null);
  const [verificationResult, setVerificationResult] = useState<SeedPlacementResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copiedAddress, setCopiedAddress] = useState(false);

  const cleanDomain = domain.trim().toLowerCase();

  const handleGenerateSeed = async () => {
    if (!cleanDomain) {
      setErrorMessage("Please enter a valid store domain before generating a seed address.");
      return;
    }

    setIsGenerating(true);
    setErrorMessage(null);
    setVerificationResult(null);

    try {
      const res = await apiFetch("/api/v1/seed-testing/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          store_domain: cleanDomain,
          provider: "seed",
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to generate seed test address.");
      }

      const data: GenerateSeedResponse = await res.json();
      setSeedData(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to initiate seed test session.";
      setErrorMessage(msg);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCopyAddress = () => {
    if (!seedData?.seed_email_address) return;
    navigator.clipboard.writeText(seedData.seed_email_address);
    setCopiedAddress(true);
    setTimeout(() => setCopiedAddress(false), 2000);
  };

  const handleVerifyPlacement = async () => {
    if (!seedData?.tracking_token || !cleanDomain) {
      setErrorMessage("Please generate a seed address first.");
      return;
    }

    setIsVerifying(true);
    setErrorMessage(null);

    try {
      const res = await apiFetch("/api/v1/seed-testing/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tracking_token: seedData.tracking_token,
          store_domain: cleanDomain,
          timeout_seconds: 10.0,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Verification pipeline timed out or failed.");
      }

      const result: SeedPlacementResult = await res.json();
      setVerificationResult(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to verify seed placement across mailbox providers.";
      setErrorMessage(msg);
    } finally {
      setIsVerifying(false);
    }
  };

  const getPlacementBadge = (status: PlacementStatus) => {
    switch (status) {
      case "inbox":
        return {
          label: "Primary Inbox",
          className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
          icon: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
        };
      case "promotions":
        return {
          label: "Promotions Tab",
          className: "bg-amber-500/15 text-amber-300 border-amber-500/30",
          icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />,
        };
      case "spam":
        return {
          label: "Spam / Junk Folder",
          className: "bg-rose-500/15 text-rose-300 border-rose-500/30",
          icon: <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />,
        };
      case "missing":
        return {
          label: "Awaiting Message",
          className: "bg-zinc-800 text-zinc-400 border-zinc-700",
          icon: <Mail className="w-3.5 h-3.5 text-zinc-500" />,
        };
      default:
        return {
          label: "Check Error",
          className: "bg-zinc-800 text-zinc-400 border-zinc-700",
          icon: <Info className="w-3.5 h-3.5 text-zinc-500" />,
        };
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn font-mono text-xs">
      {/* 1. Header Overview Card */}
      <GlassEmeraldCard
        title="Automated Seed Inbox Testing Pipeline"
        subtitle="Simulates live customer receipt delivery across Gmail, Yahoo, and Outlook to confirm primary inbox placement"
        badgeText="2024 RADAR"
        badgeVariant="emerald"
        icon={<Radio className="w-5 h-5 text-emerald-400" />}
      >
        <div className="space-y-4 font-sans text-xs">
          <p className="text-zinc-300 leading-relaxed">
            Verify whether transactional receipts from <strong className="text-white font-mono">{cleanDomain || "your store"}</strong> reach the customer&apos;s primary inbox or get silently routed into spam. Generate a cryptographically tracked seed address, dispatch a test order confirmation, and analyze real-time placement.
          </p>

          {!seedData && (
            <div className="pt-2">
              <EmeraldHoverButton
                onClick={handleGenerateSeed}
                isLoading={isGenerating}
                loadingText="Generating Seed Address..."
                icon={<Sparkles className="w-4 h-4 fill-current" />}
                size="md"
                variant="primary"
              >
                Generate Test Seed Address
              </EmeraldHoverButton>
            </div>
          )}
        </div>
      </GlassEmeraldCard>

      {errorMessage && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-300 text-xs flex items-start gap-2.5 animate-fadeIn">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-bold text-rose-400 block">Seed Testing Issue:</span>
            <span className="text-[11px] text-rose-200 mt-0.5 block">{errorMessage}</span>
          </div>
        </div>
      )}

      {/* 2. Three-Step Guidance & Seed Address Strip */}
      {seedData && (
        <div className="space-y-5 animate-fadeIn">
          {/* Active Seed Address Banner */}
          <div className="p-5 rounded-2xl bg-[#0E0E12]/90 border border-emerald-500/30 backdrop-blur-xl shadow-xl space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                <span className="font-bold text-white uppercase text-xs tracking-wider">Active Test Address</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  Valid for 60 minutes
                </span>
              </div>
              <span className="text-[11px] text-zinc-400 font-sans">
                Token: <code className="text-emerald-300">{seedData.tracking_token}</code>
              </span>
            </div>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 pt-1">
              <div className="flex-1 bg-black/60 border border-white/10 rounded-xl px-4 py-2.5 font-mono text-sm text-emerald-300 select-all truncate">
                {seedData.seed_email_address}
              </div>
              <button
                type="button"
                onClick={handleCopyAddress}
                className="px-4 py-2.5 bg-[#1F1F22] hover:bg-[#2A2A2D] text-white rounded-xl border border-white/10 flex items-center justify-center gap-2 transition cursor-pointer active:scale-95 shrink-0 font-sans font-semibold text-xs"
              >
                {copiedAddress ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                <span>{copiedAddress ? "Copied!" : "Copy Address"}</span>
              </button>
            </div>
          </div>

          {/* 3 Step Action Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-[#08080A] border border-zinc-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                  STEP 1
                </span>
                <Copy className="w-3.5 h-3.5 text-zinc-500" />
              </div>
              <h4 className="text-white font-bold text-xs">Copy Seed Address</h4>
              <p className="text-[11px] text-zinc-400 font-sans leading-relaxed">
                Copy the unique test recipient address above. It routes into multi-provider IMAP witness mailboxes.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-[#08080A] border border-zinc-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                  STEP 2
                </span>
                <Send className="w-3.5 h-3.5 text-zinc-500" />
              </div>
              <h4 className="text-white font-bold text-xs">Send Test Order Receipt</h4>
              <p className="text-[11px] text-zinc-400 font-sans leading-relaxed">
                From your Shopify admin (Settings &gt; Notifications) or ESP (Klaviyo), dispatch a test order confirmation to this address.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-[#08080A] border border-zinc-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                  STEP 3
                </span>
                <Zap className="w-3.5 h-3.5 text-emerald-400 fill-current" />
              </div>
              <h4 className="text-white font-bold text-xs">Verify Live Placement</h4>
              <p className="text-[11px] text-zinc-400 font-sans leading-relaxed">
                Wait ~10 seconds for email delivery, then trigger the multi-provider verification pipeline below.
              </p>
            </div>
          </div>

          {/* Trigger Verification Bar */}
          <div className="p-4 rounded-xl bg-[#0E0E12] border border-white/[0.08] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div>
              <span className="font-bold text-white block text-xs">Ready to check live inbox placement?</span>
              <span className="text-[11px] text-zinc-400 font-sans">
                Queries Gmail, Yahoo, and Outlook IMAP nodes concurrently.
              </span>
            </div>
            <EmeraldHoverButton
              onClick={handleVerifyPlacement}
              isLoading={isVerifying}
              loadingText="Scanning Providers (10s max)..."
              icon={<Zap className="w-4 h-4 fill-current" />}
              size="md"
              variant="primary"
            >
              Verify Live Placement
            </EmeraldHoverButton>
          </div>
        </div>
      )}

      {/* 3. Verification Results Display */}
      {verificationResult && (
        <div className="space-y-5 animate-fadeIn">
          {/* Rate Summary Strip */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div className="p-4 rounded-xl bg-[#0E0E12] border border-white/[0.08] space-y-1">
              <span className="text-[10px] text-zinc-500 uppercase">Overall Placement</span>
              <div className="text-base font-bold text-white capitalize flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${
                  verificationResult.overall_placement === "inbox"
                    ? "bg-emerald-400"
                    : verificationResult.overall_placement === "promotions"
                    ? "bg-amber-400"
                    : "bg-rose-400"
                }`} />
                {verificationResult.overall_placement}
              </div>
            </div>

            <div className="p-4 rounded-xl bg-[#0E0E12] border border-white/[0.08] space-y-1">
              <span className="text-[10px] text-zinc-500 uppercase">Primary Inbox Rate</span>
              <div className="text-base font-bold text-emerald-400 font-mono">
                {Math.round(verificationResult.inbox_rate_pct)}%
              </div>
            </div>

            <div className="p-4 rounded-xl bg-[#0E0E12] border border-white/[0.08] space-y-1">
              <span className="text-[10px] text-zinc-500 uppercase">Spam Folder Rate</span>
              <div className={`text-base font-bold font-mono ${
                verificationResult.spam_rate_pct > 0 ? "text-rose-400" : "text-zinc-400"
              }`}>
                {Math.round(verificationResult.spam_rate_pct)}%
              </div>
            </div>

            <div className="p-4 rounded-xl bg-[#0E0E12] border border-white/[0.08] space-y-1">
              <span className="text-[10px] text-zinc-500 uppercase">Lookup Latency</span>
              <div className="text-base font-bold text-zinc-300 font-mono">
                {Math.round(verificationResult.execution_time_ms)}ms
              </div>
            </div>
          </div>

          {/* Provider Placement Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {verificationResult.providers.map((p) => {
              const badge = getPlacementBadge(p.placement);

              return (
                <div
                  key={p.provider}
                  className="p-5 rounded-2xl bg-[#0E0E12]/90 border border-white/[0.08] backdrop-blur-xl space-y-4 hover:border-emerald-500/30 transition-all shadow-lg"
                >
                  <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
                    <div className="flex items-center gap-2 font-bold text-white text-sm capitalize">
                      <Mail className="w-4 h-4 text-emerald-400" />
                      {p.provider}
                    </div>
                    <span className="text-[10px] font-mono text-zinc-400">
                      {Math.round(p.latency_ms)}ms
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-zinc-400 font-sans">Folder Classification:</span>
                      <span className={`px-2.5 py-0.5 rounded-full border text-[10px] font-bold flex items-center gap-1.5 ${badge.className}`}>
                        {badge.icon}
                        <span>{badge.label}</span>
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-zinc-400 font-sans">Target Mailbox:</span>
                      <span className="font-mono text-zinc-200">{p.folder_name}</span>
                    </div>

                    {/* Authentication Statuses parsed from message headers */}
                    {p.headers && (
                      <div className="pt-2 border-t border-white/[0.06] space-y-1 text-[10px]">
                        <div className="flex items-center justify-between">
                          <span className="text-zinc-500">SPF Verdict:</span>
                          <span className={p.headers.spf_result === "pass" ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                            {p.headers.spf_result?.toUpperCase() || "N/A"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-zinc-500">DKIM Signature:</span>
                          <span className={p.headers.dkim_result === "pass" ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                            {p.headers.dkim_result?.toUpperCase() || "N/A"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-zinc-500">DMARC Policy:</span>
                          <span className={p.headers.dmarc_result === "pass" ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                            {p.headers.dmarc_result?.toUpperCase() || "N/A"}
                          </span>
                        </div>
                      </div>
                    )}

                    {p.error_detail && (
                      <div className="p-2 rounded bg-rose-500/10 border border-rose-500/20 text-[10px] text-rose-300">
                        {p.error_detail}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Actionable Recommendations */}
          {verificationResult.recommendations.length > 0 && (
            <div className="p-5 rounded-2xl bg-amber-500/10 border border-amber-500/30 space-y-2">
              <div className="flex items-center gap-2 font-bold text-amber-300 text-xs">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Deliverability Recommendations
              </div>
              <ul className="space-y-1.5 list-disc list-inside text-[11px] text-zinc-300 font-sans">
                {verificationResult.recommendations.map((rec, idx) => (
                  <li key={idx}>{rec}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SeedTestingView;
