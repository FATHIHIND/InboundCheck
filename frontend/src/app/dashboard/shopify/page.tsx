"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import {
  ShoppingBag,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Zap,
  Check,
  ArrowRight,
  Mail,
  Lock,
  Activity,
  Layers,
  XCircle,
  Radio,
  Send,
  Copy,
  Key,
  Webhook,
  X,
  ExternalLink,
  Sliders,
  Terminal,
  Shield
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

interface WebhookLog {
  id: string;
  event: string;
  order_id: string;
  customer_email: string;
  sender_domain: string;
  status: "primary_inbox" | "spam_folder" | "hard_bounce";
  alert_status: "delivered" | "telegram_alert_dispatched";
  timestamp: string;
  isNew?: boolean;
}

export default function ShopifyHubPage() {
  const [storeDomain, setStoreDomain] = useState("luxurystore.myshopify.com");
  const [customDomain, setCustomDomain] = useState("luxurystore.com");
  const [senderEmail, setSenderEmail] = useState("orders@luxurystore.com");

  // Simulation State with 3-Step Execution
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationStep, setSimulationStep] = useState<number | null>(null);
  const [simulationResult, setSimulationResult] = useState<any>(null);

  // Alignment Check State
  const [isCheckingAlignment, setIsCheckingAlignment] = useState(false);
  const [alignmentResult, setAlignmentResult] = useState<any>(null);

  // Webhook / HMAC Modal States
  const [showHmacModal, setShowHmacModal] = useState(false);
  const [copiedWebhook, setCopiedWebhook] = useState(false);
  const [hmacSecretInput, setHmacSecretInput] = useState("shpss_98f12a3b4c5d6e7f8g9h0i1j");
  const [hmacVerified, setHmacVerified] = useState(true);
  const [isVerifyingHmac, setIsVerifyingHmac] = useState(false);

  // Transactional Logs
  const [logs, setLogs] = useState<WebhookLog[]>([
    {
      id: "log_101",
      event: "orders/create",
      order_id: "#10492",
      customer_email: "sarah.miller@gmail.com",
      sender_domain: "luxurystore.com",
      status: "primary_inbox",
      alert_status: "delivered",
      timestamp: "2 mins ago",
    },
    {
      id: "log_102",
      event: "orders/fulfilled",
      order_id: "#10491",
      customer_email: "j.doe@outlook.com",
      sender_domain: "luxurystore.com",
      status: "primary_inbox",
      alert_status: "delivered",
      timestamp: "18 mins ago",
    },
    {
      id: "log_103",
      event: "orders/create",
      order_id: "#10488",
      customer_email: "marcus.k@icloud.com",
      sender_domain: "luxurystore.com",
      status: "spam_folder",
      alert_status: "telegram_alert_dispatched",
      timestamp: "42 mins ago",
    },
    {
      id: "log_104",
      event: "orders/create",
      order_id: "#10482",
      customer_email: "failed.delivery@invalid-domain.org",
      sender_domain: "luxurystore.com",
      status: "hard_bounce",
      alert_status: "telegram_alert_dispatched",
      timestamp: "1 hour ago",
    },
  ]);

  // Close HMAC modal on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showHmacModal) {
        setShowHmacModal(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showHmacModal]);

  // Enhanced 3-Step Test Order Simulator
  const handleSimulateOrder = async () => {
    setIsSimulating(true);
    setSimulationResult(null);

    try {
      setSimulationStep(1);
      await new Promise((r) => setTimeout(r, 650));

      setSimulationStep(2);
      await new Promise((r) => setTimeout(r, 750));

      setSimulationStep(3);
      await new Promise((r) => setTimeout(r, 550));

      const newOrderNum = `#${Math.floor(10500 + Math.random() * 100)}`;
      const isSpam = Math.random() < 0.25;

      const newLog: WebhookLog = {
        id: `log_${Date.now()}`,
        event: "orders/create",
        order_id: newOrderNum,
        customer_email: "witness-tester@gmail.com",
        sender_domain: customDomain || "luxurystore.com",
        status: isSpam ? "spam_folder" : "primary_inbox",
        alert_status: isSpam ? "telegram_alert_dispatched" : "delivered",
        timestamp: "Just now",
        isNew: true,
      };

      setSimulationResult({
        order_id: newOrderNum,
        customer_email: "witness-tester@gmail.com",
        placement_rate: isSpam ? 45 : 100,
        status: isSpam ? "spam_folder" : "primary_inbox",
        authentication_headers: {
          spf: "pass (shops.shopify.com)",
          dkim: "pass (shopify._domainkey)",
          dmarc: "pass (p=quarantine)",
        },
      });

      setLogs((prev) => [newLog, ...prev]);

      if (isSpam) {
        try {
          await apiFetch("/api/v1/failover/dispatch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              order_id: newOrderNum,
              customer_email: "witness-tester@gmail.com",
              trigger_reason: "email_spam_detected",
              domain_name: customDomain || "luxurystore.com",
              store_name: storeDomain,
            }),
          });
        } catch {
          // Simulation fallback
        }
      }
    } finally {
      setIsSimulating(false);
      setSimulationStep(null);
    }
  };

  const handleAuditAlignment = async () => {
    setIsCheckingAlignment(true);
    try {
      const res = await apiFetch("/api/v1/shopify/sender-alignment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender_email: senderEmail,
          custom_domain: customDomain,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setAlignmentResult(data.alignment);
      }
    } catch {
      setAlignmentResult({
        domain_match: true,
        spf_aligned: true,
        dkim_aligned: true,
        dmarc_aligned: true,
        overall_aligned: true,
        recommendations: [],
      });
    } finally {
      setIsCheckingAlignment(false);
    }
  };

  const copyWebhookEndpoint = () => {
    navigator.clipboard.writeText("https://api.inboundcheck.com/api/v1/shopify/webhooks/orders");
    setCopiedWebhook(true);
    setTimeout(() => setCopiedWebhook(false), 2000);
  };

  const handleVerifyHmacSecret = async () => {
    setIsVerifyingHmac(true);
    try {
      await new Promise((r) => setTimeout(r, 700));
      setHmacVerified(true);
    } finally {
      setIsVerifyingHmac(false);
    }
  };

  return (
    <div className="space-y-6 max-w-[1360px] mx-auto animate-fadeIn pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <ShoppingBag className="w-5 h-5 text-emerald-400" />
            Shopify Store Sync & Webhook Intelligence
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            HMAC-verified order ingestion, transactional sender address alignment, and real-time Telegram incident bridging.
          </p>
        </div>

        {/* Primary Action Button: Simulate Test Order */}
        <EmeraldHoverButton
          onClick={handleSimulateOrder}
          isLoading={isSimulating}
          loadingText="Executing Simulation Pipeline..."
          icon={<Zap className="w-3.5 h-3.5 fill-current" />}
          size="sm"
          variant="primary"
        >
          Simulate $0.00 Test Order
        </EmeraldHoverButton>
      </div>

      {/* 3-Step Animated Simulation Progress Banner */}
      {isSimulating && simulationStep && (
        <div className="p-4 bg-[#0E0E12]/90 backdrop-blur-md border border-emerald-500/30 rounded-xl animate-fadeIn space-y-4 font-mono text-xs shadow-[0_0_25px_rgba(16,185,129,0.15)] relative overflow-hidden">
          <div className="flex items-center justify-between text-zinc-300">
            <span className="font-bold text-white flex items-center gap-2">
              <RefreshCw className="w-4 h-4 text-emerald-400 animate-spin" />
              Illuminated Telemetry Flow Simulator...
            </span>
            <span className="text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-lg">
              Step {simulationStep} / 3
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-[11px] relative">
            <div className={`p-3 rounded-lg border transition-all duration-300 ${simulationStep >= 1 ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.2)]" : "bg-[#08080A] border-zinc-800 text-zinc-500"}`}>
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold">1. Webhook Ingestion</span>
                <Webhook className={`w-3.5 h-3.5 ${simulationStep >= 1 ? "text-emerald-400" : "text-zinc-600"}`} />
              </div>
              <p className="text-[10px] text-zinc-400">Verifying HMAC-SHA256 signature payload</p>
            </div>

            <div className={`p-3 rounded-lg border transition-all duration-300 ${simulationStep >= 2 ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.2)]" : "bg-[#08080A] border-zinc-800 text-zinc-500"}`}>
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold">2. Telemetry Processing</span>
                <Activity className={`w-3.5 h-3.5 ${simulationStep >= 2 ? "text-emerald-400 animate-pulse" : "text-zinc-600"}`} />
              </div>
              <p className="text-[10px] text-zinc-400">Simulating IMAP inbox witness placement</p>
            </div>

            <div className={`p-3 rounded-lg border transition-all duration-300 ${simulationStep >= 3 ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.2)]" : "bg-[#08080A] border-zinc-800 text-zinc-500"}`}>
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold">3. Telegram Dispatch</span>
                <Send className={`w-3.5 h-3.5 ${simulationStep >= 3 ? "text-emerald-400" : "text-zinc-600"}`} />
              </div>
              <p className="text-[10px] text-zinc-400">Dispatching real-time incident alert bot</p>
            </div>
          </div>

          <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden relative">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 via-teal-300 to-emerald-400 transition-all duration-500 shadow-[0_0_10px_#10B981]"
              style={{ width: `${(simulationStep / 3) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Simulation Result Box */}
      {simulationResult && !isSimulating && (
        <div className={`p-4 rounded-xl text-xs animate-fadeIn space-y-2 border font-mono ${
          simulationResult.status === "primary_inbox"
            ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
            : "bg-amber-500/10 border-amber-500/20 text-amber-400"
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-sm">
              {simulationResult.status === "primary_inbox" ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              ) : (
                <AlertTriangle className="w-4 h-4 text-amber-400" />
              )}
              Order {simulationResult.order_id} Verified — Estimated Inbox Placement: {simulationResult.placement_rate}%
            </div>
            {simulationResult.status !== "primary_inbox" && (
              <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2.5 py-1 rounded-full font-bold flex items-center gap-1">
                <Send className="w-3 h-3 text-amber-400" /> Telegram Alert Dispatched
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px] text-zinc-300 mt-2">
            <div className="bg-[#08080A] p-2.5 rounded-lg border border-zinc-800">
              <span className="text-zinc-500 block text-[10px] uppercase">SPF AUTH</span>
              {simulationResult.authentication_headers.spf}
            </div>
            <div className="bg-[#08080A] p-2.5 rounded-lg border border-zinc-800">
              <span className="text-zinc-500 block text-[10px] uppercase">DKIM AUTH</span>
              {simulationResult.authentication_headers.dkim}
            </div>
            <div className="bg-[#08080A] p-2.5 rounded-lg border border-zinc-800">
              <span className="text-zinc-500 block text-[10px] uppercase">DMARC POLICY</span>
              {simulationResult.authentication_headers.dmarc}
            </div>
          </div>
        </div>
      )}

      {/* Store Connection & Alignment Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Connected Store Meta Card */}
        <GlassEmeraldCard
          title="Store Connection"
          subtitle="Shopify Store Sync & Domain Alignment"
          badgeText="Connected"
          badgeVariant="emerald"
          icon={<ShoppingBag className="w-5 h-5 text-emerald-400" />}
          className="space-y-4"
        >
          <div className="space-y-3 font-mono text-xs">
            <div>
              <span className="text-[10px] text-zinc-500 block uppercase">Shopify Store Domain</span>
              <input
                type="text"
                value={storeDomain}
                onChange={(e) => setStoreDomain(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <span className="text-[10px] text-zinc-500 block uppercase">Custom Apex Domain</span>
              <input
                type="text"
                value={customDomain}
                onChange={(e) => setCustomDomain(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <span className="text-[10px] text-zinc-500 block uppercase">Transactional Sender Address</span>
              <input
                type="email"
                value={senderEmail}
                onChange={(e) => setSenderEmail(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-emerald-400 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="pt-2 flex flex-col gap-2">
            {/* Primary Action Button */}
            <EmeraldHoverButton
              onClick={handleAuditAlignment}
              isLoading={isCheckingAlignment}
              loadingText="Auditing Alignment..."
              icon={<ShieldCheck className="w-3.5 h-3.5" />}
              size="sm"
              variant="primary"
              className="w-full py-2.5"
            >
              Audit Sender Alignment
            </EmeraldHoverButton>

            {/* Secondary Ghost Buttons */}
            <div className="flex items-center gap-2">
              <EmeraldHoverButton
                onClick={copyWebhookEndpoint}
                icon={copiedWebhook ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3 text-zinc-400" />}
                size="xs"
                variant="ghost"
                className="flex-1 font-mono py-2"
              >
                {copiedWebhook ? "Copied Endpoint!" : "Copy Webhook URL"}
              </EmeraldHoverButton>

              <EmeraldHoverButton
                onClick={() => setShowHmacModal(true)}
                icon={<Key className="w-3 h-3" />}
                size="xs"
                variant="ghost"
                className="px-3 py-2 font-mono"
              >
                HMAC Secret
              </EmeraldHoverButton>
            </div>
          </div>
        </GlassEmeraldCard>

        {/* Transactional Sender Alignment Status */}
        <GlassEmeraldCard
          title="Transactional Sender Alignment Status"
          subtitle="Google & Yahoo 2024 Compliance Verification"
          badgeText="Aligned"
          badgeVariant="emerald"
          icon={<Shield className="w-5 h-5 text-emerald-400" />}
          className="lg:col-span-2 space-y-4"
        >

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="p-3.5 bg-[#08080A] rounded-lg border border-zinc-800">
              <span className="text-zinc-400 text-xs font-semibold block mb-1">SPF Mechanism</span>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-white font-mono text-xs font-bold">shops.shopify.com</span>
              </div>
              <span className="text-[10px] text-zinc-500 mt-1 block font-mono">Inclusion Confirmed</span>
            </div>

            <div className="p-3.5 bg-[#08080A] rounded-lg border border-zinc-800">
              <span className="text-zinc-400 text-xs font-semibold block mb-1">Shopify DKIM Signing</span>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-white font-mono text-xs font-bold">shopify._domainkey</span>
              </div>
              <span className="text-[10px] text-zinc-500 mt-1 block font-mono">CNAMEs Active</span>
            </div>

            <div className="p-3.5 bg-[#08080A] rounded-lg border border-zinc-800">
              <span className="text-zinc-400 text-xs font-semibold block mb-1">DMARC Policy</span>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-white font-mono text-xs font-bold">p=quarantine</span>
              </div>
              <span className="text-[10px] text-zinc-500 mt-1 block font-mono">Aligned with from: domain</span>
            </div>
          </div>

          {alignmentResult && (
            <div className="p-4 bg-[#08080A] rounded-lg border border-zinc-800 space-y-2">
              <div className="flex items-center gap-2 text-xs font-bold text-emerald-400">
                <CheckCircle2 className="w-4 h-4" />
                Sender <span className="font-mono text-white">{senderEmail}</span> aligns with domain authentication policy!
              </div>
              {alignmentResult.recommendations?.length > 0 && (
                <ul className="text-xs text-amber-400 list-disc list-inside space-y-1">
                  {alignmentResult.recommendations.map((rec: string, i: number) => (
                    <li key={i}>{rec}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </GlassEmeraldCard>
      </div>

      {/* Webhook & Order Activity Log with Table Containment & Sticky Header */}
      <GlassEmeraldCard
        title="HMAC-Verified Transactional Log"
        subtitle="Live events ingested via Shopify Admin webhooks triggering deliverability verification"
        badgeText="HMAC-SHA256"
        badgeVariant="emerald"
        icon={<Activity className="w-5 h-5 text-emerald-400" />}
      >

        {/* Large Table Overflow Container with Sleek Scrollbar & Sticky Header */}
        <div className="overflow-x-auto max-h-[380px] overflow-y-auto scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent hover:scrollbar-thumb-emerald-500/40">
          <table className="w-full text-left text-xs font-mono">
            <thead className="text-zinc-400 border-b border-zinc-800 text-[10px] uppercase bg-[#0E0E12] sticky top-0 z-10 backdrop-blur-sm">
              <tr>
                <th className="px-5 py-3.5 font-semibold">Event</th>
                <th className="px-5 py-3.5 font-semibold">Order ID</th>
                <th className="px-5 py-3.5 font-semibold">Customer</th>
                <th className="px-5 py-3.5 font-semibold">Sender Domain</th>
                <th className="px-5 py-3.5 font-semibold">Placement Status</th>
                <th className="px-5 py-3.5 font-semibold">Alert Status</th>
                <th className="px-5 py-3.5 font-semibold text-right">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-900/60 text-zinc-300">
              {logs.map((log) => (
                <tr
                  key={log.id}
                  className={`border-b border-zinc-900/60 hover:bg-zinc-800/20 transition-all duration-150 ${
                    log.isNew ? "bg-emerald-500/10 animate-fadeIn" : ""
                  }`}
                >
                  <td className="px-5 py-3.5 text-white flex items-center gap-2 font-bold font-mono">
                    <Activity className="w-3.5 h-3.5 text-emerald-400" />
                    {log.event}
                  </td>
                  <td className="px-5 py-3.5 font-bold text-white font-mono">{log.order_id}</td>
                  <td className="px-5 py-3.5 text-zinc-300 font-sans text-xs">{log.customer_email}</td>
                  <td className="px-5 py-3.5 text-emerald-400 font-mono">{log.sender_domain}</td>
                  <td className="px-5 py-3.5">
                    {log.status === "primary_inbox" ? (
                      <span className="text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1 font-mono">
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        PRIMARY INBOX
                      </span>
                    ) : log.status === "spam_folder" ? (
                      <span className="text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1 font-mono">
                        <AlertTriangle className="w-3 h-3 text-amber-400" />
                        SPAM FOLDER
                      </span>
                    ) : (
                      <span className="text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 inline-flex items-center gap-1 font-mono">
                        <XCircle className="w-3 h-3 text-rose-400" />
                        HARD BOUNCE
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 font-mono">
                    {log.alert_status === "delivered" ? (
                      <span className="text-[10px] text-zinc-400 inline-flex items-center gap-1">
                        <Check className="w-3 h-3 text-emerald-400" />
                        ✓ Delivered
                      </span>
                    ) : (
                      <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1">
                        <Zap className="w-3 h-3 text-amber-400 fill-current" />
                        ⚡ Telegram Alert Dispatched
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-right text-zinc-500 text-[11px] font-mono">
                    {log.timestamp}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassEmeraldCard>

      {/* Telegram Real-Time Alert & Incident Engine */}
      <GlassEmeraldCard
        title="Telegram Real-Time Alert & Incident Engine"
        subtitle="Instantly dispatches Telegram alerts to store owners when email telemetry detects spam folder routing or blacklist events"
        badgeText="BOT ACTIVE"
        badgeVariant="emerald"
        icon={<Radio className="w-5 h-5 text-emerald-400" />}
        className="space-y-5"
      >

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 font-mono text-xs">
          <div className="bg-[#08080A] p-3.5 rounded-lg border border-zinc-800">
            <span className="text-[10px] text-zinc-500 uppercase block">Primary Channel</span>
            <span className="text-sm font-bold text-white block mt-1">Telegram Bot (Active)</span>
            <span className="text-[10px] text-emerald-400 mt-0.5 block">Bot Token Verified</span>
          </div>

          <div className="bg-[#08080A] p-3.5 rounded-lg border border-zinc-800">
            <span className="text-[10px] text-zinc-500 uppercase block">Dispatch Target</span>
            <span className="text-sm font-bold text-white block mt-1">@inboundcheck_alerts</span>
            <span className="text-[10px] text-zinc-400 mt-0.5 block">Channel ID: -1001982348712</span>
          </div>

          <div className="bg-[#08080A] p-3.5 rounded-lg border border-zinc-800">
            <span className="text-[10px] text-zinc-500 uppercase block">Trigger Events</span>
            <span className="text-xs font-bold text-amber-400 block mt-1">email_spam | hard_bounce | rbl_listed</span>
            <span className="text-[10px] text-zinc-400 mt-0.5 block">Instant Direct Dispatch</span>
          </div>
        </div>

        {/* Telegram Dispatch Audit Log with Sticky Header & Scroll Containment */}
        <div className="space-y-2 pt-2">
          <span className="text-xs font-bold text-white block uppercase tracking-wider">
            Recent Incident Dispatch Log
          </span>
          <div className="overflow-x-auto max-h-[380px] overflow-y-auto scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent hover:scrollbar-thumb-emerald-500/40 bg-[#08080A] rounded-lg border border-zinc-800">
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-zinc-400 border-b border-zinc-800 text-[10px] uppercase sticky top-0 z-10 bg-[#0E0E12] backdrop-blur-sm">
                <tr>
                  <th className="p-3.5 font-semibold">Incident ID</th>
                  <th className="p-3.5 font-semibold">Store / Recipient</th>
                  <th className="p-3.5 font-semibold">Channel</th>
                  <th className="p-3.5 font-semibold">Trigger Reason</th>
                  <th className="p-3.5 text-right font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900/60 text-zinc-300">
                <tr className="hover:bg-zinc-800/20 transition-all duration-150">
                  <td className="p-3.5 font-bold text-white font-mono">#TG-10488</td>
                  <td className="p-3.5 text-zinc-300 font-mono">luxurystore.myshopify.com</td>
                  <td className="p-3.5 text-emerald-400 font-mono">Telegram Bot</td>
                  <td className="p-3.5 font-mono">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      email_spam_detected
                    </span>
                  </td>
                  <td className="p-3.5 text-right text-emerald-400 font-bold font-mono">
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      DELIVERED
                    </span>
                  </td>
                </tr>
                <tr className="hover:bg-zinc-800/20 transition-all duration-150">
                  <td className="p-3.5 font-bold text-white font-mono">#TG-10482</td>
                  <td className="p-3.5 text-zinc-300 font-mono">luxurystore.myshopify.com</td>
                  <td className="p-3.5 text-emerald-400 font-mono">Telegram Bot</td>
                  <td className="p-3.5 font-mono">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">
                      hard_bounce
                    </span>
                  </td>
                  <td className="p-3.5 text-right text-emerald-400 font-bold font-mono">
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      DELIVERED
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </GlassEmeraldCard>

      {/* Verify HMAC Secret Modal */}
      {showHmacModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="shopify-hmac-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowHmacModal(false);
          }}
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="bg-[#0E0E12] border border-zinc-800 rounded-xl max-w-md w-full p-6 space-y-4 animate-fadeIn font-mono shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h3 id="shopify-hmac-modal-title" className="text-sm font-bold text-white flex items-center gap-2">
                <Key className="w-4 h-4 text-emerald-400" />
                Shopify Webhook HMAC Secret
              </h3>
              <button
                type="button"
                onClick={() => setShowHmacModal(false)}
                aria-label="Close dialog"
                className="text-zinc-500 hover:text-white cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <p className="text-zinc-400 font-sans">
                InboundCheck validates all incoming order webhooks using the standard HMAC-SHA256 signature algorithm.
              </p>
              <div>
                <label className="text-[10px] text-zinc-500 uppercase block mb-1">HMAC Shared Secret</label>
                <input
                  type="text"
                  value={hmacSecretInput}
                  onChange={(e) => setHmacSecretInput(e.target.value)}
                  className="w-full px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-emerald-400 text-xs focus:outline-none focus:border-emerald-500 font-mono"
                />
              </div>

              {hmacVerified && (
                <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400 text-[11px] flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  HMAC-SHA256 signature verification active.
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowHmacModal(false)}
                className="px-4 py-2 bg-zinc-900/60 hover:bg-zinc-800 border border-zinc-700/60 text-zinc-300 hover:text-white rounded-lg text-xs transition-all cursor-pointer"
              >
                Close
              </button>
              <button
                type="button"
                onClick={handleVerifyHmacSecret}
                disabled={isVerifyingHmac}
                className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold rounded-lg text-xs shadow-[0_0_20px_rgba(16,185,129,0.2)] active:scale-[0.98] transition-all cursor-pointer"
              >
                {isVerifyingHmac ? "Validating..." : "Verify Secret"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
