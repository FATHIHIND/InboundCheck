import Link from "next/link";
import { ArrowLeft, FileText, CheckCircle2, Clock, AlertTriangle, Scale } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service | InboundCheck",
  description:
    "Subscription terms, 3-day free trial conditions, and service level agreements for InboundCheck.",
};

export default function TermsOfServicePage() {
  return (
    <div className="min-h-screen bg-[#050507] text-zinc-300 antialiased selection:bg-emerald-500/20 selection:text-emerald-300 font-sans">
      {/* Top Header */}
      <header className="border-b border-white/[0.06] bg-[#08080A]/80 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-4xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-xs font-mono text-zinc-400 hover:text-white transition group"
          >
            <ArrowLeft className="w-3.5 h-3.5 group-hover:-translate-x-1 transition-transform" />
            Back to InboundCheck
          </Link>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs font-mono text-emerald-400 font-bold uppercase tracking-wider">
              Legal Agreement
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-6 py-12 space-y-8">
        {/* Title Hero */}
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono">
            <Scale className="w-3.5 h-3.5" />
            Merchant Service Agreement
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
            Terms of Service
          </h1>
          <p className="text-sm font-mono text-zinc-400">
            Last Updated: September 2026 • Version 3.1
          </p>
        </div>

        {/* Content Body */}
        <div className="obsidian-card rounded-2xl border border-white/[0.08] bg-[#0B0B0E]/80 backdrop-blur-xl p-6 sm:p-10 space-y-8 text-sm leading-relaxed text-zinc-300">
          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Clock className="w-4 h-4 text-emerald-400" />
              1. 3-Day Free Trial Terms &amp; Billing Lifecycle
            </h2>
            <p>
              InboundCheck provides a risk-free 3-day trial for new merchant accounts:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Full Feature Access:</strong> Trial accounts receive complete access to DNS audits, SPF consolidation merge tools, and Blacklist Radar monitoring.</li>
              <li><strong>Billing Commencement:</strong> At the expiration of the 3-day trial period, the selected plan tier (Starter at $9/mo, Growth at $29/mo, or Agency at $79/mo) will be billed via Stripe unless cancelled prior to expiration.</li>
              <li><strong>Cancellation &amp; Refunds:</strong> You may cancel anytime directly through the Stripe Customer Portal inside the Billing dashboard. Subscription cancellations take effect at the end of the current billing cycle.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              2. Service Scope &amp; Deliverability SLAs
            </h2>
            <p>
              InboundCheck supplies continuous automated DNS diagnostics, SPF/DKIM/DMARC governance, and real-time deliverability risk analytics:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Availability Target:</strong> We target 99.99% uptime for our multi-resolver DNS diagnostic engine and webhook ingestion workers.</li>
              <li><strong>Third-Party Mailbox Algorithms:</strong> While InboundCheck ensures strict compliance with RFC 1035 and 2024 Google/Yahoo mailbox deliverability standards, final inbox placement remains subject to mailbox providers’ proprietary machine learning and recipient engagement models.</li>
              <li><strong>1-Click DNS Remediation:</strong> Automatic zone editing via Cloudflare or GoDaddy APIs requires explicit merchant authorization. InboundCheck captures DNS zone rollback snapshots prior to applying any record modification.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              3. Acceptable Use &amp; Merchant Responsibilities
            </h2>
            <p>
              To maintain the integrity and high sender reputation of our platform, merchants agree that:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li>You will only monitor domains and Shopify stores that you own or have explicit authorization to govern.</li>
              <li>You will not use InboundCheck services to facilitate unsolicited commercial email (spam), phishing campaigns, or malicious domain spoofing.</li>
              <li>Any attempt to reverse-engineer our proprietary scoring models or perform Denial of Service attacks against our multi-resolver probe network will result in immediate tenant termination without refund.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <FileText className="w-4 h-4 text-emerald-400" />
              4. Limitation of Liability &amp; Disclaimers
            </h2>
            <p>
              InboundCheck is provided on an &ldquo;as-is&rdquo; and &ldquo;as-available&rdquo; basis. Under no circumstances will InboundCheck or its affiliates be liable for indirect, incidental, punitive, or consequential damages resulting from email service provider outages, customer spam markings, or DNS registrar service disruptions exceeding the subscription fees paid by the merchant over the preceding 30 calendar days.
            </p>
          </section>

          <section className="space-y-3 border-t border-white/[0.06] pt-6">
            <h2 className="text-base font-bold text-white">5. Governing Law &amp; Legal Contact</h2>
            <p className="text-zinc-400">
              These terms shall be governed by and construed in accordance with the laws of Delaware, United States. Direct formal legal inquiries to:{" "}
              <a
                href="mailto:legal@inboundcheck.com"
                className="text-emerald-400 hover:underline font-mono"
              >
                legal@inboundcheck.com
              </a>
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
