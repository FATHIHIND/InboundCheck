import Link from "next/link";
import { ArrowLeft, Shield, Lock, EyeOff, Database, Globe } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy | InboundCheck",
  description:
    "Zero-PII email deliverability governance privacy policy for Shopify Plus merchants and DTC brands.",
};

export default function PrivacyPolicyPage() {
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
              Zero-PII Verified
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-6 py-12 space-y-8">
        {/* Title Hero */}
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono">
            <Shield className="w-3.5 h-3.5" />
            Enterprise Privacy Standard
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
            Privacy Policy
          </h1>
          <p className="text-sm font-mono text-zinc-400">
            Effective Date: September 2026 • Version 3.1
          </p>
        </div>

        {/* Content Body */}
        <div className="obsidian-card rounded-2xl border border-white/[0.08] bg-[#0B0B0E]/80 backdrop-blur-xl p-6 sm:p-10 space-y-8 text-sm leading-relaxed text-zinc-300">
          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <EyeOff className="w-4 h-4 text-emerald-400" />
              1. Zero-PII Storage Architecture
            </h2>
            <p>
              InboundCheck is engineered from the ground up for strict data minimization. We do not store, harvest, or monetize your end customers’ Personally Identifiable Information (PII). When processing Shopify transactional order notifications or webhook events:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li>Customer email addresses are pseudonymized or hashed in memory.</li>
              <li>Credit card numbers, payment tokens, and billing addresses are never ingested or transmitted to our servers.</li>
              <li>Customer physical mailing addresses and private purchase items are strictly filtered prior to telemetry analysis.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Database className="w-4 h-4 text-emerald-400" />
              2. DNS Telemetry &amp; Deliverability Data Collected
            </h2>
            <p>
              To provide multi-resolver DNS audit services and spam filter diagnostics, InboundCheck collects and processes:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Public DNS Records:</strong> SPF TXT records, DKIM public key selectors, DMARC policy alignment, MX routing hosts, and BIMI certificates.</li>
              <li><strong>Reputation &amp; Blacklist Logs:</strong> Public DNSBL / RBL index status across Spamhaus, Barracuda, SpamCop, and related authoritative reputation databases.</li>
              <li><strong>Merchant Account Information:</strong> Merchant contact email, business name, Shopify myshopify.com domain, and billing subscription identifiers (managed via Stripe).</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Lock className="w-4 h-4 text-emerald-400" />
              3. DNS API Provider Credentials
            </h2>
            <p>
              When you opt to connect Cloudflare or GoDaddy credentials for 1-click automated DNS remediation:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li>API tokens and secret keys are encrypted at rest using AES-256 / Fernet envelope cryptography.</li>
              <li>Keys are never exposed in user-facing client state and are masked in transit (<code className="text-emerald-400">••••••••••••••••</code>).</li>
              <li>Credentials are used solely to inject or rollback DNS records explicitly confirmed by the merchant.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Globe className="w-4 h-4 text-emerald-400" />
              4. GDPR, CCPA &amp; International Compliance
            </h2>
            <p>
              In accordance with the European Union General Data Protection Regulation (GDPR) and the California Consumer Privacy Act (CCPA):
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Right to Deletion:</strong> Merchants can remove any monitored domain or request complete tenant account termination anytime via the dashboard.</li>
              <li><strong>Cryptographic Multi-Tenancy:</strong> All database queries are isolated with Supabase Row-Level Security (RLS) enforcing <code className="text-emerald-400">auth.uid() = user_id</code>.</li>
              <li><strong>Sub-processors:</strong> We utilize SOC-2 Type II certified sub-processors including Supabase (PostgreSQL hosting), Stripe (PCI-DSS Level 1 payment processing), and Cloudflare (edge delivery).</li>
            </ul>
          </section>

          <section className="space-y-3 border-t border-white/[0.06] pt-6">
            <h2 className="text-base font-bold text-white">5. Contact Our Privacy Officer</h2>
            <p className="text-zinc-400">
              If you have any questions regarding our zero-PII commitment or data processing policies, contact our privacy engineering team directly at:{" "}
              <a
                href="mailto:privacy@inboundcheck.com"
                className="text-emerald-400 hover:underline font-mono"
              >
                privacy@inboundcheck.com
              </a>
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
