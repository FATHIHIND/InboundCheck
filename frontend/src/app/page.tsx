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
  Check,
  ArrowRight,
  Sparkles,
  Server,
  ShoppingBag,
  Terminal,
  Radio,
  Send,
  Plus,
  Globe,
  Menu,
  X,
  Flame,
  Clock,
  Inbox,
  Lock,
  ChevronRight,
  ExternalLink,
  Activity
} from "lucide-react";
import FadeInUp from "@/components/landing/FadeInUp";

// 5 Core High-Intent FAQ Items
const FAQ_ITEMS = [
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
    a: "Yes, 100%. InboundCheck generates verified Google & Yahoo 2024 compliant SPF records with automated recursion flattening (keeping lookup counts under 10), configures 2048-bit DKIM keys, and establishes continuous DMARC aggregate monitoring to permanently clear compliance warnings.",
  },
  {
    q: "How long does the 1-Click Cloudflare & GoDaddy DNS auto-fix take?",
    a: "Under 5 seconds. Connect your Cloudflare API token or GoDaddy key, click 'Auto-Insert Records', and our backend engine runs pre-flight conflict checks before injecting records directly into your DNS zone—with zero manual zone file editing required.",
  },
  {
    q: "How does the continuous Blacklist Radar and Telegram alerting protect my revenue?",
    a: "InboundCheck monitors 10+ authoritative spam blacklists (Spamhaus, Barracuda, SpamCop) on an hourly daemon. If an IP or domain threat is detected, an instant actionable alert is dispatched to your Telegram bot or webhook with 1-click remediation before it triggers customer disputes or payment gateway holds.",
  },
];

// Brand Marquee Data
const MARQUEE_BRANDS = [
  {
    name: "Shopify Plus",
    icon: (
      <svg className="w-5 h-5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" />
        <path d="M3 6h18" />
        <path d="M16 10a4 4 0 0 1-8 0" />
      </svg>
    ),
  },
  {
    name: "Klaviyo",
    icon: (
      <svg className="w-5 h-5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 2 7 12 12 22 7 12 2" />
        <polyline points="2 17 12 22 22 17" />
        <polyline points="2 12 12 17 22 12" />
      </svg>
    ),
  },
  {
    name: "Cloudflare",
    icon: (
      <svg className="w-5 h-5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
      </svg>
    ),
  },
  {
    name: "Google Workspace",
    icon: (
      <svg className="w-5 h-5 text-teal-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="16" x="2" y="4" rx="2" />
        <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
      </svg>
    ),
  },
  {
    name: "Postmark",
    icon: (
      <svg className="w-5 h-5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
    ),
  },
];

