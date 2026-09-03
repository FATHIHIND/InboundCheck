"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Zap,
  Copy,
  Check,
  Search,
  ArrowRight,
  Sparkles,
  Lock,
  Server,
  ShoppingBag,
  ExternalLink,
  ChevronRight,
  TrendingUp,
  RefreshCw,
  Layers,
  Terminal,
  Radio,
  Activity,
  CheckCheck,
  Globe,
  Sliders,
  Send,
  MessageSquare,
  ChevronDown,
  HelpCircle,
  MailWarning,
  EyeOff,
  Flame,
  ArrowUpRight,
  Clock,
  Inbox
} from "lucide-react";
import dynamic from "next/dynamic";
import Hero3DCanvas from "@/components/landing/Hero3DCanvas";
import WireframeGridCanvas from "@/components/landing/WireframeGridCanvas";
import RadarPulseCanvas from "@/components/landing/RadarPulseCanvas";
import Tilt3DCard from "@/components/landing/Tilt3DCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

const ThreeUIHero = dynamic(() => import("@/components/landing/ThreeUIHero"), {
  ssr: false,
});

// --- Mouse Following Spotlight Container ---
function SpotlightCard({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    setMousePosition({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`relative rounded-2xl border border-white/[0.08] bg-[#0E0E12] overflow-hidden transition-all duration-300 ${className}`}
    >
      {isHovered && (
        <div
          className="pointer-events-none absolute -inset-px transition-opacity duration-300 z-0"
          style={{
            background: `radial-gradient(400px circle at ${mousePosition.x}px ${mousePosition.y}px, rgba(16, 185, 129, 0.12), transparent 80%)`,
          }}
        />
      )}
      <div className="relative z-10">{children}</div>
    </div>
  );
}

export default function LandingPage() {
  // Domain Audit State
  const [domainInput, setDomainInput] = useState("");
  const [auditStep, setAuditStep] = useState<0 | 1 | 2 | 3 | 4>(0);
  const [isAuditing, setIsAuditing] = useState(false);

  // FAQ Accordion State
  const [expandedFaq, setExpandedFaq] = useState<number | null>(0);

  // Bento Interactive States
  const [dnsToggleFixed, setDnsToggleFixed] = useState(false);
  const [activeStepHover, setActiveStepHover] = useState<number | null>(null);

  // Structured Data Schema.org
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "InboundCheck",
    operatingSystem: "Cloud, Web",
    applicationCategory: "BusinessApplication",
    description:
      "Enterprise email deliverability, real-time blacklist surveillance, and 1-click DNS governance platform for Shopify DTC merchants.",
    offers: {
      "@type": "Offer",
      price: "79.00",
      priceCurrency: "USD",
    },
  };

  const handleSimulatedAudit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!domainInput.trim()) return;

    setIsAuditing(true);
    setAuditStep(1); // Step 1: SPF Lookup

    await new Promise((r) => setTimeout(r, 700));
    setAuditStep(2); // Step 2: RBL Probes

    await new Promise((r) => setTimeout(r, 800));
    setAuditStep(3); // Step 3: DMARC Policy

    await new Promise((r) => setTimeout(r, 700));
    setAuditStep(4); // Step 4: Blurred Gate
    setIsAuditing(false);
  };

  const faqItems = [
    {
      q: "Why do my Shopify emails land in spam if I didn't touch my store settings?",
      a: "In early 2024, Google, Yahoo, and Apple Mail deployed strict anti-spam algorithms requiring 100% cryptographic SPF alignment, valid DKIM CNAME records, and strict DMARC policies (`p=quarantine` or `reject`). If your store sending domain has more than 10 DNS lookups or lacks custom selector rotation, your order confirmations and shipping receipts are automatically relegated to junk folders without warning.",
    },
    {
      q: "How does InboundCheck differ from Klaviyo, Omnisend, or Mailchimp?",
      a: "Klaviyo and Omnisend manage marketing newsletters. InboundCheck operates at the infrastructure & DNS root level. We continuously monitor your apex domain, query authoritative RBL blacklists (Spamhaus, Barracuda), and simulate real-time IMAP delivery receipts to guarantee your highest-value transactional receipts land in the Primary Inbox.",
    },
    {
      q: "Will this fix my Google & Yahoo 2024 compliance warnings?",
      a: "Yes, 100%. InboundCheck generates verified RFC-compliant SPF records with automated recursion flattening (keeping lookup counts under 10), configures 2048-bit DKIM keys, and establishes continuous DMARC aggregate monitoring to permanently clear compliance warnings.",
    },
    {
      q: "How long does the 1-Click Cloudflare & GoDaddy DNS auto-fix take?",
      a: "Under 5 seconds. Connect your Cloudflare API token or GoDaddy key, click 'Auto-Insert Records', and our backend engine runs pre-flight conflict checks before injecting records directly into your DNS zone—with zero manual zone file editing required.",
    },
  ];

  return (
    <div className="min-h-screen bg-[#08080A] text-white selection:bg-emerald-500/30 selection:text-emerald-300 font-sans relative overflow-hidden">
      {/* Schema.org SEO JSON-LD */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* Spatial Background Mesh & Ambient Glow */}
      <div className="fixed inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:4rem_4rem] pointer-events-none z-0 opacity-40" />
      <div className="fixed top-0 left-1/2 -translate-x-1/2 w-[800px] h-[500px] bg-emerald-500/10 blur-[150px] pointer-events-none z-0 rounded-full" />
      <div className="fixed bottom-10 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-emerald-500/5 blur-[160px] pointer-events-none z-0 rounded-full" />

      {/* Navigation Header */}
      <nav className="border-b border-white/[0.08] bg-[#08080A]/85 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-8 h-8 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shadow-[0_0_15px_rgba(16,185,129,0.2)] group-hover:border-emerald-500/50 transition">
              <svg
                className="w-4 h-4 text-emerald-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-base tracking-tight text-white">inboundcheck</span>
              <span className="text-[10px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.5 rounded">
                PRO
              </span>
            </div>
          </Link>

          <div className="hidden md:flex items-center gap-8 text-xs font-mono text-zinc-400">
            <a href="#threat" className="hover:text-white transition">The $4.2k Leak</a>
            <a href="#capabilities" className="hover:text-white transition">Platform Radar</a>
            <a href="#protocol" className="hover:text-white transition">Governance Protocol</a>
            <a href="#pricing" className="hover:text-white transition">Pricing</a>
            <a href="#faq" className="hover:text-white transition">FAQ</a>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/auth/login"
              className="text-xs text-zinc-400 hover:text-white font-medium px-3 py-1.5 transition"
            >
              Sign In
            </Link>
            <EmeraldHoverButton
              href="/auth/signup"
              size="sm"
              variant="primary"
              icon={<ArrowRight size={14} />}
              iconPosition="right"
            >
              Start Free Trial
            </EmeraldHoverButton>
          </div>
        </div>
      </nav>

      {/* 1. High-Suspense Hero Section with Interactive 3D WebGL Constellation */}
      <section className="relative pt-20 pb-20 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto text-center min-h-[620px] flex flex-col justify-center items-center">
        {/* Interactive 3D Particle & Energy Beam Constellation (ThreeUI Inspired) */}
        <Hero3DCanvas />
        <ThreeUIHero />

        <div className="relative z-10 w-full space-y-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 font-mono text-xs font-semibold shadow-[0_0_20px_rgba(16,185,129,0.15)]"
          >
            <Zap size={13} className="fill-current animate-pulse" />
            <span>THE SILENT SHOPIFY PROFIT KILLER</span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-4xl sm:text-6xl font-extrabold tracking-tight text-white max-w-4xl mx-auto leading-[1.12]"
          >
            Your Order Confirmations Are Landing in Spam.{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-teal-200">
              You Just Don't Know It Yet.
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="text-base sm:text-lg text-zinc-400 max-w-2xl mx-auto leading-relaxed"
          >
            Google and Yahoo changed the deliverability rules. Over 28% of Shopify transactional receipts quietly vanish into junk folders—costing you repeat sales and customer trust.
          </motion.p>

          {/* Interactive Live Bait (Free Domain Health Check) */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="max-w-xl mx-auto"
          >
            <div className="obsidian-card p-2 rounded-2xl border border-white/[0.1] shadow-2xl bg-[#0E0E12]/90 backdrop-blur-xl">
              <form onSubmit={handleSimulatedAudit} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <div className="relative flex-1">
                  <Globe className="w-4 h-4 text-zinc-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={domainInput}
                    onChange={(e) => setDomainInput(e.target.value)}
                    placeholder="enter your store sending domain (e.g. brandshop.com)"
                    className="w-full pl-10 pr-4 py-2.5 bg-[#08080A] border border-white/[0.08] rounded-xl text-xs text-white placeholder-zinc-500 font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <EmeraldHoverButton
                  type="submit"
                  isLoading={isAuditing}
                  loadingText="Running Audit..."
                  icon={<Zap size={14} className="fill-current" />}
                  size="md"
                  variant="primary"
                  className="whitespace-nowrap"
                >
                  Check Inboxing Risk Free
                </EmeraldHoverButton>
              </form>

              {/* Diagnostic Terminal Animation & Blurred Gate */}
              {auditStep > 0 && (
                <div className="mt-3 p-3.5 bg-[#08080A] rounded-xl border border-white/[0.06] text-left font-mono text-xs space-y-2">
                  <div className="flex items-center justify-between text-[11px] text-zinc-500 border-b border-white/[0.04] pb-2">
                    <span className="flex items-center gap-1.5">
                      <Terminal size={12} className="text-emerald-400" />
                      LIVE DIAGNOSTIC PROBE: {domainInput}
                    </span>
                    <span className="text-emerald-400">RFC 1035 VALIDATOR</span>
                  </div>

                  <div className="space-y-1.5 text-[11px]">
                    {auditStep >= 1 && (
                      <div className="flex items-center gap-2 text-zinc-300">
                        <span className="text-emerald-400">✓</span> Resolving SPF records across 1.1.1.1 and 8.8.8.8...
                      </div>
                    )}
                    {auditStep >= 2 && (
                      <div className="flex items-center gap-2 text-zinc-300">
                        <span className="text-emerald-400">✓</span> Probing 10 authoritative RBL Blacklists (Spamhaus, Barracuda)...
                      </div>
                    )}
                    {auditStep >= 3 && (
                      <div className="flex items-center gap-2 text-zinc-300">
                        <span className="text-emerald-400">✓</span> Auditing DMARC enforcement & DKIM CNAME selectors...
                      </div>
                    )}
                  </div>

                  {/* Step 4: Blurred Gate */}
                  {auditStep === 4 && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.96 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="mt-3 p-4 rounded-xl bg-red-500/[0.06] border border-red-500/20 relative overflow-hidden"
                    >
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                        <div className="space-y-1">
                          <div className="font-bold text-white text-xs">
                            Deliverability Vulnerabilities Detected
                          </div>
                          <p className="text-[11px] text-zinc-300 font-sans leading-relaxed">
                            Your domain shows <strong className="text-red-400">2 critical deliverability anomalies</strong>: SPF lookup count exceeds RFC limits and DMARC policy is currently set to <code className="text-amber-300">p=none</code>.
                          </p>
                        </div>
                      </div>

                      <div className="mt-3 pt-3 border-t border-white/[0.06] flex flex-col sm:flex-row items-center justify-between gap-2">
                        <span className="text-[10px] text-zinc-400 font-sans">
                          Full cryptographic report prepared.
                        </span>
                        <EmeraldHoverButton
                          href={`/auth/signup?domain=${encodeURIComponent(domainInput)}`}
                          size="sm"
                          variant="primary"
                          icon={<ArrowRight size={13} />}
                          iconPosition="right"
                          className="w-full sm:w-auto"
                        >
                          Unlock Full Report Free
                        </EmeraldHoverButton>
                      </div>
                    </motion.div>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        </div>
      </section>

      {/* 2. The Suspense Narrative: "The $4,200 Silent Leak" Section */}
      <section id="threat" className="relative z-10 py-16 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto border-t border-white/[0.06]">
        <div className="text-center space-y-3 mb-12">
          <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
            THE REALITY GAP
          </span>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            The $4,200 Monthly Silent Leak in Your Store
          </h2>
          <p className="text-xs sm:text-sm text-zinc-400 max-w-xl mx-auto">
            Mailbox providers don't notify you when they shadow-ban your sending domain. Here is what actually happens behind the scenes:
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Card 1: What You See */}
          <div className="obsidian-card p-6 rounded-2xl border border-white/[0.08] space-y-4">
            <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
              <span className="text-xs font-bold text-zinc-400 font-mono flex items-center gap-1.5">
                <CheckCircle2 size={15} className="text-zinc-500" />
                WHAT YOUR SHOPIFY DASHBOARD SHOWS
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
                Surface Metrics
              </span>
            </div>

            <div className="space-y-3 font-mono text-xs">
              <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] flex items-center justify-between">
                <span className="text-zinc-400">Completed Orders</span>
                <span className="text-white font-bold">1,000 Orders</span>
              </div>
              <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] flex items-center justify-between">
                <span className="text-zinc-400">Order Receipts Sent</span>
                <span className="text-white font-bold">1,000 Dispatched</span>
              </div>
              <div className="p-3 bg-[#08080A] rounded-xl border border-white/[0.04] flex items-center justify-between">
                <span className="text-zinc-400">Shopify Status</span>
                <span className="text-emerald-400 font-bold">✓ All Systems Normal</span>
              </div>
            </div>
            <p className="text-xs text-zinc-500 font-sans italic">
              "Everything looks green. You assume your customers are receiving their tracking codes and receipts."
            </p>
          </div>

          {/* Card 2: What Actually Happens */}
          <div className="obsidian-card p-6 rounded-2xl border border-red-500/20 bg-[#0E0E12] space-y-4 relative overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
              <span className="text-xs font-bold text-red-400 font-mono flex items-center gap-1.5">
                <Flame size={15} className="text-red-400" />
                WHAT ACTUALLY HAPPENS AT GMAIL / YAHOO
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">
                Silent Loss
              </span>
            </div>

            <div className="space-y-3 font-mono text-xs">
              <div className="p-3 bg-[#08080A] rounded-xl border border-red-500/10 flex items-center justify-between">
                <span className="text-zinc-400">Filtered into SPAM folder</span>
                <span className="text-red-400 font-bold">240 Receipts (24%)</span>
              </div>
              <div className="p-3 bg-[#08080A] rounded-xl border border-red-500/10 flex items-center justify-between">
                <span className="text-zinc-400">Support Tickets ("Where is my order?")</span>
                <span className="text-amber-400 font-bold">42 Angry Customers</span>
              </div>
              <div className="p-3 bg-[#08080A] rounded-xl border border-red-500/10 flex items-center justify-between">
                <span className="text-zinc-400">Lost LTV & Repeat GMV</span>
                <span className="text-red-400 font-bold">-$4,200.00 / mo</span>
              </div>
            </div>
            <p className="text-xs text-zinc-400 font-sans">
              <strong className="text-white">InboundCheck eliminates this blindspot.</strong> We act as your 24/7 radar to guarantee transactional deliverability.
            </p>
          </div>
        </div>
      </section>

      {/* 3. Interactive Spotlight Bento Grid (Core Platform Capabilities) */}
      <section id="capabilities" className="relative z-10 py-16 px-4 sm:px-6 lg:px-8 max-w-6xl mx-auto border-t border-white/[0.06]">
        <div className="text-center space-y-3 mb-12">
          <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
            ENGINEERED FOR SUPREMACY
          </span>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Real-Time Surveillance & Automated DNS Governance
          </h2>
          <p className="text-xs sm:text-sm text-zinc-400 max-w-xl mx-auto">
            Explore interactive live widgets from our enterprise engine.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Card 1: 3D Wireframe DNS Inspector */}
          <SpotlightCard className="p-6 flex flex-col justify-between space-y-6 relative overflow-hidden group">
            <WireframeGridCanvas />
            <div className="space-y-2 relative z-10">
              <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
                <Server size={18} />
              </div>
              <h3 className="text-base font-bold text-white tracking-tight">1-Click DNS Inspector</h3>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Interactive 3D wireframe plane auditing SPF syntax, DKIM 2048-bit selectors, and DMARC alignment rules in real-time.
              </p>
            </div>

            {/* Interactive Toggle Fixing Widget */}
            <div className="p-4 bg-[#08080A]/90 backdrop-blur-md rounded-xl border border-white/[0.08] space-y-3 font-mono text-xs relative z-10">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-zinc-400">SPF LOOKUP OPTIMIZER</span>
                <button
                  type="button"
                  onClick={() => setDnsToggleFixed(!dnsToggleFixed)}
                  className={`text-[10px] font-bold px-2 py-0.5 rounded cursor-pointer transition ${
                    dnsToggleFixed
                      ? "bg-emerald-500 text-black shadow-[0_0_10px_rgba(16,185,129,0.4)]"
                      : "bg-[#1E1E26] text-zinc-300 hover:text-white"
                  }`}
                >
                  {dnsToggleFixed ? "✓ Flattened (3 / 10)" : "⚡ Flatten SPF"}
                </button>
              </div>
              <div className="text-[11px] text-zinc-300 font-mono truncate">
                {dnsToggleFixed
                  ? "v=spf1 include:_spf.shopify.com ~all"
                  : "v=spf1 include:klaviyo.com include:zendesk.com include:shops.shopify.com (12 Lookups - FAIL)"}
              </div>
            </div>
          </SpotlightCard>

          {/* Card 2: Real-Time Blacklist Radar */}
          <SpotlightCard className="p-6 flex flex-col justify-between space-y-6 relative overflow-hidden group">
            <RadarPulseCanvas />
            <div className="space-y-2 relative z-10">
              <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
                <Radio size={18} />
              </div>
              <h3 className="text-base font-bold text-white tracking-tight">Real-Time Blacklist Radar</h3>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Concentric WebGL radar waves scanning 10 global threat matrices every hour before your sending domain gets burned.
              </p>
            </div>

            {/* Radar Animation Widget */}
            <div className="p-4 bg-[#08080A]/90 backdrop-blur-md rounded-xl border border-white/[0.08] space-y-3 font-mono text-xs relative z-10">
              <div className="flex items-center justify-between text-[10px] text-zinc-500">
                <span>RBL THREAT MATRIX</span>
                <span className="text-emerald-400 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                  PROBING
                </span>
              </div>
              <div className="space-y-1.5 text-[11px]">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-300">Spamhaus ZEN</span>
                  <span className="text-emerald-400 font-bold">CLEAN (18ms)</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-300">Barracuda BRBL</span>
                  <span className="text-emerald-400 font-bold">CLEAN (22ms)</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-300">SpamCop SCBL</span>
                  <span className="text-emerald-400 font-bold">CLEAN (14ms)</span>
                </div>
              </div>
            </div>
          </SpotlightCard>

          {/* Card 3: Instant Telegram Bot Radar (with 3D Tilt Hover Physics) */}
          <SpotlightCard className="p-6 flex flex-col justify-between space-y-6 relative overflow-hidden group">
            <div className="space-y-2 relative z-10">
              <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
                <Send size={18} />
              </div>
              <h3 className="text-base font-bold text-white tracking-tight">Telegram Incident Bot</h3>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Floating 3D glassmorphic push notification engine dispatching critical incident alerts directly to your phone.
              </p>
            </div>

            {/* Telegram Push Mockup wrapped in 3D Tilt Hover Physics */}
            <Tilt3DCard className="relative z-10">
              <div className="p-3.5 bg-[#1C2430]/95 backdrop-blur-md rounded-xl border border-blue-500/30 space-y-1.5 text-xs shadow-2xl">
                <div className="flex items-center justify-between text-[10px] text-zinc-400 font-mono">
                  <span className="flex items-center gap-1 text-blue-400 font-bold">
                    <Send size={10} /> @InboundCheckBot
                  </span>
                  <span>now</span>
                </div>
                <div className="text-[11px] font-bold text-white flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
                  🚨 CRITICAL: Spam Placement Detected
                </div>
                <p className="text-[10px] text-zinc-300 font-mono leading-normal">
                  Order #10492 routed to SPAM by Gmail filter. Health score dropped to 64%.
                </p>
              </div>
            </Tilt3DCard>
          </SpotlightCard>
        </div>
      </section>

      {/* 4. Interactive Protocol Steps (01, 02, 03 Execution Methodology) */}
      <section id="protocol" className="relative z-10 py-16 px-4 sm:px-6 lg:px-8 max-w-4xl mx-auto border-t border-white/[0.06]">
        <div className="text-center space-y-3 mb-12">
          <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
            EXECUTION METHODOLOGY
          </span>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            The InboundCheck Governance Protocol
          </h2>
          <p className="text-xs sm:text-sm text-zinc-400 max-w-lg mx-auto">
            A closed-loop mathematical pipeline protecting transactional receipts from server to subscriber.
          </p>
        </div>

        <div className="space-y-4">
          {/* Step 1 */}
          <div
            onMouseEnter={() => setActiveStepHover(1)}
            onMouseLeave={() => setActiveStepHover(null)}
            className={`obsidian-card p-6 rounded-2xl border transition-all duration-200 cursor-default ${
              activeStepHover === 1
                ? "border-emerald-500/40 bg-[#121218] shadow-[0_0_25px_rgba(16,185,129,0.1)]"
                : "border-white/[0.08]"
            }`}
          >
            <div className="flex items-start gap-4">
              <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                01
              </span>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-white">Multi-Resolver Cryptographic Ingestion</h3>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  Asynchronously queries Cloudflare (1.1.1.1), Google (8.8.8.8), and Quad9 resolvers with SSRF-safe syntax parsers to confirm record propagation and DKIM 2048-bit keys globally.
                </p>
              </div>
            </div>
          </div>

          {/* Step 2 */}
          <div
            onMouseEnter={() => setActiveStepHover(2)}
            onMouseLeave={() => setActiveStepHover(null)}
            className={`obsidian-card p-6 rounded-2xl border transition-all duration-200 cursor-default ${
              activeStepHover === 2
                ? "border-emerald-500/40 bg-[#121218] shadow-[0_0_25px_rgba(16,185,129,0.1)]"
                : "border-white/[0.08]"
            }`}
          >
            <div className="flex items-start gap-4">
              <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                02
              </span>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-white">1-Click Zone Record Auto-Insertion</h3>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  Connect Cloudflare API tokens or GoDaddy keys to auto-publish SPF, CNAMEs, and DMARC records with pre-flight conflict checks and instant snapshot rollback.
                </p>
              </div>
            </div>
          </div>

          {/* Step 3 */}
          <div
            onMouseEnter={() => setActiveStepHover(3)}
            onMouseLeave={() => setActiveStepHover(null)}
            className={`obsidian-card p-6 rounded-2xl border transition-all duration-200 cursor-default ${
              activeStepHover === 3
                ? "border-emerald-500/40 bg-[#121218] shadow-[0_0_25px_rgba(16,185,129,0.1)]"
                : "border-white/[0.08]"
            }`}
          >
            <div className="flex items-start gap-4">
              <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                03
              </span>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-white">Predictive Dispute & Protected Revenue ROI</h3>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  Directly correlates real delivery health to store GMV, computing protected revenue metrics ($R_protected) and dispute reduction multipliers.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 5. High-Converting Pricing Cards */}
      <section id="pricing" className="relative z-10 py-16 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto border-t border-white/[0.06]">
        <div className="text-center space-y-3 mb-12">
          <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
            TRANSPARENT PRICING
          </span>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Simple Pricing, No Surprises.
          </h2>
          <p className="text-xs sm:text-sm text-zinc-400 max-w-md mx-auto">
            Choose a plan tailored to your store volume with continuous deliverability protection.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-3xl mx-auto">
          {/* Starter Plan */}
          <div className="obsidian-card p-7 rounded-2xl border border-white/[0.08] flex flex-col justify-between space-y-6">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-base font-bold text-white">Starter Merchant</h3>
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">
                  Self-Service
                </span>
              </div>
              <div className="text-3xl font-extrabold text-white font-mono">
                $29 <span className="text-xs font-normal text-zinc-400 font-sans">/ month</span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Essential DNS governance and on-demand audits for emerging DTC stores.
              </p>

              <div className="space-y-2.5 pt-4 border-t border-white/[0.06] text-xs font-sans text-zinc-300">
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>1 Verified Apex Sending Domain</span>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>Daily Multi-Resolver DNS Audits</span>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>10-List Blacklist Radar Probing</span>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>Telegram Bot Alert Engine</span>
                </div>
              </div>
            </div>

            <EmeraldHoverButton
              href="/auth/signup"
              size="md"
              variant="ghost"
              className="w-full"
            >
              Start 14-Day Free Trial
            </EmeraldHoverButton>
          </div>

          {/* Growth Plan (Most Popular) */}
          <div className="obsidian-card p-7 rounded-2xl border border-emerald-500/40 relative overflow-hidden flex flex-col justify-between space-y-6 shadow-[0_0_30px_rgba(16,185,129,0.12)]">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-base font-bold text-white">Growth Tier</h3>
                <span className="text-[10px] font-mono font-bold uppercase px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  Most Popular
                </span>
              </div>
              <div className="text-3xl font-extrabold text-white font-mono">
                $79 <span className="text-xs font-normal text-zinc-400 font-sans">/ month</span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Comprehensive 24/7 automated deliverability & 1-click zone auto-fixer for scaling Shopify brands.
              </p>

              <div className="space-y-2.5 pt-4 border-t border-white/[0.06] text-xs font-sans text-zinc-300">
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <strong className="text-white">Up to 5 Apex Sending Domains</strong>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>Hourly DNS & IMAP Telemetry Ingestion</span>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>1-Click Cloudflare & GoDaddy Auto-Fixer</span>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>AI Content Lab & Liquid Template Optimizer</span>
                </div>
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  <span>Instant Telegram Incident Alert Engine</span>
                </div>
              </div>
            </div>

            <EmeraldHoverButton
              href="/auth/signup"
              size="md"
              variant="primary"
              className="w-full"
            >
              Start 14-Day Free Trial
            </EmeraldHoverButton>
          </div>
        </div>
      </section>

      {/* 6. High-Intent FAQ Accordion */}
      <section id="faq" className="relative z-10 py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto border-t border-white/[0.06]">
        <div className="text-center space-y-3 mb-10">
          <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
            FREQUENTLY ASKED QUESTIONS
          </span>
          <h2 className="text-2xl font-bold text-white tracking-tight">
            Everything You Need to Know About InboundCheck
          </h2>
        </div>

        <div className="space-y-3">
          {faqItems.map((item, idx) => (
            <div
              key={idx}
              className="obsidian-card rounded-xl border border-white/[0.08] overflow-hidden"
            >
              <button
                type="button"
                onClick={() => setExpandedFaq(expandedFaq === idx ? null : idx)}
                className="w-full p-4 text-left flex items-center justify-between gap-4 font-semibold text-xs text-white hover:text-emerald-400 transition cursor-pointer"
              >
                <span>{item.q}</span>
                <ChevronDown
                  size={15}
                  className={`text-zinc-400 transition-transform duration-200 flex-shrink-0 ${
                    expandedFaq === idx ? "rotate-180 text-emerald-400" : ""
                  }`}
                />
              </button>
              {expandedFaq === idx && (
                <div className="px-4 pb-4 text-xs text-zinc-400 font-sans leading-relaxed border-t border-white/[0.04] pt-3">
                  {item.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* 7. Sticky Bottom Urgency Bar */}
      <div className="sticky bottom-0 z-40 bg-[#0E0E12]/95 backdrop-blur-md border-t border-white/[0.08] py-3 px-4 shadow-2xl">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2.5 text-zinc-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>
              <strong className="text-white">Google & Yahoo 2024 filtering is active.</strong> Audit your store domain in under 60 seconds.
            </span>
          </div>
          <EmeraldHoverButton
            href="/auth/signup"
            size="sm"
            variant="primary"
            className="whitespace-nowrap"
          >
            Start 14-Day Free Trial
          </EmeraldHoverButton>
        </div>
      </div>

      {/* Footer */}
      <footer className="relative z-10 py-8 px-4 border-t border-white/[0.06] text-center text-xs text-zinc-500 font-mono space-y-2">
        <div>InboundCheck Enterprise — High-Precision Shopify Email Deliverability Platform</div>
        <div className="text-[10px] text-zinc-600">RFC 1035 • RFC 7489 • Google & Yahoo 2024 Mailbox Compliant</div>
      </footer>
    </div>
  );
}
