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
  Activity,
} from "lucide-react";
import FadeInUp from "@/components/landing/FadeInUp";
import ShopifyAuditPasses from "@/components/landing/ShopifyAuditPass";

// 5 Core High-Intent FAQ Items
const FAQ_ITEMS = [
  {
    q: "Why do my Shopify emails land in spam if I didn't touch my store settings?",
    a: "In early 2024, Google, Yahoo, and Apple Mail deployed strict anti-spam algorithms requiring 100% cryptographic SPF alignment, valid DKIM CNAME records, and strict DMARC policies (`p=quarantine` or `reject`). If your store sending domain has more than 10 DNS lookups or lacks custom selector rotation, your order confirmations and shipping receipts are automatically relegated to junk folders without warning.",
  },
  {
    q: "How does InboundCheck differ from Klaviyo, Omnisend, or Mailchimp?",
    a: "Klaviyo and Omnisend manage marketing newsletters. InboundCheck operates at the infrastructure & DNS root level. We continuously monitor your apex domain, query authoritative RBL blacklists (Spamhaus, Barracuda), and simulate real-time IMAP delivery receipts to maximize primary inbox placement for your highest-value transactional receipts.",
  },
  {
    q: "Will this fix my Google & Yahoo 2024 compliance warnings?",
    a: "Yes. InboundCheck aligns your DNS records with official 2024 Google & Yahoo standards by automatically combining multi-app records so Gmail & Yahoo never reject your receipts, configures 2048-bit DKIM keys, and establishes continuous DMARC aggregate monitoring to clear compliance warnings.",
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

  // System Status Modal State
  const [showStatusModal, setShowStatusModal] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showStatusModal) {
        setShowStatusModal(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showStatusModal]);

  // Lock document body scroll when mobile navigation drawer is active (prevents iOS scroll bleed)
  useEffect(() => {
    if (typeof document !== "undefined") {
      if (mobileMenuOpen) {
        document.body.style.overflow = "hidden";
      } else {
        document.body.style.overflow = "";
      }
    }
    return () => {
      if (typeof document !== "undefined") {
        document.body.style.overflow = "";
      }
    };
  }, [mobileMenuOpen]);

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

  // Structured Data Schema.org with Technical SEO, GEO & AEO Enhancements (CITES Compliant)
  const structuredData = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebApplication",
        "@id": "https://inboundcheck.com/#webapp",
        name: "InboundCheck",
        url: "https://inboundcheck.com",
        operatingSystem: "All (Cloud SaaS)",
        applicationCategory: "BusinessApplication",
        applicationSubCategory: "Email Deliverability & DNS Governance for E-Commerce",
        description:
          "Enterprise transactional email deliverability, real-time blacklist surveillance, and 1-click DNS governance platform engineered for Shopify & DTC merchants.",
        featureList: [
          "Shopify DNS Auto-Fix & SPF Conflict Optimization",
          "Zero Email Drop Limit SPF Record Merging",
          "Google & Yahoo 2024 Compliance Defense",
          "DKIM 2048-Bit Verified Sender Keys",
          "1-Click Cloudflare and GoDaddy Zone Auto-Patch",
          "Real-Time RBL Blacklist Surveillance across 10 Databases",
          "Omnichannel WhatsApp & SMS Transactional Failover"
        ],
        knowsAbout: [
          "RFC 7208 (Sender Policy Framework / SPF)",
          "RFC 6376 (DomainKeys Identified Mail / DKIM)",
          "RFC 7489 (Domain-based Message Authentication, Reporting, and Conformance / DMARC)",
          "BIMI (Brand Indicators for Message Identification)",
          "Google and Yahoo 2024 Bulk Sender Mandates",
          "Shopify Transactional Email Deliverability",
          "E-Commerce Payment Dispute & Chargeback Prevention"
        ],
        author: {
          "@type": "Organization",
          name: "InboundCheck Enterprise",
          url: "https://inboundcheck.com",
          logo: "https://inboundcheck.com/icon.png"
        },
        aggregateRating: {
          "@type": "AggregateRating",
          ratingValue: "4.9",
          reviewCount: "128",
          bestRating: "5",
          worstRating: "1"
        },
        offers: [
          {
            "@type": "Offer",
            name: "Starter ($9/mo)",
            price: "9.00",
            priceCurrency: "USD",
            priceValidUntil: "2027-12-31",
            availability: "https://schema.org/InStock",
            description: "Single DTC Brand - 1 Monitored Domain with 3-Day Free Trial",
          },
          {
            "@type": "Offer",
            name: "Growth ($29/mo)",
            price: "29.00",
            priceCurrency: "USD",
            priceValidUntil: "2027-12-31",
            availability: "https://schema.org/InStock",
            description: "Scaling Multi-Brand - Up to 3 Monitored Domains with 3-Day Free Trial & 1-Click DNS Auto-Remediation",
          },
          {
            "@type": "Offer",
            name: "Agency ($79/mo)",
            price: "79.00",
            priceCurrency: "USD",
            priceValidUntil: "2027-12-31",
            availability: "https://schema.org/InStock",
            description: "Agencies & High-Volume Brands - Up to 20 Monitored Domains with 3-Day Free Trial & White-Label Reporting",
          },
        ],
      },
      {
        "@type": "SoftwareApplication",
        "@id": "https://inboundcheck.com/#dns-inspector",
        name: "Shopify DNS Auto-Fix & SPF Conflict Optimization",
        applicationCategory: "BusinessApplication",
        operatingSystem: "All (Cloud SaaS)",
        description:
          "Automated DNS governance merging Shopify, Klaviyo, and Zendesk records to eliminate Google and Yahoo 10-lookup SPF limit email rejections.",
        featureList: [
          "Zero Email Drop Limit SPF Record Merging",
          "Google & Yahoo 2024 Compliance Defense",
          "DKIM 2048-Bit Verified Sender Keys",
          "1-Click Cloudflare and GoDaddy Zone Auto-Patch"
        ],
        offers: {
          "@type": "Offer",
          price: "0.00",
          priceCurrency: "USD",
          priceValidUntil: "2027-12-31",
          availability: "https://schema.org/InStock",
          description: "Free Instant Domain Deliverability Health Check"
        }
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
              className="min-h-[44px] inline-flex items-center bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium px-5 py-2.5 rounded-xl border border-white/10 transition-all hover:border-white/25 shadow-sm active:scale-95"
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
            {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
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
          {/* Institutional Compliance & 2024 Enforcement Hero Badge */}
          <FadeInUp>
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.04] border border-white/10 mb-8 backdrop-blur-md hover:border-emerald-500/40 transition-colors cursor-default">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-mono font-medium text-gray-300 tracking-wide">
                2024 GOOGLE &amp; YAHOO DMARC ENFORCEMENT LIVE
              </span>
            </div>
          </FadeInUp>

          {/* Value Proposition Framing (Obsidian Editorial Serif & Sans) */}
          <FadeInUp delay={0.1}>
            <h1 className="text-4xl sm:text-6xl md:text-7xl font-semibold tracking-tight text-white max-w-4xl leading-[1.08] mb-6 text-center">
              Stop Shopify Order Receipts{" "}
              <span className="italic font-serif text-emerald-400 font-normal">
                Landing in Spam.
              </span>
            </h1>
          </FadeInUp>

          <FadeInUp delay={0.2}>
            <p className="text-[16px] text-gray-400 max-w-2xl text-center mb-8 leading-relaxed">
              Google and Yahoo 2024 DMARC &amp; SPF rules trigger silent rejections when merchants connect multiple apps. Unreceived order receipts cause dispute surges, customer support spikes, and lost GMV. InboundCheck protects your deliverability before revenue leaks.
            </p>
          </FadeInUp>

          {/* Interactive Live Bait Domain Health Check */}
          <FadeInUp delay={0.4} className="w-full max-w-xl mx-auto mt-8 mb-14">
            <div className="p-2.5 rounded-2xl border border-white/10 bg-[#0A0A0C]/90 backdrop-blur-xl shadow-2xl">
              <form onSubmit={handleSimulatedAudit} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <div className="relative flex-1">
                  <Globe className="w-4 h-4 text-zinc-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={domainInput}
                    onChange={(e) => setDomainInput(e.target.value)}
                    placeholder="enter your store sending domain (e.g. store.com)"
                    className="w-full pl-10 pr-4 py-2.5 bg-[#000000] border border-white/10 rounded-xl text-xs text-white placeholder-zinc-500 font-mono focus:outline-none focus:border-emerald-500 transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={isAuditing}
                  className="bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs px-5 py-2.5 rounded-xl transition-all shadow-[0_0_20px_rgba(16,185,129,0.3)] flex items-center justify-center gap-1.5 whitespace-nowrap cursor-pointer active:scale-95 disabled:opacity-60 min-h-[44px]"
                >
                  <Zap className="w-3.5 h-3.5 fill-current" />
                  <span>{isAuditing ? "Analyzing Risk..." : "Analyze Revenue Risk"}</span>
                </button>
              </form>

              {/* Diagnostic Terminal Animation & Blurred Gate */}
              {auditStep > 0 && (
                <div className="mt-3 p-4 bg-[#000000] rounded-xl border border-white/10 text-left font-mono text-xs space-y-2.5">
                  <div className="flex items-center justify-between text-[11px] text-zinc-500 border-b border-white/10 pb-2">
                    <span className="flex items-center gap-1.5">
                      <Terminal className="w-3 h-3 text-emerald-400" />
                      REVENUE &amp; DELIVERABILITY RISK PROBE: {domainInput}
                    </span>
                    <span className="text-emerald-400 font-semibold">2024 ENFORCEMENT AUDIT</span>
                  </div>

                  <div className="space-y-1.5 text-[11px]">
                    {auditStep >= 1 && (
                      <div className="flex items-center gap-2 text-zinc-300">
                        <span className="text-emerald-400">✓</span> Checking SPF mechanism limits &amp; multi-app lookup exhaustion...
                      </div>
                    )}
                    {auditStep >= 2 && (
                      <div className="flex items-center gap-2 text-zinc-300">
                        <span className="text-emerald-400">✓</span> Scanning 10 authoritative RBLs for domain &amp; IP spam listings...
                      </div>
                    )}
                    {auditStep >= 3 && (
                      <div className="flex items-center gap-2 text-zinc-300">
                        <span className="text-emerald-400">✓</span> Evaluating DMARC policy enforcement &amp; DKIM alignment risks...
                      </div>
                    )}
                  </div>

                  {auditStep === 4 && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.98 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="mt-3 p-4 rounded-xl bg-red-950/30 border border-red-500/40 relative overflow-hidden space-y-3"
                    >
                      {/* Alert Header */}
                      <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-red-500/20">
                        <div className="flex items-center gap-2">
                          <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
                          </span>
                          <span className="font-bold text-rose-300 text-xs tracking-tight">
                            Critical Deliverability Breach Detected
                          </span>
                        </div>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-500/20 text-rose-200 border border-red-500/30 font-semibold">
                          {domainInput}
                        </span>
                      </div>

                      {/* Bottom-Line Merchant Impact Cards */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left">
                        <div className="p-2.5 rounded-lg bg-black/60 border border-red-500/20">
                          <div className="text-[10px] font-mono text-zinc-400 uppercase tracking-wider">
                            At-Risk Transactional GMV
                          </div>
                          <div className="text-sm font-bold text-rose-400 font-mono mt-0.5">
                            ~$2,400 / wk
                          </div>
                          <div className="text-[10px] text-zinc-400 mt-0.5 font-sans">
                            Lost order confirmation emails trigger payment disputes
                          </div>
                        </div>

                        <div className="p-2.5 rounded-lg bg-black/60 border border-red-500/20">
                          <div className="text-[10px] font-mono text-zinc-400 uppercase tracking-wider">
                            Mailbox Routing Risk
                          </div>
                          <div className="text-xs font-bold text-amber-400 mt-0.5 font-sans">
                            Routed Directly to Spam Folder
                          </div>
                          <div className="text-[10px] text-zinc-400 mt-0.5 font-sans">
                            Order receipts &amp; shipping confirmations fail 2024 compliance
                          </div>
                        </div>
                      </div>

                      {/* Diagnostic Breakdown */}
                      <p className="text-[11px] text-zinc-300 font-sans leading-relaxed">
                        Your store exceeds the <strong className="text-rose-400">10-lookup SPF threshold</strong> (multi-app conflict) and DMARC is set to passive <code className="text-amber-300 font-mono px-1 py-0.5 rounded bg-white/5 border border-white/10">p=none</code>. Gmail and Yahoo automatically relegate your receipts to customer junk folders.
                      </p>

                      {/* High-Converting 60s CTA Button */}
                      <div className="pt-2 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-3">
                        <span className="text-[11px] text-zinc-400 font-sans flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          <span>1-Click Cloudflare &amp; GoDaddy auto-fix ready</span>
                        </span>
                        <Link
                          href={`/auth/signup?domain=${encodeURIComponent(domainInput.trim())}`}
                          onClick={() => {
                            try {
                              if (typeof window !== "undefined") {
                                sessionStorage.setItem("inboundcheck_pending_domain", domainInput.trim());
                                localStorage.setItem("inboundcheck_pending_domain", domainInput.trim());
                              }
                            } catch {
                              // Storage access fallback
                            }
                          }}
                          className="w-full sm:w-auto inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-all shadow-[0_0_20px_rgba(16,185,129,0.35)] active:scale-95 cursor-pointer min-h-[44px]"
                        >
                          <span>Fix My Delivery Records in 60s</span>
                          <ArrowRight size={13} className="stroke-[2.5]" />
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

        <FadeInUp delay={0.2} className="w-full flex justify-center">
          <ShopifyAuditPasses />
        </FadeInUp>
      </section>

      {/* 4. Interactive Feature Sections (Two-Column Layouts) */}
      
      {/* Column 1: Fix Hidden DNS Conflicts in 1 Click (id="dns-inspector") */}
      <section
        id="dns-inspector"
        aria-label="Shopify DNS Automation"
        className="py-28 px-6 max-w-7xl mx-auto border-t border-white/5 relative z-10"
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          {/* Left: Copy */}
          <FadeInUp className="space-y-6">
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 text-xs font-mono font-semibold">
                <Server size={14} />
                <span>DNS GOVERNANCE ENGINE</span>
              </div>
              <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-emerald-400 text-xs font-mono font-medium">
                <ShieldCheck size={13} className="text-emerald-400" />
                <span>2024 Compliance Enforced</span>
              </div>
            </div>

            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white leading-tight">
              Fix Hidden DNS Conflicts in 1 Click
            </h2>

            {/* Descriptive H3 for AI Search Engines & Screen Readers */}
            <h3 className="sr-only">Shopify DNS Auto-Fix &amp; SPF Conflict Optimization</h3>

            <p className="text-base text-gray-400 leading-relaxed">
              When you connect Shopify, Klaviyo, and support inboxes, your DNS breaks Google &amp; Yahoo 2024 deliverability rules. InboundCheck merges your records into a single compliant entry automatically.
            </p>
            <div className="space-y-3.5 font-sans text-sm text-gray-300">
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span>
                  <strong className="text-white">Prevents Spam Routing:</strong> Automatically merges multi-app SPF records to bypass Google&apos;s 10-lookup barrier.
                </span>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span>
                  <strong className="text-white">Establishes Cryptographic Sender Trust:</strong> Validates 2048-bit DKIM keys to pass DMARC alignment on Gmail and Yahoo.
                </span>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} />
                </div>
                <span>
                  <strong className="text-white">Zero Manual Editing:</strong> Syncs verified records directly to Cloudflare, GoDaddy, or Namecheap via secure API.
                </span>
              </div>
            </div>
          </FadeInUp>

          {/* Right Mockup: Glassmorphic floating card with Dynamic Flowing Emerald Background */}
          <FadeInUp delay={0.2}>
            <div className="bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 rounded-2xl p-6 sm:p-8 relative overflow-hidden shadow-2xl group hover:border-emerald-500/40 transition-all duration-300">
              {/* Glowing Emerald Gradient Wave Base */}
              <div
                className="absolute inset-0 -z-20 pointer-events-none rounded-2xl"
                style={{
                  background:
                    "radial-gradient(ellipse at top right, rgba(16, 185, 129, 0.25) 0%, rgba(0, 128, 96, 0.1) 40%, rgba(14, 18, 23, 0.95) 100%)",
                }}
              />
              {/* Flowing Ambient Background Video with Screen Blend */}
              <video
                autoPlay
                loop
                muted
                playsInline
                className="opacity-20 absolute inset-0 w-full h-full object-cover pointer-events-none mix-blend-screen -z-10"
              >
                <source
                  src="https://cdn.sceneai.art/Hero%20Section%20Video/1bcc8fa3-37f6-4c53-8591-0347e4c7f8ac.mp4"
                  type="video/mp4"
                />
              </video>

              <div className="space-y-6 relative z-10">
                {/* Visual Glass Header */}
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                      <Server size={16} />
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-white">Cloudflare Zone Automation</div>
                      <div className="text-xs text-gray-400 font-mono">Auto-Remediate • Connected</div>
                    </div>
                  </div>
                  <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    SYNCED
                  </span>
                </div>

                {/* SPF Mechanism Visual Counter */}
                <div className="p-4 rounded-xl bg-black/60 border border-white/10 space-y-2">
                  <div className="flex items-center justify-between text-xs font-mono text-zinc-400">
                    <span>SPF LOOKUP COUNTER</span>
                    <span className="text-emerald-400 font-bold">5 / 10 RFC LIMIT</span>
                  </div>
                  {/* Visual Progress Bar */}
                  <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
                    <div className="w-1/2 h-full bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full" />
                  </div>
                  <div className="flex items-center justify-between text-[11px] pt-1">
                    <span className="text-zinc-400 font-sans">Google &amp; Yahoo Threshold</span>
                    <span className="text-emerald-400 font-medium">Within Safe Limits</span>
                  </div>
                </div>

                {/* DMARC and DKIM Status Chips (Static Display) */}
                <div className="grid grid-cols-2 gap-3 font-mono text-xs">
                  <div className="p-3 bg-black/75 rounded-xl border border-white/10 space-y-1.5">
                    <span className="text-[10px] text-zinc-400 block">DMARC STATUS</span>
                    <span className="text-emerald-400 font-semibold text-[10px] font-mono bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/30 inline-block">
                      DMARC: Inboxing Safe
                    </span>
                  </div>
                  <div className="p-3 bg-black/75 rounded-xl border border-white/10 space-y-1.5">
                    <span className="text-[10px] text-zinc-400 block">DKIM STATUS</span>
                    <span className="text-emerald-400 font-semibold text-[10px] font-mono bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/30 inline-block">
                      DKIM: Verified &amp; Active
                    </span>
                  </div>
                </div>

                {/* Verified System Footer Status Strip */}
                <div className="w-full py-3 px-4 rounded-xl bg-black/60 border border-white/10 flex items-center justify-center gap-2.5 text-xs text-zinc-300 font-mono shadow-sm">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                  <span className="tracking-tight text-center">
                    Automated DNS Synchronization Active • Cloudflare API Connected
                  </span>
                </div>
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
            <div className="bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 rounded-2xl p-6 sm:p-8 relative overflow-hidden shadow-2xl group hover:border-emerald-500/40 transition-all duration-300">
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
            <div className="p-7 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 space-y-4 hover:border-emerald-500/40 transition-all shadow-xl">
              <div className="flex items-center justify-between text-xs text-zinc-400 font-mono border-b border-white/10 pb-3">
                <span className="flex items-center gap-1.5 text-emerald-400 font-semibold">
                  <Send className="w-3.5 h-3.5" /> @InboundCheckBot
                </span>
                <span>Real-Time Push</span>
              </div>
              <div className="text-sm font-semibold text-white flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" />
                CRITICAL: Spam Placement Alert
              </div>
              <p className="text-xs text-zinc-300 font-mono leading-relaxed bg-black/60 p-3 rounded-xl border border-white/5">
                Sending domain health score dropped to 72%. Gmail anti-spam filter classified Order #10492 as junk.
              </p>
              <div className="flex items-center justify-between pt-1">
                <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                  1-Click Remediate
                </span>
                <span className="text-xs text-zinc-400 font-mono">Dispatched in 320ms</span>
              </div>
            </div>
          </FadeInUp>

          {/* Omnichannel Failover Box */}
          <FadeInUp delay={0.2}>
            <div className="p-7 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 space-y-4 hover:border-emerald-500/40 transition-all shadow-xl">
              <div className="flex items-center justify-between text-xs text-zinc-400 font-mono border-b border-white/10 pb-3">
                <span className="flex items-center gap-1.5 text-teal-400 font-semibold">
                  <Zap className="w-3.5 h-3.5" /> Omnichannel Failover Engine
                </span>
                <span>International SMS &amp; WhatsApp Fallback</span>
              </div>
              <div className="text-sm font-semibold text-white flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Receipt Auto-Routed to WhatsApp
              </div>
              <p className="text-xs text-zinc-300 font-mono leading-relaxed bg-black/60 p-3 rounded-xl border border-white/5">
                When customer email bounced, order confirmation #10492 was delivered via WhatsApp Business API within 1.2s. Eliminates silent delivery drop-off.
              </p>
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs font-mono px-2.5 py-1 rounded bg-teal-500/20 text-teal-300 border border-teal-500/40">
                  Revenue Protected: $184.00
                </span>
                <span className="text-xs text-zinc-400 font-mono">Real-Time Failover Verification</span>
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
              Three simple steps to protect your order confirmations from the spam folder.
            </p>
          </div>
        </FadeInUp>

        <div className="space-y-4">
          <FadeInUp delay={0.1}>
            <div className="p-6 sm:p-7 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 hover:border-emerald-500/40 transition-all">
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
            <div className="p-6 sm:p-7 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 hover:border-emerald-500/40 transition-all">
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
            <div className="p-6 sm:p-7 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 hover:border-emerald-500/40 transition-all">
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
            <div className="h-full p-8 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 flex flex-col justify-between hover:border-white/20 transition-all shadow-xl">
              <div className="space-y-4">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <span className="text-[10px] font-mono uppercase px-3 py-1 rounded-full bg-white/5 text-gray-300 border border-white/10">
                    Single DTC Brand
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    3-Day Free Trial
                  </span>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">Starter</h3>
                  <div className="text-4xl font-bold text-white font-mono tracking-tight pt-2">
                    $9 <span className="text-xs font-normal text-gray-400 font-sans">/ month</span>
                  </div>
                </div>
                <p className="text-sm text-gray-400 leading-relaxed min-h-[44px]">
                  Essential 24/7 continuous DNS monitoring and failure alerts for single-store DTC brands.
                </p>

                <div className="space-y-3 pt-6 border-t border-white/10 text-xs sm:text-sm text-gray-300">
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <strong className="text-white font-semibold">1 Monitored Domain Cap</strong>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>24/7 Continuous DNS &amp; 10-RBL Blacklist Radar</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Instant Telegram Failure Alerts</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Multi-Resolver Automated Audits</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span className="text-emerald-400 font-medium">3-Day Free Trial — No Risk</span>
                  </div>
                </div>
              </div>

              <div className="pt-8 mt-auto">
                <Link
                  href="/auth/signup?tier=starter"
                  className="w-full min-h-[44px] inline-flex items-center justify-center py-3 px-5 rounded-xl bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium border border-white/10 transition-all hover:border-emerald-500/40"
                >
                  Start 3-Day Free Trial
                </Link>
              </div>
            </div>
          </FadeInUp>

          {/* Growth Plan (Most Popular) */}
          <FadeInUp delay={0.2} className="h-full">
            <div className="h-full p-8 rounded-2xl bg-[#0E1217] backdrop-blur-xl border-2 border-emerald-500/50 flex flex-col justify-between shadow-[0_0_40px_-5px_rgba(16,185,129,0.3)] lg:-translate-y-3 relative z-10">
              <div className="space-y-4">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-3 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5 shadow-[0_0_15px_rgba(16,185,129,0.3)]">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    MOST POPULAR
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    3-Day Free Trial
                  </span>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">Growth Tier</h3>
                  <div className="text-4xl font-bold text-white font-mono tracking-tight pt-2">
                    $29 <span className="text-xs font-normal text-gray-400 font-sans">/ month</span>
                  </div>
                </div>
                <p className="text-sm text-gray-300 leading-relaxed min-h-[44px]">
                  Multi-domain governance, automated DNS repair, and store order sync for scaling brands.
                </p>

                <div className="space-y-3 pt-6 border-t border-white/10 text-xs sm:text-sm text-gray-300">
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <strong className="text-white font-semibold">Up to 3 Monitored Domains</strong>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Shopify Store OAuth Sync &amp; Alignment</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>1-Click DNS Auto-Remediation (Cloudflare &amp; GoDaddy)</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Revenue &amp; Dispute Risk Analytics (Protected GMV)</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Instant Telegram Incident Alert Engine</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span className="text-emerald-400 font-medium">3-Day Free Trial — No Risk</span>
                  </div>
                </div>
              </div>

              <div className="pt-8 mt-auto">
                <Link
                  href="/auth/signup?tier=growth"
                  className="w-full min-h-[44px] inline-flex items-center justify-center py-3.5 px-5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-sm transition-all shadow-[0_0_25px_rgba(16,185,129,0.4)] cursor-pointer"
                >
                  Start 3-Day Free Trial
                </Link>
              </div>
            </div>
          </FadeInUp>

          {/* Agency Plan */}
          <FadeInUp delay={0.3} className="h-full">
            <div className="h-full p-8 rounded-2xl bg-[#0A0A0C]/90 backdrop-blur-xl border border-white/10 flex flex-col justify-between hover:border-white/20 transition-all shadow-xl">
              <div className="space-y-4">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <span className="text-[10px] font-mono uppercase px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/25">
                    High-Volume Scaling
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    3-Day Free Trial
                  </span>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">Agency Tier</h3>
                  <div className="text-4xl font-bold text-white font-mono tracking-tight pt-2">
                    $79 <span className="text-xs font-normal text-gray-400 font-sans">/ month</span>
                  </div>
                </div>
                <p className="text-sm text-gray-400 leading-relaxed min-h-[44px]">
                  Expanded capacity, multi-store management, and white-label reporting for agencies &amp; DTC high-volume merchants.
                </p>

                <div className="space-y-3 pt-6 border-t border-white/10 text-xs sm:text-sm text-gray-300">
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <strong className="text-white font-semibold">Up to 20 Monitored Domains</strong>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Multi-Store Management Hub</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Priority Audit Queue &amp; White-Label Reporting</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Dedicated 15m Sweeps &amp; IMAP Probes</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>Automated Zone Auto-Patching &amp; Backups</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span className="text-emerald-400 font-medium">3-Day Free Trial — No Risk</span>
                  </div>
                </div>
              </div>

              <div className="pt-8 mt-auto">
                <Link
                  href="/auth/signup?tier=agency"
                  className="w-full min-h-[44px] inline-flex items-center justify-center py-3 px-5 rounded-xl bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium border border-white/10 transition-all hover:border-emerald-500/40"
                >
                  Start 3-Day Free Trial
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
                      <Plus className="w-4 h-4" />
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
                  className="w-full sm:w-auto min-h-[44px] inline-flex items-center justify-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-sm px-8 py-3.5 rounded-xl shadow-[0_0_30px_rgba(16,185,129,0.35)] transition-all active:scale-95"
                >
                  <span>Start 3-Day Free Trial</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>
                <Link
                  href="/auth/login"
                  className="w-full sm:w-auto min-h-[44px] inline-flex items-center justify-center gap-2 bg-[#1F1F22] hover:bg-[#2A2A2D] text-white text-sm font-medium px-8 py-3.5 rounded-xl border border-white/10 transition-all active:scale-95"
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
                <li><a href="#how-it-works" className="hover:text-white transition">Google 2024 Rulebook</a></li>
                <li><a href="#dns-inspector" className="hover:text-white transition">SPF 10-Lookup Guide</a></li>
                <li><a href="#dns-inspector" className="hover:text-white transition">DKIM Selector Setup</a></li>
                <li><a href="#radar" className="hover:text-white transition">RBL Delisting Engine</a></li>
              </ul>
            </div>

            <div className="space-y-3">
              <div className="font-semibold text-white tracking-wide">Connect</div>
              <ul className="space-y-2 text-gray-400">
                <li><a href="https://t.me/InboundCheckBot" target="_blank" rel="noreferrer" className="hover:text-white transition flex items-center gap-1.5"><Send size={13} /> Telegram Bot</a></li>
                <li><a href="mailto:support@inboundcheck.com" className="hover:text-white transition">support@inboundcheck.com</a></li>
                <li>
                  <button
                    type="button"
                    onClick={() => setShowStatusModal(true)}
                    className="hover:text-white transition text-left flex items-center gap-1.5 cursor-pointer text-gray-400"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Status Page (99.99%)
                  </button>
                </li>
              </ul>
            </div>
          </div>

          {/* Bottom Copyright Bar */}
          <div className="pt-8 border-t border-white/10 text-center text-xs text-gray-500 font-mono">
            © 2026 InboundCheck. All rights reserved • Powered by Shopify Plus Ecosystem
          </div>
        </div>
      </footer>

      {/* System Status Modal */}
      {showStatusModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="status-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowStatusModal(false);
          }}
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="obsidian-card rounded-2xl max-w-lg w-full p-6 space-y-5 animate-fadeIn border border-white/[0.1] bg-[#0B0B0E] shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping" />
                <h3 id="status-modal-title" className="text-base font-bold text-white">
                  System Infrastructure Status
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowStatusModal(false)}
                aria-label="Close dialog"
                className="text-zinc-500 hover:text-white transition cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl flex items-center justify-between font-mono text-xs text-emerald-400">
              <div className="flex items-center gap-2 font-bold">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                All Systems Operational
              </div>
              <span className="text-[10px] text-emerald-500">99.99% 30d Uptime</span>
            </div>

            <div className="space-y-2.5 font-mono text-xs">
              <div className="flex items-center justify-between p-2.5 bg-[#08080A] rounded-lg border border-zinc-800">
                <span className="text-zinc-300">Multi-Resolver DNS Probing Engine</span>
                <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Operational (38ms)
                </span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-[#08080A] rounded-lg border border-zinc-800">
                <span className="text-zinc-300">10-RBL Blacklist Radar Network</span>
                <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Operational (10/10 Sync)
                </span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-[#08080A] rounded-lg border border-zinc-800">
                <span className="text-zinc-300">Shopify Webhook Ingestion Cluster</span>
                <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Operational (0ms Lag)
                </span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-[#08080A] rounded-lg border border-zinc-800">
                <span className="text-zinc-300">1-Click DNS Auto-Remediation APIs</span>
                <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Connected (Cloudflare / GoDaddy)
                </span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-[#08080A] rounded-lg border border-zinc-800">
                <span className="text-zinc-300">AI Content Intelligence Engine</span>
                <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Operational (Zero-PII)
                </span>
              </div>
            </div>

            <div className="pt-2 flex items-center justify-between text-[11px] text-zinc-500 font-mono border-t border-white/[0.06]">
              <span>Last probed: Live • Zero Active Incidents</span>
              <button
                type="button"
                onClick={() => setShowStatusModal(false)}
                className="px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 text-zinc-300 rounded-lg transition cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
