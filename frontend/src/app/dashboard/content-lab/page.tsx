"use client";

import { useState, useEffect, useRef } from "react";
import { apiFetch } from "@/lib/api";
import {
  Sparkles,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Copy,
  Check,
  Code2,
  Zap,
  Flame,
  X,
  Cpu,
  MailWarning,
  Wand2,
  Send,
  FileText,
  Layers,
  ArrowRight,
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";
import dynamic from "next/dynamic";

const ParticleStreamCanvas = dynamic(() => import("../components/ParticleStreamCanvas"), {
  ssr: false,
});

interface FlaggedEmail {
  id: string;
  template_name: string;
  subject: string;
  original_body: string;
  detected_triggers: string[];
  spam_score: number;
  risk_level: "critical" | "high" | "medium";
  promo_density: number;
  shopify_template_key: string;
}

interface VariantItem {
  variant_id: string;
  variant_name: string;
  subject: string;
  body_html: string;
  estimated_spam_risk: number;
  rationale: string;
}

interface AuditResult {
  spam_score: number;
  risk_level: "critical" | "high" | "medium" | "low";
  promotional_density?: number;
  flagged_triggers: string[];
  recommendations: string[];
}

const PRESET_TEMPLATES = [
  {
    id: "order_confirmation",
    label: "Order Confirmation",
    subject: "Order {{ order.name }} confirmed! Thank you for your purchase",
    body: "<p>Hi {{ customer.first_name }},</p>\n<p>Thank you for buying from our store! ACT NOW to claim 100% FREE shipping on your next purchase. Click here to confirm!</p>\n<p>View order summary: {{ checkout.order_status_url }}</p>",
  },
  {
    id: "shipping_update",
    label: "Shipping Notification",
    subject: "Your order #{{ order.name }} is on the way!",
    body: "<p>Hi {{ customer.first_name }},</p>\n<p>Great news! Your package has been dispatched and is in transit.</p>\n<p>Track your delivery here: {{ fulfillment.tracking_url }}</p>",
  },
  {
    id: "abandoned_checkout",
    label: "Abandoned Cart",
    subject: "Did you forget something? Claim your items now!",
    body: "<p>Hi {{ customer.first_name }},</p>\n<p>You left items in your cart! URGENT: 100% FREE discount expires in 2 hours. Click here to complete checkout!</p>",
  },
];

export default function AIContentLabPage() {
  // Direct Input State
  const [subjectInput, setSubjectInput] = useState(PRESET_TEMPLATES[0].subject);
  const [bodyInput, setBodyInput] = useState(PRESET_TEMPLATES[0].body);
  const [selectedPreset, setSelectedPreset] = useState("order_confirmation");

  // Audit state
  const [isAuditing, setIsAuditing] = useState(false);
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);

  // Variant Generation state
  const [isGeneratingVariants, setIsGeneratingVariants] = useState(false);
  const [variants, setVariants] = useState<VariantItem[]>([]);
  const [selectedVariantIdx, setSelectedVariantIdx] = useState(0);
  const [variantError, setVariantError] = useState<string | null>(null);

  // Copy state
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const directInputRef = useRef<HTMLDivElement>(null);

  // Preset Selection
  const handleSelectPreset = (presetId: string) => {
    const p = PRESET_TEMPLATES.find((t) => t.id === presetId);
    if (p) {
      setSelectedPreset(presetId);
      setSubjectInput(p.subject);
      setBodyInput(p.body);
      setAuditResult(null);
      setVariants([]);
      setAuditError(null);
      setVariantError(null);
    }
  };

  // Run AI Deliverability Audit
  const handleRunAudit = async () => {
    if (!subjectInput.trim() && !bodyInput.trim()) {
      setAuditError("Please enter a subject line or email body content.");
      return;
    }
    setIsAuditing(true);
    setAuditError(null);

    try {
      const res = await apiFetch("/api/v1/ai/audit-template", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: subjectInput.trim(),
          body: bodyInput.trim(),
          template_name: "Interactive Template Input",
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to audit template content.");
      }

      const data = await res.json();
      const audit = data.audit || data;
      setAuditResult({
        spam_score: typeof audit.spam_score === "number" ? audit.spam_score : 0,
        risk_level: audit.risk_level || "low",
        promotional_density: audit.promotional_density,
        flagged_triggers: Array.isArray(audit.flagged_triggers) ? audit.flagged_triggers : [],
        recommendations: Array.isArray(audit.recommendations) ? audit.recommendations : [],
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error analyzing email template.";
      setAuditError(msg);
    } finally {
      setIsAuditing(false);
    }
  };

  // Generate Safe Polymorphic Variants
  const handleGenerateVariants = async () => {
    if (!subjectInput.trim() && !bodyInput.trim()) {
      setVariantError("Please enter a subject line or email body content.");
      return;
    }
    setIsGeneratingVariants(true);
    setVariantError(null);
    setSelectedVariantIdx(0);

    try {
      const res = await apiFetch("/api/v1/ai/generate-variants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: subjectInput.trim(),
          body: bodyInput.trim(),
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to generate polymorphic copy variants.");
      }

      const data = await res.json();
      setVariants(data.variants || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error generating copy variants.";
      setVariantError(msg);
    } finally {
      setIsGeneratingVariants(false);
    }
  };

  // Copy helper
  const handleCopy = (text: string, fieldId: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldId);
    setTimeout(() => setCopiedField(null), 2000);
  };

  return (
    <div className="space-y-6 max-w-[1360px] mx-auto animate-fadeIn pb-16">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-emerald-400 fill-current" />
            Template Optimizer &amp; Content Intelligence
          </h1>
          <p className="text-sm text-zinc-400 font-normal mt-1">
            Scan order receipts for spam triggers and generate Liquid-safe variants.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span
            title="No customer data leaves your browser."
            className="text-xs font-mono px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-bold flex items-center gap-1.5 cursor-help"
          >
            <Cpu className="w-3.5 h-3.5" />
            Privacy-Safe Analysis Engine
          </span>
          <EmeraldHoverButton
            onClick={() => {
              directInputRef.current?.scrollIntoView({ behavior: "smooth" });
            }}
            icon={<Wand2 className="w-4 h-4 text-slate-950" />}
            size="sm"
            variant="solid"
          >
            Direct Template Audit
          </EmeraldHoverButton>
        </div>
      </div>

      {/* 2. Balanced Full-Height Multi-Column Workspace */}
      <div ref={directInputRef} className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start min-h-[calc(100vh-12rem)]">
        {/* Left Column (lg:col-span-6 space-y-4): Template Editor */}
        <div className="lg:col-span-6 space-y-4">
          <GlassEmeraldCard
            title="Interactive Template Scanner"
            subtitle="Paste or select any transactional email template to test spam density"
            badgeText="Liquid Safe"
            badgeVariant="emerald"
            icon={<Code2 className="w-5 h-5 text-emerald-400" />}
            className="space-y-4"
          >
            {/* Preset Selector */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-300">
                Shopify Template Presets
              </label>
              <div className="flex flex-wrap gap-2">
                {PRESET_TEMPLATES.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handleSelectPreset(p.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-mono transition cursor-pointer flex items-center gap-1.5 border ${
                      selectedPreset === p.id
                        ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300 font-bold"
                        : "bg-[#08080A] border-zinc-800 text-zinc-400 hover:text-white hover:border-zinc-700"
                    }`}
                  >
                    <FileText className="w-3.5 h-3.5" />
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Subject Line Input */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-semibold text-zinc-300">
                  Email Subject Line
                </label>
                <span className="text-[10px] text-zinc-500 font-mono">
                  Supports Liquid: {"{{ order.name }}"}
                </span>
              </div>
              <input
                type="text"
                value={subjectInput}
                onChange={(e) => {
                  setSubjectInput(e.target.value);
                  setSelectedPreset("");
                }}
                placeholder="e.g. Order {{ order.name }} confirmed - Receipt & details"
                className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-zinc-100 placeholder:text-zinc-500 font-medium font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>

            {/* Body Content Textarea */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-semibold text-zinc-300">
                  Email HTML / Text Body
                </label>
                <span className="text-[10px] text-zinc-500 font-mono">
                  Preserves Liquid variables &amp; HTML
                </span>
              </div>
              <textarea
                rows={9}
                value={bodyInput}
                onChange={(e) => {
                  setBodyInput(e.target.value);
                  setSelectedPreset("");
                }}
                placeholder="<p>Hi {{ customer.first_name }},</p><p>Thank you for buying from our store! ACT NOW to claim 100% FREE shipping on your next purchase...</p>"
                className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-zinc-100 placeholder:text-zinc-500 font-medium font-mono text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500/30 focus:border-emerald-500/60 leading-relaxed transition-all resize-y min-h-[180px]"
              />
            </div>

            {/* Action Buttons */}
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <EmeraldHoverButton
                onClick={handleRunAudit}
                isLoading={isAuditing}
                loadingText="Auditing Template..."
                icon={<Zap className="w-3.5 h-3.5" />}
                size="sm"
                variant="secondary"
                className="flex-1 min-h-[40px]"
              >
                Scan Deliverability
              </EmeraldHoverButton>

              <EmeraldHoverButton
                onClick={handleGenerateVariants}
                isLoading={isGeneratingVariants}
                loadingText="Generating Variants..."
                icon={<Sparkles className="w-3.5 h-3.5 fill-current" />}
                size="sm"
                variant="primary"
                className="flex-1 min-h-[40px]"
              >
                Generate Safe Variants
              </EmeraldHoverButton>
            </div>

            {/* Error Notices */}
            {auditError && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-xs text-rose-300 font-mono flex items-center gap-2 animate-fadeIn">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{auditError}</span>
              </div>
            )}
            {variantError && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-xs text-rose-300 font-mono flex items-center gap-2 animate-fadeIn">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{variantError}</span>
              </div>
            )}
          </GlassEmeraldCard>
        </div>

        {/* Right Column (lg:col-span-6 space-y-4): Intelligence Stage */}
        <div className="lg:col-span-6 space-y-4">
          {/* Awaiting State when no audit has been run and no variants generated */}
          {!auditResult && variants.length === 0 && !isAuditing && !isGeneratingVariants && (
            <div className="rounded-2xl bg-[#0A0A0C]/80 border border-zinc-800/80 backdrop-blur-xl p-8 flex flex-col items-center justify-center text-center min-h-[490px] space-y-4 shadow-xl animate-fadeIn">
              <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.15)]">
                <Sparkles className="w-7 h-7" />
              </div>
              <div className="space-y-1.5 max-w-sm">
                <span className="text-[10px] font-mono uppercase tracking-widest text-emerald-400/80 font-bold px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 inline-block mb-1">
                  Deliverability Intelligence Engine
                </span>
                <h3 className="text-base font-bold text-white tracking-tight">
                  Awaiting Template Input
                </h3>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  Select a Shopify preset on the left or paste your transactional copy to scan for 2024 spam triggers and generate Liquid-safe variants.
                </p>
              </div>
              {!subjectInput.trim() && !bodyInput.trim() && (
                <button
                  type="button"
                  onClick={() => handleSelectPreset("order_confirmation")}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-all shadow-[0_0_15px_rgba(16,185,129,0.25)] cursor-pointer active:scale-95 min-h-[40px]"
                >
                  <FileText className="w-4 h-4" />
                  <span>Load Sample DTC Receipt</span>
                </button>
              )}
            </div>
          )}

          {/* Loading States */}
          {(isAuditing || isGeneratingVariants) && (
            <div className="rounded-2xl bg-[#0A0A0C]/80 border border-zinc-800/80 backdrop-blur-xl p-8 flex flex-col items-center justify-center text-center min-h-[490px] space-y-4 shadow-xl animate-fadeIn font-mono text-xs">
              <RefreshCw className="w-8 h-8 text-emerald-400 animate-spin" />
              <div className="space-y-1">
                <span className="text-white font-bold block text-sm">
                  {isAuditing ? "Analyzing Template Spam Density..." : "Synthesizing Polymorphic Copy Variations..."}
                </span>
                <span className="text-zinc-400 text-xs">
                  Validating RFC deliverability heuristics and preserving Shopify Liquid syntax.
                </span>
              </div>
            </div>
          )}

          {/* Deliverability Audit Breakdown */}
          {auditResult && (
            <div className="space-y-4 animate-fadeIn">
              <GlassEmeraldCard
                title="Deliverability Audit Breakdown"
                subtitle="Spam phrase analysis and Google/Yahoo 2024 compliance scoring"
                badgeText={
                  auditResult.spam_score >= 60
                    ? "Critical Risk"
                    : auditResult.spam_score >= 30
                    ? "Warning"
                    : "Optimal"
                }
                badgeVariant={
                  auditResult.spam_score >= 60
                    ? "amber"
                    : auditResult.spam_score >= 30
                    ? "amber"
                    : "emerald"
                }
                icon={<MailWarning className="w-5 h-5 text-emerald-400" />}
                className="space-y-4"
              >
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs">
                  <div className="p-3 bg-[#08080A] rounded-xl border border-zinc-800 space-y-1">
                    <span className="text-[10px] uppercase text-zinc-500 block">Spam Risk Score</span>
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xl font-bold ${
                          auditResult.spam_score >= 60
                            ? "text-rose-400"
                            : auditResult.spam_score >= 30
                            ? "text-amber-400"
                            : "text-emerald-400"
                        }`}
                      >
                        {auditResult.spam_score} / 100
                      </span>
                      <span className="text-[10px] text-zinc-400 font-sans">
                        {auditResult.spam_score < 30 ? "Clean" : "Spam Risk"}
                      </span>
                    </div>
                  </div>

                  <div className="p-3 bg-[#08080A] rounded-xl border border-zinc-800 space-y-1">
                    <span className="text-[10px] uppercase text-zinc-500 block">Risk Tier</span>
                    <div className="pt-0.5">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wide border ${
                        auditResult.risk_level === "critical"
                          ? "bg-rose-500/10 text-rose-400 border-rose-500/30"
                          : auditResult.risk_level === "high"
                          ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                          : auditResult.risk_level === "medium"
                          ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
                          : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          auditResult.risk_level === "critical"
                            ? "bg-rose-400 animate-pulse"
                            : auditResult.risk_level === "high"
                            ? "bg-amber-400 animate-pulse"
                            : auditResult.risk_level === "medium"
                            ? "bg-amber-300 animate-pulse"
                            : "bg-emerald-400"
                        }`} />
                        {auditResult.risk_level}
                      </span>
                    </div>
                  </div>

                  <div className="p-3 bg-[#08080A] rounded-xl border border-zinc-800 space-y-1">
                    <span className="text-[10px] uppercase text-zinc-500 block">Flagged Phrases</span>
                    <div className="text-sm font-bold text-white pt-1">
                      {auditResult.flagged_triggers.length} detected
                    </div>
                  </div>
                </div>

                {/* Flagged Triggers List */}
                {auditResult.flagged_triggers.length > 0 && (
                  <div className="space-y-2 pt-1">
                    <span className="text-xs font-semibold text-zinc-300 block">
                      Detected High-Friction Spam Triggers:
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {auditResult.flagged_triggers.map((trigger, i) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 bg-rose-500/10 border border-rose-500/25 rounded-md text-xs font-mono font-bold text-rose-300"
                        >
                          “{trigger}”
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recommendations */}
                {auditResult.recommendations.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-zinc-800/80">
                    <span className="text-xs font-semibold text-zinc-300 block">
                      AI Deliverability Recommendations:
                    </span>
                    <ul className="space-y-1.5 text-xs text-zinc-400 font-sans">
                      {auditResult.recommendations.map((rec, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                          <span>{rec}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </GlassEmeraldCard>
            </div>
          )}

          {/* Generated Polymorphic Variants Panel */}
          {variants.length > 0 && (
            <div className="space-y-4 animate-fadeIn">
              <GlassEmeraldCard
                title="Spam-Free Copy Variations"
                subtitle="Deliverability-optimized variations that preserve all Liquid template tags"
                badgeText={`${variants.length} Variants Ready`}
                badgeVariant="emerald"
                icon={<Sparkles className="w-5 h-5 text-emerald-400 fill-current" />}
                className="space-y-4"
              >
                {/* Variant Navigation Tabs */}
                <div className="flex flex-wrap gap-2 font-mono text-xs">
                  {variants.map((v, idx) => (
                    <button
                      key={v.variant_id || idx}
                      type="button"
                      onClick={() => setSelectedVariantIdx(idx)}
                      className={`px-3 py-1.5 rounded-xl font-bold transition flex items-center gap-1.5 cursor-pointer border ${
                        selectedVariantIdx === idx
                          ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                          : "bg-[#08080A] text-zinc-400 hover:text-white border-zinc-800"
                      }`}
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      {v.variant_name}
                    </button>
                  ))}
                </div>

                {/* Active Variant Display */}
                {variants[selectedVariantIdx] && (
                  <div className="space-y-4 font-mono text-xs">
                    {/* Subject Line Card */}
                    <div className="p-3.5 bg-[#08080A] rounded-xl border border-emerald-500/20 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] uppercase text-zinc-500 font-semibold block">
                          Optimized Subject Line
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            handleCopy(variants[selectedVariantIdx].subject, "variant_subject")
                          }
                          className="text-xs flex items-center gap-1 text-emerald-400 hover:text-emerald-300 transition cursor-pointer"
                        >
                          {copiedField === "variant_subject" ? (
                            <>
                              <Check className="w-3.5 h-3.5" /> Copied Subject
                            </>
                          ) : (
                            <>
                              <Copy className="w-3.5 h-3.5" /> Copy Subject
                            </>
                          )}
                        </button>
                      </div>
                      <div className="p-2.5 bg-[#050507] rounded-lg border border-white/[0.04] text-white font-sans font-semibold text-sm select-all">
                        {variants[selectedVariantIdx].subject}
                      </div>
                    </div>

                    {/* Body Content Card */}
                    <div className="p-3.5 bg-[#08080A] rounded-xl border border-emerald-500/20 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] uppercase text-zinc-500 font-semibold block">
                          Liquid-Preserving Body HTML
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            handleCopy(variants[selectedVariantIdx].body_html, "variant_body")
                          }
                          className="text-xs flex items-center gap-1 text-emerald-400 hover:text-emerald-300 transition cursor-pointer"
                        >
                          {copiedField === "variant_body" ? (
                            <>
                              <Check className="w-3.5 h-3.5" /> Copied Body HTML
                            </>
                          ) : (
                            <>
                              <Copy className="w-3.5 h-3.5" /> Copy Body HTML
                            </>
                          )}
                        </button>
                      </div>
                      <div className="p-2.5 bg-[#050507] rounded-lg border border-white/[0.04] text-emerald-300 text-[11px] leading-relaxed break-all max-h-52 overflow-y-auto select-all">
                        {variants[selectedVariantIdx].body_html}
                      </div>
                    </div>

                    {/* Rationale & Metrics */}
                    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3 bg-zinc-900/40 rounded-xl border border-white/[0.04]">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">
                          Risk: {variants[selectedVariantIdx].estimated_spam_risk}/100
                        </span>
                        <span className="text-zinc-400 font-sans text-xs">
                          {variants[selectedVariantIdx].rationale}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          const fullCopy = `Subject: ${variants[selectedVariantIdx].subject}\n\n${variants[selectedVariantIdx].body_html}`;
                          handleCopy(fullCopy, "variant_full");
                        }}
                        className="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold rounded-lg text-xs flex items-center gap-1.5 transition cursor-pointer shrink-0"
                      >
                        {copiedField === "variant_full" ? (
                          <>
                            <Check className="w-3.5 h-3.5" /> Copied All
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" /> Copy Full Template
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )}
              </GlassEmeraldCard>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
