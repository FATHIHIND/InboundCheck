"use client";

import React, { useState } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  XCircle,
  Copy,
  Check,
  RefreshCw,
  Lock,
  FileCode,
  Globe,
  ExternalLink,
  Zap,
  ArrowRight,
  Info
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

export interface RemoteAssetAuditData {
  audit_id: string;
  domain: string;
  asset_type: "bimi_logo" | "bimi_vmc";
  requested_url: string;
  final_url?: string | null;
  pinned_ip?: string | null;
  fetch_status: "verified" | "rejected" | "failed";
  http_status?: number | null;
  content_type?: string | null;
  content_length_bytes: number;
  content_sha256?: string | null;
  redirect_count: number;
  failure_code?: string | null;
  error_message?: string | null;
  created_at: string;
}

interface AssetVerificationResultProps {
  domain: string;
  initialUrl?: string;
  className?: string;
}

export const AssetVerificationResult: React.FC<AssetVerificationResultProps> = ({
  domain,
  initialUrl = "",
  className = "",
}) => {
  const [assetType, setAssetType] = useState<"bimi_logo" | "bimi_vmc">("bimi_logo");
  const [urlInput, setUrlInput] = useState<string>(initialUrl);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [result, setResult] = useState<RemoteAssetAuditData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedHash, setCopiedHash] = useState<boolean>(false);

  const handleVerify = async () => {
    if (!domain || domain.trim().length < 3) return;
    setIsLoading(true);
    setError(null);

    try {
      const res = await apiFetch("/api/v1/dns/verify-remote-asset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain: domain.trim(),
          asset_type: assetType,
          url: urlInput.trim() || undefined,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Asset verification failed (HTTP ${res.status})`);
      }

      const data: RemoteAssetAuditData = await res.json();
      setResult(data);
    } catch (err: any) {
      console.error("Asset Verification Error:", err);
      setError(err?.message || "Failed to execute hardened asset verification");
    } finally {
      setIsLoading(false);
    }
  };

  const copyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(true);
    setTimeout(() => setCopiedHash(false), 2000);
  };

  return (
    <div
      className={`p-6 rounded-xl border border-white/10 bg-[#08080A]/90 backdrop-blur-md space-y-5 font-mono text-xs ${className}`}
    >
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/10">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
            <Lock className="w-4 h-4" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-white uppercase tracking-wider">
              Store Logo Inbox Verification (BIMI)
            </h4>
            <span className="text-[11px] text-zinc-400 font-sans">
              Ensure your official store logo appears next to order emails in customer inboxes.
            </span>
          </div>
        </div>

        {/* Asset Type Toggle */}
        <div className="flex items-center rounded-lg bg-black/60 border border-white/10 p-0.5">
          <button
            type="button"
            onClick={() => setAssetType("bimi_logo")}
            className={`px-2.5 py-1 rounded transition text-xs ${
              assetType === "bimi_logo"
                ? "bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-500/30"
                : "text-zinc-400 hover:text-white"
            }`}
          >
            BIMI Logo (SVG)
          </button>
          <button
            type="button"
            onClick={() => setAssetType("bimi_vmc")}
            className={`px-2.5 py-1 rounded transition text-xs ${
              assetType === "bimi_vmc"
                ? "bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-500/30"
                : "text-zinc-400 hover:text-white"
            }`}
          >
            VMC Certificate
          </button>
        </div>
      </div>

      {/* Input URL Bar with DNS Discovery Notice */}
      <div className="space-y-2">
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            placeholder={`Auto-discover from default._bimi.${domain || "brand.com"} or enter custom https://...`}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            className="flex-1 px-3.5 py-2 rounded-lg bg-[#0E0E14] border border-zinc-800 text-white placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500 text-xs"
          />
          <EmeraldHoverButton
            size="sm"
            variant="primary"
            onClick={handleVerify}
            isLoading={isLoading}
            loadingText="Verifying Asset..."
            icon={<Zap className="w-3.5 h-3.5 fill-current" />}
          >
            Verify Asset Securely
          </EmeraldHoverButton>
        </div>
        <p className="text-[10px] text-zinc-500 font-sans">
          Leave blank to discover the authoritative URL from DNS BIMI TXT records (`l=` or `a=`).
        </p>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-300 space-y-1">
          <div className="flex items-center gap-1.5 font-bold">
            <XCircle className="w-4 h-4 text-rose-400" />
            <span>Verification Error</span>
          </div>
          <p className="text-[11px]">{error}</p>
        </div>
      )}

      {/* Verification Results Matrix */}
      {result && (
        <div className="space-y-4 pt-2 border-t border-white/5 animate-fadeIn">
          {/* Status Badge & Summary */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-xl bg-black/40 border border-white/5">
            <div className="flex items-center gap-3">
              {result.fetch_status === "verified" ? (
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0">
                  <ShieldCheck className="w-4 h-4" />
                </div>
              ) : result.fetch_status === "rejected" ? (
                <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0">
                  <ShieldAlert className="w-4 h-4" />
                </div>
              ) : (
                <div className="w-8 h-8 rounded-lg bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0">
                  <XCircle className="w-4 h-4" />
                </div>
              )}

              <div>
                <span className="text-xs font-bold text-white block">
                  {result.fetch_status === "verified"
                    ? "Store Logo Verified for Customer Inboxes"
                    : result.fetch_status === "rejected"
                    ? "Rejected by Security Policy"
                    : "Remote Asset Fetch Failed"}
                </span>
                <span className="text-[10px] text-zinc-400 block font-sans">
                  {result.error_message || "All security, transport encryption, and format integrity checks passed."}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={`text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full border ${
                  result.fetch_status === "verified"
                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                    : result.fetch_status === "rejected"
                    ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                    : "bg-rose-500/10 text-rose-400 border-rose-500/30"
                }`}
              >
                {result.fetch_status}
              </span>
            </div>
          </div>

          {/* Detailed Verification Diagnostic Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 bg-[#0E0E14] rounded-lg border border-white/5 space-y-0.5">
              <span className="text-[10px] text-zinc-500 uppercase block">Verified Host IP</span>
              <span className="text-xs text-emerald-400 font-bold block truncate">
                {result.pinned_ip || "Not Connected"}
              </span>
            </div>

            <div className="p-3 bg-[#0E0E14] rounded-lg border border-white/5 space-y-0.5">
              <span className="text-[10px] text-zinc-500 uppercase block">HTTP Status</span>
              <span className="text-xs text-white font-bold block">
                {result.http_status ? `${result.http_status} OK` : "N/A"}
              </span>
            </div>

            <div className="p-3 bg-[#0E0E14] rounded-lg border border-white/5 space-y-0.5">
              <span className="text-[10px] text-zinc-500 uppercase block">Content-Type</span>
              <span className="text-xs text-zinc-300 font-bold block truncate">
                {result.content_type || "N/A"}
              </span>
            </div>

            <div className="p-3 bg-[#0E0E14] rounded-lg border border-white/5 space-y-0.5">
              <span className="text-[10px] text-zinc-500 uppercase block">Payload Size</span>
              <span className="text-xs text-zinc-300 font-bold block">
                {(result.content_length_bytes / 1024).toFixed(2)} KB / 500 KB
              </span>
            </div>
          </div>

          {/* SHA-256 Digest Box */}
          {result.content_sha256 && (
            <div className="p-3 bg-[#0E0E14] rounded-lg border border-white/5 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-zinc-500 uppercase block">SHA-256 Digest</span>
                <button
                  type="button"
                  onClick={() => copyHash(result.content_sha256!)}
                  className="text-[11px] text-emerald-400 hover:text-emerald-300 flex items-center gap-1 transition"
                >
                  {copiedHash ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                  {copiedHash ? "Copied" : "Copy Digest"}
                </button>
              </div>
              <code className="text-[11px] text-emerald-300 block break-all selection:bg-emerald-500/30">
                {result.content_sha256}
              </code>
            </div>
          )}

          {/* Target and Final URLs */}
          <div className="space-y-1 text-[11px] text-zinc-400">
            <div className="flex items-center gap-1.5">
              <span className="text-zinc-500">Requested:</span>
              <span className="text-zinc-300 truncate">{result.requested_url}</span>
            </div>
            {result.final_url && result.final_url !== result.requested_url && (
              <div className="flex items-center gap-1.5">
                <span className="text-zinc-500">Final (Redirects: {result.redirect_count}):</span>
                <span className="text-zinc-300 truncate">{result.final_url}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AssetVerificationResult;
