import Link from "next/link";
import { ArrowLeft, Shield, Lock, Server, Cpu, CheckCircle2, Key, Terminal } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Security Architecture & Cryptographic Governance | InboundCheck",
  description:
    "Explore InboundCheck enterprise security controls: Fernet 256-bit encryption, anti-SSRF guards, and Supabase Row-Level Security.",
};

export default function SecurityPage() {
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
              OWASP ASVS Hardened
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
            Zero-Trust Enterprise Engineering
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
            Security Architecture &amp; Governance
          </h1>
          <p className="text-sm font-mono text-zinc-400">
            Defense-in-Depth Specification • Version 3.1
          </p>
        </div>

        {/* Content Body */}
        <div className="obsidian-card rounded-2xl border border-white/[0.08] bg-[#0B0B0E]/80 backdrop-blur-xl p-6 sm:p-10 space-y-8 text-sm leading-relaxed text-zinc-300">
          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Key className="w-4 h-4 text-emerald-400" />
              1. Fernet 256-Bit Envelope Encryption
            </h2>
            <p>
              To execute automated DNS fixes via Cloudflare and GoDaddy APIs without risking credential leakage:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li>All third-party tokens and API secrets are encrypted at rest using AES-256 in CBC mode with HMAC-SHA256 authenticated signatures (Fernet cryptography).</li>
              <li>Encryption keys are isolated in hardened environment variables and never checked into version control.</li>
              <li>Client UI views display strictly masked representations (<code className="text-emerald-400">••••••••••••••••</code>) with secret bytes wiped from browser memory.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Terminal className="w-4 h-4 text-emerald-400" />
              2. Anti-SSRF Defense &amp; Domain Normalization
            </h2>
            <p>
              InboundCheck protects internal network perimeters against Server-Side Request Forgery (SSRF):
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li>All user-supplied domain strings pass through rigorous RFC-compliant domain sanitizers prior to DNS resolution.</li>
              <li>Requests to loopback (<code className="text-emerald-400">127.0.0.1</code>), private subnets (<code className="text-emerald-400">10.0.0.0/8</code>, <code className="text-emerald-400">192.168.0.0/16</code>), link-local addresses, and cloud metadata services (<code className="text-emerald-400">169.254.169.254</code>) are unconditionally rejected.</li>
              <li>DNS query timeouts and concurrency limits protect backend resolvers against DNS amplification vectors.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Server className="w-4 h-4 text-emerald-400" />
              3. Supabase Row-Level Security (RLS) Isolation
            </h2>
            <p>
              Multi-tenancy is enforced at the PostgreSQL database engine layer:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li>Every monitored domain, audit log, failover incident, and DNS fix entry is bound to an authenticated tenant UID.</li>
              <li>Database policies enforce <code className="text-emerald-400">USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)</code>, preventing cross-tenant data access (IDOR / BOLA) even in the event of application logic defects.</li>
              <li>All backend API routers mandate cryptographically verified Supabase JWT Bearer tokens before parsing request payloads.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Lock className="w-4 h-4 text-emerald-400" />
              4. Edge Security, CORS &amp; Rate Limiting
            </h2>
            <p>
              Network endpoints are protected by enterprise security controls:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-400">
              <li><strong>Sliding-Window Rate Limiter:</strong> High-frequency API abuse is throttled (120 requests/minute per authenticated client).</li>
              <li><strong>Security Headers:</strong> Responses enforce <code className="text-emerald-400">X-Frame-Options: DENY</code>, <code className="text-emerald-400">X-Content-Type-Options: nosniff</code>, and strict Content Security Policies.</li>
              <li><strong>HMAC Webhook Verification:</strong> Shopify order webhooks and Stripe billing events require strict HMAC-SHA256 signature verification prior to execution.</li>
            </ul>
          </section>

          <section className="space-y-3 border-t border-white/[0.06] pt-6">
            <h2 className="text-base font-bold text-white">5. Responsible Disclosure Program</h2>
            <p className="text-zinc-400">
              We welcome coordinated vulnerability reports from security researchers. Submit findings to:{" "}
              <a
                href="mailto:security@inboundcheck.com"
                className="text-emerald-400 hover:underline font-mono"
              >
                security@inboundcheck.com
              </a>
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