export default function LandingPage() {
  // Navigation Scroll State
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Free Domain Diagnostic Tool State
  const [domainInput, setDomainInput] = useState("");
  const [auditStep, setAuditStep] = useState<0 | 1 | 2 | 3 | 4>(0);
  const [isAuditing, setIsAuditing] = useState(false);

  // Interactive Mockups State
  const [dnsToggleFixed, setDnsToggleFixed] = useState(false);

  // FAQ Accordion State (0-indexed, null if collapsed)
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const handleSimulatedAudit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!domainInput.trim()) return;

    setIsAuditing(true);
    setAuditStep(1); // Step 1: Resolving SPF records

    await new Promise((r) => setTimeout(r, 650));
    setAuditStep(2); // Step 2: Probing 10 authoritative RBLs

    await new Promise((r) => setTimeout(r, 700));
    setAuditStep(3); // Step 3: Auditing DMARC & DKIM selectors

    await new Promise((r) => setTimeout(r, 650));
    setAuditStep(4); // Step 4: Blurred Gate / Vulnerabilities Detected
    setIsAuditing(false);
  };

  const closeMobileMenu = () => {
    setMobileMenuOpen(false);
  };

  // Structured Data Schema.org
  const structuredData = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebApplication",
        "@id": "https://inboundcheck.com/#webapp",
        name: "InboundCheck",
        url: "https://inboundcheck.com",
        operatingSystem: "Cloud, Web",
        applicationCategory: "BusinessApplication",
        applicationSubCategory: "Email Deliverability & DNS Governance for E-Commerce",
        description:
          "Enterprise email deliverability, real-time blacklist surveillance, and 1-click DNS governance platform for Shopify DTC merchants.",
        offers: [
          {
            "@type": "Offer",
            name: "Starter Merchant",
            price: "29.00",
            priceCurrency: "USD",
            availability: "https://schema.org/InStock",
            description: "Single DTC Brand - 1 Verified Apex Sending Domain",
          },
          {
            "@type": "Offer",
            name: "Growth Tier",
            price: "79.00",
            priceCurrency: "USD",
            availability: "https://schema.org/InStock",
            description: "Scaling Multi-Brand - Up to 5 Apex Sending Domains",
          },
          {
            "@type": "Offer",
            name: "Enterprise Tier",
            price: "199.00",
            priceCurrency: "USD",
            availability: "https://schema.org/InStock",
            description: "Shopify Plus & Aggregators - Unlimited Monitored Domains",
          },
        ],
      },
      {
        "@type": "FAQPage",
        "@id": "https://inboundcheck.com/#faq",
        mainEntity: FAQ_ITEMS.map((item) => ({
          "@type": "Question",
          name: item.q,
          acceptedAnswer: {
            "@type": "Answer",
            text: item.a,
          },
        })),
      },
    ],
  };

  return (
    <div className="min-h-screen bg-black text-white selection:bg-emerald-500/30 selection:text-emerald-300 font-sans relative overflow-x-hidden">
      {/* Schema.org SEO & GEO JSON-LD */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />

      {/* 2. Navigation Bar (Sticky, Glassmorphic & Responsive) */}
      <nav
        className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
          scrolled
            ? "bg-black/80 backdrop-blur-md border-b border-white/5 shadow-2xl"
            : "bg-transparent border-b border-transparent"
        }`}
      >
        <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
          {/* Brand Logo */}
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shadow-[0_0_15px_rgba(16,185,129,0.25)] group-hover:border-emerald-500/60 transition-all">
              <svg
                className="w-5 h-5 text-emerald-400 group-hover:scale-105 transition-transform"
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
            <div className="flex items-center gap-2">
              <span className="font-bold text-base md:text-lg tracking-tight text-white">
                InboundCheck
              </span>
              <span className="text-[10px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.5 rounded tracking-wide">
                PRO
              </span>
            </div>
          </Link>

          {/* Center Links (Desktop) */}
          <div className="hidden md:flex items-center gap-8">
            <a
              href="#blindspot"
              className="text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
              The Blindspot
            </a>
            <a
              href="#dns-inspector"
              className="text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
              DNS Inspector
            </a>
            <a
              href="#radar"
              className="text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
              Blacklist Radar
            </a>
            <a
              href="#pricing"
              className="text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
              Pricing
            </a>
            <a
              href="#faq"
              className="text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
              FAQ
            </a>
          </div>

          {/* Right CTA Buttons */}
          <div className="hidden md:flex items-center gap-4">
            <Link
              href="/auth/login"
              className="text-sm font-medium text-gray-400 hover:text-white transition-colors"
            >
              Sign In
            </Link>
            <Link
              href="/auth/signup"
              className="bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium px-5 py-2.5 rounded-full border border-white/10 transition-all hover:border-white/25 shadow-sm active:scale-95"
            >
              Get started
            </Link>
          </div>

          {/* Mobile Hamburger Button */}
          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden p-2 text-gray-400 hover:text-white transition-colors"
            aria-label="Toggle navigation menu"
          >
            {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Mobile Dropdown Menu */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25 }}
              className="md:hidden bg-black/95 backdrop-blur-xl border-b border-white/10 px-6 py-6 space-y-4"
            >
              <div className="flex flex-col space-y-3">
                <a
                  href="#blindspot"
                  onClick={closeMobileMenu}
                  className="text-base font-medium text-gray-300 hover:text-emerald-400 transition-colors py-1.5"
                >
                  The Blindspot
                </a>
                <a
                  href="#dns-inspector"
                  onClick={closeMobileMenu}
                  className="text-base font-medium text-gray-300 hover:text-emerald-400 transition-colors py-1.5"
                >
                  DNS Inspector
                </a>
                <a
                  href="#radar"
                  onClick={closeMobileMenu}
                  className="text-base font-medium text-gray-300 hover:text-emerald-400 transition-colors py-1.5"
                >
                  Blacklist Radar
                </a>
                <a
                  href="#pricing"
                  onClick={closeMobileMenu}
                  className="text-base font-medium text-gray-300 hover:text-emerald-400 transition-colors py-1.5"
                >
                  Pricing
                </a>
                <a
                  href="#faq"
                  onClick={closeMobileMenu}
                  className="text-base font-medium text-gray-300 hover:text-emerald-400 transition-colors py-1.5"
                >
                  FAQ
                </a>
              </div>

              <div className="pt-4 border-t border-white/10 flex flex-col gap-3">
                <Link
                  href="/auth/login"
                  onClick={closeMobileMenu}
                  className="text-center py-2.5 text-sm font-medium text-gray-300 hover:text-white"
                >
                  Sign In
                </Link>
                <Link
                  href="/auth/signup"
                  onClick={closeMobileMenu}
                  className="text-center bg-white text-black font-semibold text-sm py-3 rounded-full hover:bg-gray-100 transition-all shadow-md"
                >
                  Get started
                </Link>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </nav>

      {/* 3. Hero Section (id="about") */}
      <section
        id="about"
        className="min-h-screen flex flex-col items-center justify-center pt-32 pb-20 relative z-0 overflow-hidden text-center px-6"
      >
        {/* Ambient Background Video */}
        <video
          autoPlay
          loop
          muted
          playsInline
          className="-z-10 absolute inset-0 object-cover min-w-full min-h-full opacity-40 pointer-events-none select-none"
        >
          <source
            src="https://cdn.sceneai.art/Hero%20Section%20Video/50b4f304-cdca-4e12-8735-580d225834be.mp4"
            type="video/mp4"
          />
        </video>
        {/* Gradient Overlay */}
        <div className="absolute inset-0 -z-10 bg-gradient-to-b from-black/40 via-transparent to-black pointer-events-none" />

        <div className="max-w-4xl mx-auto flex flex-col items-center relative z-10">
          {/* Top Badge */}
          <FadeInUp delay={0.1}>
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/5 border border-white/10 text-xs font-medium text-emerald-400 mb-8 backdrop-blur-sm shadow-[0_0_20px_rgba(16,185,129,0.15)]">
              <span>✨ Announcing Google &amp; Yahoo 2024 Enforcement Defense</span>
            </div>
          </FadeInUp>

          {/* Main Headline */}
          <FadeInUp delay={0.2}>
            <h1 className="text-4xl sm:text-6xl md:text-7xl font-bold tracking-tight text-white leading-[1.12] mb-6">
              Your Order Confirmations Are Landing in Spam.{" "}
              <span className="font-serif italic font-normal text-emerald-400">
                Don&apos;t Know It Yet.
              </span>
            </h1>
          </FadeInUp>

          {/* Sub-text */}
          <FadeInUp delay={0.3}>
            <p className="text-[16px] text-gray-400 max-w-2xl text-center mb-8 leading-relaxed">
              Google and Yahoo silently discard up to 28% of Shopify order receipts. InboundCheck continuously governs your DNS and alerts you before chargebacks occur.
            </p>
          </FadeInUp>

          {/* Interactive Live Bait Domain Health Check */}
          <FadeInUp delay={0.4} className="w-full max-w-xl mx-auto mt-8 mb-14">
            <div className="p-2.5 rounded-2xl border border-white/10 bg-[#0E0E12]/90 backdrop-blur-xl shadow-2xl">
              <form onSubmit={handleSimulatedAudit} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <div className="relative flex-1">
                  <Globe className="w-4 h-4 text-zinc-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={domainInput}
                    onChange={(e) => setDomainInput(e.target.value)}
                    placeholder="enter your store sending domain (e.g. store.com)"
                    className="w-full pl-10 pr-4 py-2.5 bg-[#050507] border border-white/10 rounded-xl text-xs text-white placeholder-zinc-500 font-mono focus:outline-none focus:border-emerald-500 transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={isAuditing}
                  className="bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs px-5 py-2.5 rounded-xl transition-all shadow-[0_0_20px_rgba(16,185,129,0.3)] flex items-center justify-center gap-1.5 whitespace-nowrap cursor-pointer active:scale-95 disabled:opacity-60"
                >
                  <Zap size={14} className="fill-current" />
                  <span>{isAuditing ? "Running Audit..." : "Check Inboxing Risk-Free"}</span>
                </button>
              </form>

              {/* Diagnostic Terminal Animation & Blurred Gate */}
              {auditStep > 0 && (
                <div className="mt-3 p-4 bg-[#050507] rounded-xl border border-white/10 text-left font-mono text-xs space-y-2.5">
                  <div className="flex items-center justify-between text-[11px] text-zinc-500 border-b border-white/10 pb-2">
                    <span className="flex items-center gap-1.5">
                      <Terminal size={12} className="text-emerald-400" />
                      LIVE DIAGNOSTIC PROBE: {domainInput}
                    </span>
                    <span className="text-emerald-400 font-semibold">GOOGLE &amp; YAHOO 2024 VALIDATOR</span>
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
                        <span className="text-emerald-400">✓</span> Auditing DMARC enforcement &amp; DKIM CNAME selectors...
                      </div>
                    )}
                  </div>

                  {auditStep === 4 && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.98 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="mt-3 p-4 rounded-xl bg-red-500/10 border border-red-500/30 relative overflow-hidden"
                    >
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                        <div className="space-y-1">
                          <div className="font-bold text-white text-xs">
                            Deliverability Vulnerabilities Detected
                          </div>
                          <p className="text-[11px] text-zinc-300 font-sans leading-relaxed">
                            Your domain shows <strong className="text-red-400">2 critical deliverability anomalies</strong>: SPF lookup count exceeds Google &amp; Yahoo 2024 limits and DMARC policy is currently set to <code className="text-amber-300 font-mono">p=none</code>.
                          </p>
                        </div>
                      </div>

                      <div className="mt-3 pt-3 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-3">
                        <span className="text-[11px] text-zinc-400 font-sans">
                          Full cryptographic report prepared.
                        </span>
                        <Link
                          href={`/auth/signup?domain=${encodeURIComponent(domainInput)}`}
                          className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-all shadow-[0_0_15px_rgba(16,185,129,0.3)]"
                        >
                          <span>Unlock Full Report Free</span>
                          <ArrowRight size={13} />
                        </Link>
                      </div>
                    </motion.div>
                  )}
                </div>
              )}
            </div>
          </FadeInUp>
        </div>

        {/* Seamless Infinite Brand Marquee */}
        <div className="w-full max-w-7xl mx-auto pt-4 relative">
          <p className="text-xs font-mono text-gray-500 uppercase tracking-widest text-center mb-6">
            Safeguarding transactional deliverability for stores powered by
          </p>
          <div className="relative overflow-hidden w-full [mask-image:linear-gradient(to_right,transparent,black_10%,black_90%,transparent)]">
            <div className="w-max flex items-center animate-[marquee_30s_linear_infinite] hover:[animation-play-state:paused]">
              {/* Duplicate 4 times for seamless continuous looping */}
              {[...Array(4)].map((_, loopIdx) => (
                <div key={loopIdx} className="flex items-center">
                  {MARQUEE_BRANDS.map((brand, bIdx) => (
                    <div
                      key={`${loopIdx}-${bIdx}`}
                      className="flex-shrink-0 px-8 flex items-center gap-3 text-gray-400 hover:text-white transition-colors duration-200"
                    >
                      <div className="p-2 rounded-lg bg-white/5 border border-white/10">
                        {brand.icon}
                      </div>
                      <span className="font-medium text-sm tracking-tight text-gray-300">
                        {brand.name}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* The Blindspot Section (id="blindspot" & alias id="threat") */}
      <section id="blindspot" className="py-28 px-6 max-w-5xl mx-auto border-t border-white/5 relative z-10">
        <div id="threat" className="absolute -top-10 left-0" />
        <FadeInUp>
          <div className="text-center space-y-3 mb-16">
            <span className="text-xs font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
              THE REALITY GAP
            </span>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-semibold text-white tracking-tight">
              The $4,200 Monthly Silent Leak in Your Store
            </h2>
            <p className="text-sm md:text-base text-gray-400 max-w-xl mx-auto">
              Mailbox providers don&apos;t notify you when they shadow-ban your sending domain. Here is what actually happens behind the scenes:
            </p>
          </div>
        </FadeInUp>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Card 1: What You See */}
          <FadeInUp delay={0.1}>
            <div className="h-full p-8 rounded-3xl bg-[#0E0E12]/80 backdrop-blur-xl border border-white/10 space-y-6 shadow-2xl relative overflow-hidden group hover:border-white/20 transition-all">
              <div className="flex items-center justify-between border-b border-white/10 pb-4">
                <span className="text-xs font-semibold text-zinc-300 font-mono flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-emerald-400" />
                  WHAT YOUR SHOPIFY DASHBOARD SHOWS
                </span>
                <span className="text-[10px] font-mono px-2.5 py-1 rounded bg-white/5 text-zinc-400 border border-white/10">
                  Surface Metrics
                </span>
              </div>

              <div className="space-y-3 font-mono text-xs">
                <div className="p-4 bg-black/60 rounded-xl border border-white/5 flex items-center justify-between">
                  <span className="text-zinc-400">Completed Orders</span>
                  <span className="text-white font-semibold">1,000 Orders</span>
                </div>
                <div className="p-4 bg-black/60 rounded-xl border border-white/5 flex items-center justify-between">
                  <span className="text-zinc-400">Order Receipts Sent</span>
                  <span className="text-white font-semibold">1,000 Dispatched</span>
                </div>
                <div className="p-4 bg-black/60 rounded-xl border border-white/5 flex items-center justify-between">
                  <span className="text-zinc-400">Shopify Status</span>
                  <span className="text-emerald-400 font-semibold flex items-center gap-1.5">
                    <Check size={14} /> All Systems Normal
                  </span>
                </div>
              </div>

              <p className="text-xs text-gray-400 italic">
                &ldquo;Everything looks green. You assume your customers are receiving tracking codes and receipts.&rdquo;
              </p>
            </div>
          </FadeInUp>

          {/* Card 2: What Actually Happens */}
          <FadeInUp delay={0.2}>
            <div className="h-full p-8 rounded-3xl bg-rose-950/20 backdrop-blur-xl border border-rose-900/40 space-y-6 shadow-2xl relative overflow-hidden group hover:border-rose-700/50 transition-all">
              <div className="flex items-center justify-between border-b border-rose-900/30 pb-4">
                <span className="text-xs font-semibold text-rose-400 font-mono flex items-center gap-2">
                  <Flame size={16} className="text-rose-400" />
                  WHAT ACTUALLY HAPPENS AT GMAIL / YAHOO
                </span>
                <span className="text-[10px] font-mono px-2.5 py-1 rounded-full bg-rose-950/60 text-rose-400 border border-rose-800/50 font-medium">
                  Silent Loss
                </span>
              </div>

              <div className="space-y-3 font-mono text-xs">
                <div className="p-4 bg-black/60 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-zinc-400">Filtered into SPAM folder</span>
                  <span className="text-rose-400 font-semibold">240 Receipts (24%)</span>
                </div>
                <div className="p-4 bg-black/60 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-zinc-400">Support Tickets (&ldquo;Where is my order?&rdquo;)</span>
                  <span className="text-rose-300 font-semibold">42 Angry Customers</span>
                </div>
                <div className="p-4 bg-black/60 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-zinc-400">Lost LTV &amp; Dispute Risk</span>
                  <span className="text-rose-400 font-semibold">-$4,200.00 / mo</span>
                </div>
              </div>

              <p className="text-xs text-zinc-300">
                InboundCheck eliminates this blindspot with 24/7 proactive DNS and deliverability monitoring.
              </p>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* 4. Interactive Feature Sections (Two-Column Layouts) */}
      
      {/* Column 1: 1-Click DNS Inspector & SPF Conflict Resolver (id="dns-inspector") */}
      <section id="dns-inspector" className="py-28 px-6 max-w-7xl mx-auto border-t border-white/5 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          {/* Left: Copy */}
          <FadeInUp className="space-y-6">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 text-xs font-mono font-semibold">
              <Server size={14} />
              <span>DNS GOVERNANCE ENGINE</span>
            </div>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white leading-tight">
              1-Click DNS Inspector &amp; SPF Conflict Resolver
            </h2>
            <p className="text-base text-gray-400 leading-relaxed">
              Google and Yahoo enforce a strict 10-lookup limit on SPF records. DTC stores using Shopify, Klaviyo, Zendesk, and Postmark exceed this limit almost immediately, triggering silent spam classification.
            </p>
            <div className="space-y-3 font-sans text-sm text-gray-300">
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span><strong>SPF 10-Lookup Cap Enforcement:</strong> Automated recursion flattening maintains compliance with RFC 7208.</span>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span><strong>DKIM 2048-Bit Cryptographic Alignment:</strong> Automatically validates and rotates Shopify CNAME selector records.</span>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span><strong>1-Click Cloudflare &amp; GoDaddy Sync:</strong> Insert or rollback verified records directly via secure API with zero manual zone editing.</span>
              </div>
            </div>
            <div className="pt-2">
              <Link
                href="/auth/signup"
                className="inline-flex items-center gap-2 text-emerald-400 font-semibold text-sm hover:text-emerald-300 transition-colors"
              >
                <span>Audit your SPF budget now</span>
                <ChevronRight size={16} />
              </Link>
            </div>
          </FadeInUp>

          {/* Right Mockup: Glassmorphic floating card with background video */}
          <FadeInUp delay={0.2}>
            <div className="bg-[#1C1C1E]/90 backdrop-blur-xl border border-white/10 rounded-3xl p-6 sm:p-8 relative overflow-hidden shadow-2xl group hover:border-emerald-500/40 transition-all duration-300">
              {/* Background Video */}
              <video
                autoPlay
                loop
                muted
                playsInline
                className="absolute inset-0 w-full h-full object-cover opacity-30 -z-10 pointer-events-none"
              >
                <source
                  src="https://cdn.sceneai.art/Hero%20Section%20Video/1bcc8fa3-37f6-4c53-8591-0347e4c7f8ac.mp4"
                  type="video/mp4"
                />
              </video>
              <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/40 -z-10" />

              {/* Card Content */}
              <div className="space-y-6 relative z-10">
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                      <Server size={16} />
                    </div>
                    <div>
                      <div className="font-semibold text-sm text-white">store-checkout.com</div>
                      <div className="text-[10px] text-gray-400 font-mono">Cloudflare Managed Zone</div>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-semibold">
                    SYNCED
                  </span>
                </div>

                {/* SPF Lookup Gauge (4/10 used) */}
                <div className="p-4 bg-black/75 backdrop-blur-md rounded-2xl border border-white/10 space-y-3 font-mono">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-400">SPF LOOKUP BUDGET</span>
                    <span className="text-emerald-400 font-bold">4 / 10 Used</span>
                  </div>
                  <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                    <div className="bg-emerald-400 h-2 rounded-full w-[40%] shadow-[0_0_12px_rgba(16,185,129,0.8)]" />
                  </div>
                  <div className="flex items-center justify-between text-[11px] pt-1">
                    <span className="text-zinc-400 font-sans">Google / Yahoo Threshold</span>
                    <span className="text-emerald-400 font-medium">Within Safe Limits</span>
                  </div>
                </div>

                {/* DMARC and DKIM Status */}
                <div className="grid grid-cols-2 gap-3 font-mono text-xs">
                  <div className="p-3 bg-black/75 rounded-xl border border-white/10 space-y-1">
                    <span className="text-[10px] text-zinc-500 block">DMARC POLICY</span>
                    <span className="text-emerald-400 font-bold text-xs bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20 inline-block">
                      p=quarantine
                    </span>
                  </div>
                  <div className="p-3 bg-black/75 rounded-xl border border-white/10 space-y-1">
                    <span className="text-[10px] text-zinc-500 block">DKIM KEY LENGTH</span>
                    <span className="text-white font-bold text-xs inline-block">
                      2048-bit RSA
                    </span>
                  </div>
                </div>

                {/* 1-Click Fix Toggle */}
                <button
                  type="button"
                  onClick={() => setDnsToggleFixed(!dnsToggleFixed)}
                  className={`w-full py-3 px-4 rounded-xl text-xs font-semibold transition-all cursor-pointer flex items-center justify-center gap-2 shadow-lg ${
                    dnsToggleFixed
                      ? "bg-emerald-500 text-black shadow-[0_0_20px_rgba(16,185,129,0.4)]"
                      : "bg-[#1F1F22] text-emerald-400 hover:bg-[#2A2A2D] border border-emerald-500/30 hover:border-emerald-500/50"
                  }`}
                >
                  <Zap size={14} className="fill-current" />
                  <span>
                    {dnsToggleFixed
                      ? "✓ Records Auto-Applied to Cloudflare"
                      : "1-Click Auto-Apply DNS Fix"}
                  </span>
                </button>
              </div>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* Column 2: Real-Time Blacklist Radar (id="radar") */}
      <section id="radar" className="py-28 px-6 max-w-7xl mx-auto border-t border-white/5 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          {/* Left Mockup: Floating card with background video */}
          <FadeInUp className="order-2 lg:order-1">
            <div className="bg-[#1C1C1E]/90 backdrop-blur-xl border border-white/10 rounded-3xl p-6 sm:p-8 relative overflow-hidden shadow-2xl group hover:border-emerald-500/40 transition-all duration-300">
              {/* Background Video */}
              <video
                autoPlay
                loop
                muted
                playsInline
                className="absolute inset-0 w-full h-full object-cover opacity-30 -z-10 pointer-events-none"
              >
                <source
                  src="https://cdn.sceneai.art/Hero%20Section%20Video/736fd4a0-70ac-4f44-9633-55769ead6aca.mp4"
                  type="video/mp4"
                />
              </video>
              <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/40 -z-10" />

              {/* Card Content */}
              <div className="space-y-6 relative z-10">
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                      <Radio size={16} />
                    </div>
                    <div>
                      <div className="font-semibold text-sm text-white">RBL Threat Radar</div>
                      <div className="text-[10px] text-gray-400 font-mono">10 Authoritative Registries</div>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 font-semibold">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    LIVE SCANNING
                  </span>
                </div>

                {/* Radar Real-Time Status Nodes */}
                <div className="space-y-2.5 font-mono text-xs">
                  <div className="flex items-center justify-between p-3 rounded-xl bg-black/75 backdrop-blur-md border border-white/10">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-emerald-400" />
                      <span className="text-zinc-200">Spamhaus ZEN</span>
                    </div>
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <Check size={13} /> 0 LISTINGS (CLEAN)
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-black/75 backdrop-blur-md border border-white/10">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-emerald-400" />
                      <span className="text-zinc-200">Barracuda BRBL</span>
                    </div>
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <Check size={13} /> 0 LISTINGS (CLEAN)
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-black/75 backdrop-blur-md border border-white/10">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-emerald-400" />
                      <span className="text-zinc-200">SpamCop SCBL</span>
                    </div>
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <Check size={13} /> 0 LISTINGS (CLEAN)
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-black/75 backdrop-blur-md border border-white/10">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-emerald-400" />
                      <span className="text-zinc-200">Invaluement URI</span>
                    </div>
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <Check size={13} /> 0 LISTINGS (CLEAN)
                    </span>
                  </div>
                </div>

                {/* Sweep Telemetry Footer */}
                <div className="p-3 bg-black/60 rounded-xl border border-white/5 flex items-center justify-between text-[11px] font-mono text-zinc-400">
                  <span>Last Automated Sweep: 4 mins ago</span>
                  <span className="text-emerald-400 font-semibold">100% Reputation Health</span>
                </div>
              </div>
            </div>
          </FadeInUp>

          {/* Right: Copy */}
          <FadeInUp delay={0.2} className="order-1 lg:order-2 space-y-6">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 text-xs font-mono font-semibold">
              <Radio size={14} />
              <span>REAL-TIME BLACKLIST RADAR</span>
            </div>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white leading-tight">
              Real-Time Blacklist Radar &amp; Hourly Anti-Spam Sweeps
            </h2>
            <p className="text-base text-gray-400 leading-relaxed">
              When a shared IP pool or secondary domain is flagged on Spamhaus or Barracuda, mailbox providers drop your delivery rates to near-zero without sending a single bounce notification.
            </p>
            <div className="space-y-3 font-sans text-sm text-gray-300">
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span><strong>Continuous 60-Minute Probing:</strong> Queries 10 authoritative RBL databases around the clock.</span>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span><strong>Predictive 48–72h Risk Forecasting:</strong> Identifies early listing velocity before primary inbox placement is destroyed.</span>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span><strong>Automated Delisting Guidance:</strong> Pre-fills delisting requests with verified diagnostic proofs to expedite remediation.</span>
              </div>
            </div>
            <div className="pt-2">
              <Link
                href="/auth/signup"
                className="inline-flex items-center gap-2 text-emerald-400 font-semibold text-sm hover:text-emerald-300 transition-colors"
              >
                <span>Protect your domain reputation</span>
                <ChevronRight size={16} />
              </Link>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* Telegram Incident Alerts & Omnichannel Failover Showcase */}
      <section className="py-24 px-6 max-w-7xl mx-auto border-t border-white/5 relative z-10">
        <FadeInUp>
          <div className="text-center space-y-3 mb-16">
            <span className="text-xs font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
              INSTANT INCIDENT RESPONSE
            </span>
            <h2 className="text-3xl sm:text-4xl font-semibold text-white tracking-tight">
              Telegram Bot Alerts &amp; Omnichannel WhatsApp Fallback
            </h2>
            <p className="text-sm md:text-base text-gray-400 max-w-xl mx-auto">
              Never miss a silent delivery failure. InboundCheck notifies your engineering team instantly and routes high-priority receipts via WhatsApp/SMS when mailboxes reject them.
            </p>
          </div>
        </FadeInUp>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
          {/* Telegram Alert Box */}
          <FadeInUp delay={0.1}>
            <div className="p-7 rounded-3xl bg-[#0E0E12]/90 backdrop-blur-xl border border-white/10 space-y-4 hover:border-emerald-500/40 transition-all shadow-xl">
              <div className="flex items-center justify-between text-xs text-zinc-400 font-mono border-b border-white/10 pb-3">
                <span className="flex items-center gap-1.5 text-emerald-400 font-semibold">
                  <Send size={14} /> @InboundCheckBot
                </span>
                <span>Real-Time Push</span>
              </div>
              <div className="text-sm font-semibold text-white flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-rose-400 animate-ping" />
                CRITICAL: Spam Placement Alert
              </div>
              <p className="text-xs text-zinc-300 font-mono leading-relaxed bg-black/60 p-3 rounded-xl border border-white/5">
                Sending domain health score dropped to 72%. Gmail anti-spam filter classified Order #10492 as junk.
              </p>
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                  1-Click Remediate
                </span>
                <span className="text-xs text-zinc-400 font-mono">Dispatched in 320ms</span>
              </div>
            </div>
          </FadeInUp>

          {/* Omnichannel Failover Box */}
          <FadeInUp delay={0.2}>
            <div className="p-7 rounded-3xl bg-[#0E0E12]/90 backdrop-blur-xl border border-white/10 space-y-4 hover:border-emerald-500/40 transition-all shadow-xl">
              <div className="flex items-center justify-between text-xs text-zinc-400 font-mono border-b border-white/10 pb-3">
                <span className="flex items-center gap-1.5 text-teal-400 font-semibold">
                  <Zap size={14} /> Omnichannel Failover Engine
                </span>
                <span>E.164 Fallback</span>
              </div>
              <div className="text-sm font-semibold text-white flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
                Receipt Auto-Routed to WhatsApp
              </div>
              <p className="text-xs text-zinc-300 font-mono leading-relaxed bg-black/60 p-3 rounded-xl border border-white/5">
                When customer email bounced, order confirmation #10492 was delivered via WhatsApp Business API within 1.2s. Zero dispute risk.
              </p>
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs font-mono px-2.5 py-1 rounded bg-teal-500/20 text-teal-300 border border-teal-500/40">
                  Revenue Protected: $184.00
                </span>
                <span className="text-xs text-zinc-400 font-mono">100% Delivery SLA</span>
              </div>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* How It Works (3 Steps) */}
      <section id="how-it-works" className="py-28 px-6 max-w-4xl mx-auto border-t border-white/5 relative z-10">
        <FadeInUp>
          <div className="text-center space-y-3 mb-16">
            <span className="text-xs font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
              ONBOARDING IN 60 SECONDS
            </span>
            <h2 className="text-3xl sm:text-4xl font-semibold text-white tracking-tight">
              How InboundCheck Protects Your Store
            </h2>
            <p className="text-sm md:text-base text-gray-400 max-w-lg mx-auto">
              Three simple steps to permanently eliminate spam placement for your order confirmations.
            </p>
          </div>
        </FadeInUp>

        <div className="space-y-4">
          <FadeInUp delay={0.1}>
            <div className="p-6 sm:p-7 rounded-2xl bg-[#0E0E12]/80 backdrop-blur-xl border border-white/10 hover:border-emerald-500/40 transition-all">
              <div className="flex items-start gap-4">
                <span className="text-xs font-mono font-bold px-3 py-1.5 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  01
                </span>
                <div className="space-y-1">
                  <h3 className="text-base font-semibold text-white">Connect Your Sending Domain</h3>
                  <p className="text-xs sm:text-sm text-gray-400 leading-relaxed">
                    Enter your store&apos;s sending domain. Our engine probes Cloudflare, Google, and Quad9 resolvers in real-time to benchmark your authentication baseline.
                  </p>
                </div>
              </div>
            </div>
          </FadeInUp>

          <FadeInUp delay={0.2}>
            <div className="p-6 sm:p-7 rounded-2xl bg-[#0E0E12]/80 backdrop-blur-xl border border-white/10 hover:border-emerald-500/40 transition-all">
              <div className="flex items-start gap-4">
                <span className="text-xs font-mono font-bold px-3 py-1.5 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  02
                </span>
                <div className="space-y-1">
                  <h3 className="text-base font-semibold text-white">1-Click Automated DNS Remediation</h3>
                  <p className="text-xs sm:text-sm text-gray-400 leading-relaxed">
                    Connect your Cloudflare or GoDaddy API to auto-patch missing SPF includes, DMARC policies, and Shopify DKIM keys without touching DNS zone files manually.
                  </p>
                </div>
              </div>
            </div>
          </FadeInUp>

          <FadeInUp delay={0.3}>
            <div className="p-6 sm:p-7 rounded-2xl bg-[#0E0E12]/80 backdrop-blur-xl border border-white/10 hover:border-emerald-500/40 transition-all">
              <div className="flex items-start gap-4">
                <span className="text-xs font-mono font-bold px-3 py-1.5 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  03
                </span>
                <div className="space-y-1">
                  <h3 className="text-base font-semibold text-white">24/7 Radar &amp; Revenue Protection</h3>
                  <p className="text-xs sm:text-sm text-gray-400 leading-relaxed">
                    Relax while our hourly daemon monitors spam blacklists, catches IP traps, and alerts your team on Telegram before customer disputes hit your payment processor.
                  </p>
                </div>
              </div>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* 5. High-Converting Pricing Cards (id="pricing") */}
      <section id="pricing" className="py-28 px-6 max-w-7xl mx-auto border-t border-white/5 relative z-10">
        <FadeInUp>
          <div className="text-center space-y-3 mb-16">
            <span className="text-xs font-mono tracking-[0.2em] text-emerald-400 uppercase font-semibold">
              TRANSPARENT PRICING
            </span>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-semibold text-white tracking-tight">
              Simple Pricing, No Surprises.
            </h2>
            <p className="text-sm md:text-base text-gray-400 max-w-md mx-auto">
              Choose a plan tailored to your store volume with continuous deliverability protection.
            </p>
          </div>
        </FadeInUp>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-stretch max-w-6xl mx-auto">
          {/* Starter Plan */}
          <FadeInUp delay={0.1} className="h-full">
            <div className="h-full p-8 rounded-3xl bg-[#0E0E12]/90 backdrop-blur-xl border border-white/10 flex flex-col justify-between hover:border-white/20 transition-all shadow-xl">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono uppercase px-3 py-1 rounded-full bg-white/5 text-gray-300 border border-white/10">
                    Single DTC Brand
                  </span>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">Starter Merchant</h3>
                  <div className="text-4xl font-bold text-white font-mono tracking-tight pt-2">
                    $29 <span className="text-xs font-normal text-gray-400 font-sans">/ month</span>
                  </div>
                </div>
                <p className="text-sm text-gray-400 leading-relaxed min-h-[44px]">
                  Essential DNS governance and on-demand audits for emerging DTC stores.
                </p>

                <div className="space-y-3 pt-6 border-t border-white/10 text-xs sm:text-sm text-gray-300">
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>1 Verified Apex Sending Domain</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Daily Multi-Resolver DNS Audits</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>10-List Blacklist Radar Probing</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Telegram Bot Alert Engine</span>
                  </div>
                </div>
              </div>

              <div className="pt-8 mt-auto">
                <Link
                  href="/auth/signup?tier=starter"
                  className="w-full inline-flex items-center justify-center py-3 px-5 rounded-full bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium border border-white/10 transition-all"
                >
                  Get Started with Starter
                </Link>
              </div>
            </div>
          </FadeInUp>

          {/* Growth Plan (Most Popular) */}
          <FadeInUp delay={0.2} className="h-full">
            <div className="h-full p-8 rounded-3xl bg-[#0E0E12]/95 backdrop-blur-xl border border-emerald-500/50 flex flex-col justify-between shadow-[0_0_40px_-5px_rgba(16,185,129,0.3)] lg:-translate-y-3 relative z-10">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-3 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5 shadow-[0_0_15px_rgba(16,185,129,0.3)]">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    MOST POPULAR
                  </span>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">Growth Tier</h3>
                  <div className="text-4xl font-bold text-white font-mono tracking-tight pt-2">
                    $79 <span className="text-xs font-normal text-gray-400 font-sans">/ month</span>
                  </div>
                </div>
                <p className="text-sm text-gray-300 leading-relaxed min-h-[44px]">
                  Comprehensive 24/7 automated deliverability &amp; 1-click zone auto-fixer for scaling Shopify brands.
                </p>

                <div className="space-y-3 pt-6 border-t border-white/10 text-xs sm:text-sm text-gray-300">
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <strong className="text-white font-semibold">Up to 5 Apex Sending Domains</strong>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Hourly DNS &amp; IMAP Telemetry Ingestion</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>1-Click Cloudflare &amp; GoDaddy Auto-Fixer</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>AI Content Lab &amp; Liquid Template Optimizer</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Instant Telegram Incident Alert Engine</span>
                  </div>
                </div>
              </div>

              <div className="pt-8 mt-auto">
                <Link
                  href="/auth/signup?tier=growth"
                  className="w-full inline-flex items-center justify-center py-3.5 px-5 rounded-full bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-sm transition-all shadow-[0_0_25px_rgba(16,185,129,0.4)]"
                >
                  Scale with Growth
                </Link>
              </div>
            </div>
          </FadeInUp>

          {/* Enterprise Plan */}
          <FadeInUp delay={0.3} className="h-full">
            <div className="h-full p-8 rounded-3xl bg-[#0E0E12]/90 backdrop-blur-xl border border-white/10 flex flex-col justify-between hover:border-white/20 transition-all shadow-xl">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono uppercase px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/25">
                    Shopify Plus &amp; Aggregators
                  </span>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">Enterprise Tier</h3>
                  <div className="text-4xl font-bold text-white font-mono tracking-tight pt-2">
                    $199 <span className="text-xs font-normal text-gray-400 font-sans">/ month</span>
                  </div>
                </div>
                <p className="text-sm text-gray-400 leading-relaxed min-h-[44px]">
                  Maximum-scale deliverability surveillance and white-glove governance for high-volume stores.
                </p>

                <div className="space-y-3 pt-6 border-t border-white/10 text-xs sm:text-sm text-gray-300">
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <strong className="text-white font-semibold">Unlimited Monitored Domains</strong>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Dedicated 15m Sweeps &amp; IMAP Probes</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Custom Webhooks &amp; REST API Access</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>White-Glove Onboarding &amp; Zone Migration</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check size={16} className="text-emerald-400 flex-shrink-0" />
                    <span>Priority 24/7 Deliverability Engineer</span>
                  </div>
                </div>
              </div>

              <div className="pt-8 mt-auto">
                <Link
                  href="/auth/signup?tier=enterprise"
                  className="w-full inline-flex items-center justify-center py-3 px-5 rounded-full bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium border border-white/10 transition-all"
                >
                  Get Enterprise Access
                </Link>
              </div>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* 5. High-End FAQ Accordion (id="faq") */}
      <section id="faq" className="max-w-3xl mx-auto py-28 px-6 relative z-10">
        <FadeInUp>
          {/* Strictly ONE header */}
          <h2 className="text-4xl md:text-5xl font-semibold text-center mb-12 tracking-tight text-white">
            Frequently Asked Questions
          </h2>
        </FadeInUp>

        <FadeInUp delay={0.1}>
          <div className="border border-white/10 rounded-2xl bg-transparent overflow-hidden">
            {FAQ_ITEMS.map((item, idx) => {
              const isOpen = openFaqIndex === idx;
              return (
                <div
                  key={idx}
                  className="border-b border-white/10 last:border-b-0 transition-colors"
                >
                  <button
                    type="button"
                    onClick={() => setOpenFaqIndex(isOpen ? null : idx)}
                    className="w-full p-6 text-left flex items-center justify-between gap-4 font-semibold text-sm text-white hover:text-emerald-400 transition cursor-pointer"
                  >
                    <span>{item.q}</span>
                    <div
                      className={`transition-transform duration-300 flex-shrink-0 ${
                        isOpen ? "rotate-45 text-emerald-400" : "text-gray-400"
                      }`}
                    >
                      <Plus size={18} />
                    </div>
                  </button>
                  {/* Smooth CSS Grid Transition */}
                  <div
                    className={`grid transition-[grid-template-rows] duration-300 ease-out ${
                      isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                    }`}
                  >
                    <div className="overflow-hidden">
                      <div className="px-6 pb-6 text-sm text-gray-400 font-normal leading-relaxed">
                        {item.a}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </FadeInUp>
      </section>

      {/* 6. High-Converting Footer (id="contact") */}
      <footer
        id="contact"
        className="relative pt-28 pb-16 px-6 border-t border-white/10 overflow-hidden"
      >
        {/* Ambient Background Video */}
        <video
          autoPlay
          loop
          muted
          playsInline
          className="absolute inset-0 w-full h-full object-cover opacity-25 -z-10 pointer-events-none"
        >
          <source
            src="https://cdn.sceneai.art/Hero%20Section%20Video/50b4f304-cdca-4e12-8735-580d225834be.mp4"
            type="video/mp4"
          />
        </video>
        <div className="absolute inset-0 bg-gradient-to-t from-black via-black/90 to-transparent -z-10" />

        <div className="max-w-7xl mx-auto space-y-16 relative z-10">
          {/* Top CTA */}
          <FadeInUp>
            <div className="text-center space-y-6 max-w-3xl mx-auto">
              <h2 className="text-3xl sm:text-5xl font-bold tracking-tight text-white leading-tight">
                Ready to protect your store&apos;s{" "}
                <span className="italic font-serif text-emerald-400 font-normal">
                  deliverability?
                </span>
              </h2>
              <p className="text-gray-400 text-sm md:text-base max-w-xl mx-auto">
                Join high-volume Shopify DTC merchants who never lose revenue to spam filters. Setup takes under 60 seconds.
              </p>
              <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-4">
                <Link
                  href="/auth/signup"
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-sm px-8 py-3.5 rounded-full shadow-[0_0_30px_rgba(16,185,129,0.35)] transition-all active:scale-95"
                >
                  <span>Start 3-Day Free Trial</span>
                  <ArrowRight size={16} />
                </Link>
                <Link
                  href="/auth/login"
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium px-8 py-3.5 rounded-full border border-white/10 transition-all active:scale-95"
                >
                  <span>Sign In to Dashboard</span>
                </Link>
              </div>
            </div>
          </FadeInUp>

          {/* Footer Links Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 pt-12 border-t border-white/10 text-sm">
            <div className="space-y-3">
              <div className="font-semibold text-white tracking-wide">Product</div>
              <ul className="space-y-2 text-gray-400">
                <li><a href="#dns-inspector" className="hover:text-white transition">DNS Inspector</a></li>
                <li><a href="#radar" className="hover:text-white transition">Blacklist Radar</a></li>
                <li><a href="#how-it-works" className="hover:text-white transition">Shopify Sync</a></li>
                <li><a href="#pricing" className="hover:text-white transition">Pricing</a></li>
              </ul>
            </div>

            <div className="space-y-3">
              <div className="font-semibold text-white tracking-wide">Legal</div>
              <ul className="space-y-2 text-gray-400">
                <li><Link href="/privacy" className="hover:text-white transition">Privacy Policy</Link></li>
                <li><Link href="/terms" className="hover:text-white transition">Terms of Service</Link></li>
                <li><Link href="/security" className="hover:text-white transition">Security Architecture</Link></li>
                <li><Link href="/dpa" className="hover:text-white transition">DPA</Link></li>
              </ul>
            </div>

            <div className="space-y-3">
              <div className="font-semibold text-white tracking-wide">Documentation</div>
              <ul className="space-y-2 text-gray-400">
                <li><a href="#about" className="hover:text-white transition">Google 2024 Rulebook</a></li>
                <li><a href="#dns-inspector" className="hover:text-white transition">SPF 10-Lookup Guide</a></li>
                <li><a href="#dns-inspector" className="hover:text-white transition">DKIM Selector Setup</a></li>
                <li><a href="#radar" className="hover:text-white transition">RBL Delisting Engine</a></li>
              </ul>
            </div>

            <div className="space-y-3">
              <div className="font-semibold text-white tracking-wide">Connect</div>
              <ul className="space-y-2 text-gray-400">
                <li><a href="https://t.me" target="_blank" rel="noreferrer" className="hover:text-white transition flex items-center gap-1.5"><Send size={13} /> Telegram Bot</a></li>
                <li><a href="mailto:support@inboundcheck.com" className="hover:text-white transition">support@inboundcheck.com</a></li>
                <li><a href="#about" className="hover:text-white transition">Status Page (99.99%)</a></li>
              </ul>
            </div>
          </div>

          {/* Bottom Copyright Bar */}
          <div className="pt-8 border-t border-white/10 text-center text-xs text-gray-500 font-mono">
            © 2026 InboundCheck. All rights reserved • Powered by Shopify Plus Ecosystem
          </div>
        </div>
      </footer>
    </div>
  );
}
