import Link from "next/link";
import { ArrowLeft, FileCheck, Shield, CheckCircle2, Server, Lock } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Data Processing Addendum (DPA) | InboundCheck",
  description:
    "GDPR Article 28 compliant Data Processing Addendum for high-volume Shopify DTC merchants and enterprise senders.",
};

export default function DpaPage() {
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
              GDPR Article 28
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-6 py-12 space-y-8">
        {/* Title Hero */}
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono">
            <FileCheck className="w-3.5 h-3.5" />
            Enterprise Compliance Addendum
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
            Data Processing Addendum (DPA)
          </h1>
          <p className="text-sm font-mono text-zinc-400">
            Standard Contractual Clauses &amp; GDPR Compliance • Version 3.1
          </p>
        </div>

        {/* Content Body */}
        <div className="obsidian-card rounded-2xl border border-white/[0.08] bg-[#0B0B0E]/80 backdrop-blur-xl p-6 sm:p-10 space-y-8 text-sm leading-relaxed text-zinc-300">
          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Shield className="w-4 h-4 text-emerald-400" />
              1. Scope &amp; Roles of the Parties
            </h2>
            <p>
              This Data Processing Addendum (&ldquo;DPA&rdquo;) supplements the InboundCheck Terms of Service and applies to the processing of personal data in connection with the deliverability governance and DNS monitoring services:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Merchant as Data Controller:</strong> The merchant acts as the Data Controller with respect to all customer email addresses, store metadata, and transactional recipient logs.</li>
              <li><strong>InboundCheck as Data Processor:</strong> InboundCheck acts as the Data Processor, processing transactional telemetry solely under the documented instructions of the merchant.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Lock className="w-4 h-4 text-emerald-400" />
              2. Technical &amp; Organizational Safeguards
            </h2>
            <p>
              InboundCheck implements industry-standard security measures to protect Customer Data against unauthorized access, loss, or alteration:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Zero-PII Hashing:</strong> Email identifiers are hashed via SHA-256 for inbox placement metrics with zero raw PII persisted in storage logs.</li>
              <li><strong>Encryption in Transit &amp; At Rest:</strong> TLS 1.3 encryption across all public endpoints and AES-256 / Fernet encryption for DNS provider credentials.</li>
              <li><strong>Logical Tenant Isolation:</strong> Supabase PostgreSQL Row-Level Security ensuring strict multi-tenant cryptographic boundary enforcement.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Server className="w-4 h-4 text-emerald-400" />
              3. Authorized Sub-Processors
            </h2>
            <p>
              Merchants authorize InboundCheck to engage the following trusted infrastructure sub-processors:
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono border border-zinc-800 rounded-lg overflow-hidden">
                <thead className="bg-[#08080A] text-zinc-400 border-b border-zinc-800">
                  <tr>
                    <th className="p-2.5">Sub-Processor</th>
                    <th className="p-2.5">Role</th>
                    <th className="p-2.5">Location</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-900 text-zinc-300">
                  <tr>
                    <td className="p-2.5 font-bold text-white">Supabase Inc.</td>
                    <td className="p-2.5">Managed PostgreSQL database &amp; Auth</td>
                    <td className="p-2.5">United States (AWS us-east-1)</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-bold text-white">Stripe Inc.</td>
                    <td className="p-2.5">Payment subscription processing</td>
                    <td className="p-2.5">United States</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-bold text-white">Cloudflare Inc.</td>
                    <td className="p-2.5">Edge CDN &amp; WAF security routing</td>
                    <td className="p-2.5">Global Edge Network</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              4. Data Deletion &amp; Incident Response
            </h2>
            <p>
              Upon termination of services or merchant request, InboundCheck will delete all tenant telemetry, audit logs, and associated provider credentials within 30 days. In the event of a confirmed security incident affecting merchant data, InboundCheck will notify affected merchants within 48 hours.
            </p>
          </section>

          <section className="space-y-3 border-t border-white/[0.06] pt-6">
            <h2 className="text-base font-bold text-white">5. DPA Execution &amp; Inquiries</h2>
            <p className="text-zinc-400">
              For high-volume merchants requiring an enterprise-signed countersignature of this DPA, please submit your request to:{" "}
              <a
                href="mailto:compliance@inboundcheck.com"
                className="text-emerald-400 hover:underline font-mono"
              >
                compliance@inboundcheck.com
              </a>
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
