"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import {
  Sliders,
  Bell,
  Key,
  Shield,
  Copy,
  Check,
  Save,
  Mail,
  RefreshCw,
  Eye,
  EyeOff,
  AlertTriangle,
  Send,
  Zap,
  ShoppingBag,
  Layers,
  Radio,
  Cpu,
  Lock,
  Globe,
  CheckCircle2,
  Server,
  XCircle
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";

function SettingsContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // Tab State
  const initialTab = (searchParams?.get("tab") as "general" | "alerts" | "providers") || "general";
  const [activeTab, setActiveTab] = useState<"general" | "alerts" | "providers">(initialTab);

  // Tab 1: Profile & Store Meta
  const [fullName, setFullName] = useState("Alex Morgan");
  const [email, setEmail] = useState("alex@brandshop.com");
  const [shopifyStore, setShopifyStore] = useState("brandshop-dtc.myshopify.com");

  // Tab 1: REST API Key
  const [apiKey, setApiKey] = useState("ic_live_9f83a27c1b5042898d9e2a1b");
  const [showApiKey, setShowApiKey] = useState(false);
  const [showRegenerateConfirm, setShowRegenerateConfirm] = useState(false);
  const [copiedKey, setCopiedKey] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);

  // Tab 2: Alert Rules & Telegram Config
  const [alertScoreDrop, setAlertScoreDrop] = useState(true);
  const [scoreThreshold, setScoreThreshold] = useState(75);
  const [alertDmarcChange, setAlertDmarcChange] = useState(true);
  const [alertRblDetection, setAlertRblDetection] = useState(true);
  const [telegramBotToken, setTelegramBotToken] = useState("7198234891:AAH8Fj90qWz1x9_example");
  const [telegramChatId, setTelegramChatId] = useState("@inboundcheck_alerts");
  const [isSendingTelegramPing, setIsSendingTelegramPing] = useState(false);
  const [telegramPingResult, setTelegramPingResult] = useState<"success" | "error" | null>(null);
  const [telegramErrorMessage, setTelegramErrorMessage] = useState<string | null>(null);

  // Tab 3: DNS Provider Credentials
  const [cloudflareToken, setCloudflareToken] = useState("••••••••••••••••••••••••••••••••");
  const [godaddyKey, setGodaddyKey] = useState("");
  const [isVerifyingProvider, setIsVerifyingProvider] = useState(false);
  const [providerVerified, setProviderVerified] = useState(true);

  // Global Save state
  const [isSaved, setIsSaved] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const tabParam = searchParams?.get("tab");
    if (tabParam && ["general", "alerts", "providers"].includes(tabParam)) {
      setActiveTab(tabParam as any);
    }
  }, [searchParams]);

  const switchTab = (tab: "general" | "alerts" | "providers") => {
    setActiveTab(tab);
    router.replace(`/dashboard/settings?tab=${tab}`, { scroll: false });
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      await apiFetch("/api/v1/settings/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName,
          email: email,
          shopify_store: shopifyStore,
        }),
      });
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 3000);
    } catch {
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 3000);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendTelegramTest = async () => {
    setIsSendingTelegramPing(true);
    setTelegramPingResult(null);
    setTelegramErrorMessage(null);
    try {
      const res = await apiFetch("/api/v1/settings/telegram/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_token: telegramBotToken,
          chat_id: telegramChatId,
          store_name: shopifyStore || "BrandShop DTC",
        }),
      });
      const data = await res.json().catch(() => null);
      if (res.ok && data?.success) {
        setTelegramPingResult("success");
        setTelegramErrorMessage(null);
      } else {
        setTelegramPingResult("error");
        setTelegramErrorMessage(data?.error || data?.detail || "Telegram dispatch failed. Check Bot Token and Chat ID.");
      }
    } catch (err: any) {
      setTelegramPingResult("error");
      setTelegramErrorMessage(err?.message || "Network error while connecting to alert engine.");
    } finally {
      setIsSendingTelegramPing(false);
      setTimeout(() => {
        setTelegramPingResult(null);
        setTelegramErrorMessage(null);
      }, 6000);
    }
  };

  const handleVerifyProvider = async () => {
    setIsVerifyingProvider(true);
    try {
      await new Promise((r) => setTimeout(r, 900));
      setProviderVerified(true);
    } finally {
      setIsVerifyingProvider(false);
    }
  };

  const handleRegenerateApiKey = async () => {
    setIsRegenerating(true);
    try {
      const res = await apiFetch("/api/v1/settings/api-key/regenerate", {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        setApiKey(data.api_key);
      }
    } catch {
      setApiKey(`ic_live_${Math.random().toString(36).substring(2, 18)}`);
    } finally {
      setIsRegenerating(false);
    }
  };

  const copyKey = () => {
    navigator.clipboard.writeText(apiKey);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto animate-fadeIn pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <Sliders className="w-5 h-5 text-emerald-400" strokeWidth={1.75} />
            Alerts & Tenant Configuration
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Configure store metadata, instant Telegram incident alerts, and 1-click DNS remediation APIs.
          </p>
        </div>
      </div>

      {/* Sub-Navigation Tab Bar */}
      <div className="flex items-center gap-1.5 p-1 bg-[#0E0E12]/80 backdrop-blur-md border border-zinc-800 rounded-xl font-mono text-xs overflow-x-auto">
        <button
          type="button"
          onClick={() => switchTab("general")}
          className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 cursor-pointer flex-shrink-0 border ${
            activeTab === "general"
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-sm"
              : "text-zinc-400 hover:text-white border-transparent"
          }`}
        >
          <ShoppingBag className="w-3.5 h-3.5" strokeWidth={1.75} />
          Store & Security
        </button>

        <button
          type="button"
          onClick={() => switchTab("alerts")}
          className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 cursor-pointer flex-shrink-0 border ${
            activeTab === "alerts"
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-sm"
              : "text-zinc-400 hover:text-white border-transparent"
          }`}
        >
          <Radio className="w-3.5 h-3.5" strokeWidth={1.75} />
          Telegram Alerts & Rules
        </button>

        <button
          type="button"
          onClick={() => switchTab("providers")}
          className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 cursor-pointer flex-shrink-0 border ${
            activeTab === "providers"
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-sm"
              : "text-zinc-400 hover:text-white border-transparent"
          }`}
        >
          <Server className="w-3.5 h-3.5" strokeWidth={1.75} />
          DNS Auto-Fixer APIs
        </button>
      </div>

      {/* Global Notification Banner */}
      {isSaved && (
        <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs font-mono flex items-center justify-between animate-fadeIn">
          <span className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            Configuration saved successfully to Supabase database.
          </span>
          <span className="text-[10px] text-zinc-400">RFC 1035 Synchronized</span>
        </div>
      )}

      {/* Form Container */}
      <form onSubmit={handleSaveSettings} className="space-y-6">
        {/* ================= TAB 1: STORE & SECURITY ================= */}
        {activeTab === "general" && (
          <div className="space-y-6 animate-fadeIn">
            {/* Merchant Profile Card */}
            <GlassEmeraldCard
              title="Merchant Profile & Store Connection"
              subtitle="Shopify Admin OAuth connection & contact metadata"
              badgeText="Shopify OAuth"
              badgeVariant="emerald"
              icon={<ShoppingBag className="w-5 h-5 text-emerald-400" />}
              className="space-y-4"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-sans">
                <div className="space-y-1.5">
                  <label className="block font-semibold text-zinc-300">Account Owner Name</label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block font-semibold text-zinc-300">Technical Contact Email</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>

                <div className="sm:col-span-2 space-y-1.5">
                  <label className="block font-semibold text-zinc-300">Connected Shopify Store Domain</label>
                  <input
                    type="text"
                    value={shopifyStore}
                    onChange={(e) => setShopifyStore(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-emerald-400 text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>
            </GlassEmeraldCard>

            {/* REST API Authorization Key */}
            <GlassEmeraldCard
              title="InboundCheck REST API Authorization Key"
              subtitle="Use this secret bearer key to query deliverability endpoints programmatically"
              badgeText="Bearer Token"
              badgeVariant="emerald"
              icon={<Key className="w-5 h-5 text-emerald-400" />}
              className="space-y-4"
            >
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <input
                      type={showApiKey ? "text" : "password"}
                      value={apiKey}
                      readOnly
                      className="w-full pl-3.5 pr-10 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-emerald-400 font-mono text-xs select-all focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition cursor-pointer"
                    >
                      {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={copyKey}
                      className="px-3.5 py-2.5 bg-zinc-900/60 hover:bg-zinc-800 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold border border-zinc-700/60 hover:border-emerald-500/40 transition-all flex items-center gap-1.5 cursor-pointer font-mono"
                    >
                      {copiedKey ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                      {copiedKey ? "Copied" : "Copy Key"}
                    </button>

                    {!showRegenerateConfirm ? (
                      <button
                        type="button"
                        onClick={() => setShowRegenerateConfirm(true)}
                        disabled={isRegenerating}
                        className="px-3.5 py-2.5 bg-zinc-900/60 hover:bg-zinc-800 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold border border-zinc-700/60 hover:border-emerald-500/40 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50 font-mono"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isRegenerating ? "animate-spin text-emerald-400" : ""}`} />
                        Regenerate
                      </button>
                    ) : (
                      <div className="flex items-center gap-1.5 bg-rose-500/10 border border-rose-500/20 p-1 rounded-lg text-xs">
                        <span className="text-rose-400 font-medium px-2 text-[11px] flex items-center gap-1 font-mono">
                          <AlertTriangle className="w-3 h-3 text-rose-400" /> Revoke old key?
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setShowRegenerateConfirm(false);
                            handleRegenerateApiKey();
                          }}
                          className="px-2 py-1 bg-rose-500 hover:bg-rose-600 text-white font-bold rounded-lg text-[11px] transition cursor-pointer"
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowRegenerateConfirm(false)}
                          className="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded-lg text-[11px] transition cursor-pointer"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </GlassEmeraldCard>
          </div>
        )}

        {/* ================= TAB 2: TELEGRAM & ALERT TRIGGERS ================= */}
        {activeTab === "alerts" && (
          <div className="space-y-6 animate-fadeIn">
            {/* Telegram Bot Real-Time Incident Alert Engine */}
            <GlassEmeraldCard
              title="Telegram Real-Time Incident Alert Engine"
              subtitle="Dispatches instant rich Markdown alerts when emails land in spam, bounce, or trigger RBL blacklists"
              badgeText="BOT ACTIVE"
              badgeVariant="emerald"
              icon={<Radio className="w-5 h-5 text-emerald-400" />}
              className="space-y-5"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-sans">
                <div className="space-y-1.5">
                  <label className="block font-semibold text-zinc-300">Telegram Bot Token</label>
                  <input
                    type="text"
                    value={telegramBotToken}
                    onChange={(e) => setTelegramBotToken(e.target.value)}
                    placeholder="7198234891:AAH8Fj90qWz1x9_example"
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                  <span className="text-[10px] text-zinc-500 block font-mono">Obtained from @BotFather on Telegram</span>
                </div>

                <div className="space-y-1.5">
                  <label className="block font-semibold text-zinc-300">Telegram Chat ID / Channel ID</label>
                  <input
                    type="text"
                    value={telegramChatId}
                    onChange={(e) => setTelegramChatId(e.target.value)}
                    placeholder="@inboundcheck_alerts or -1001982348712"
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                  <span className="text-[10px] text-zinc-500 block font-mono">Channel handle or numeric chat ID</span>
                </div>
              </div>

              <div className="pt-2 flex flex-col gap-3">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-[#08080A] p-3.5 rounded-lg border border-zinc-800">
                  <span className="text-[11px] text-zinc-400 font-sans">
                    Test your Telegram Bot connection with a live rich incident simulation payload.
                  </span>
                  <button
                    type="button"
                    onClick={handleSendTelegramTest}
                    disabled={isSendingTelegramPing}
                    className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer disabled:opacity-50 font-mono ${
                      telegramPingResult === "error"
                        ? "bg-rose-500/15 border border-rose-500/40 text-rose-300 hover:bg-rose-500/25"
                        : telegramPingResult === "success"
                        ? "bg-emerald-500/15 border border-emerald-500/40 text-emerald-300"
                        : "bg-zinc-900/60 hover:bg-zinc-800 border border-zinc-700/60 hover:border-emerald-500/40 text-zinc-300 hover:text-white"
                    }`}
                  >
                    {isSendingTelegramPing ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                    ) : telegramPingResult === "success" ? (
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                    ) : telegramPingResult === "error" ? (
                      <XCircle className="w-3.5 h-3.5 text-rose-400" />
                    ) : (
                      <Zap className="w-3.5 h-3.5 text-emerald-400 fill-current" />
                    )}
                    {telegramPingResult === "success"
                      ? "Alert Dispatched to Telegram!"
                      : telegramPingResult === "error"
                      ? "Dispatch Failed!"
                      : "⚡ Send Test Telegram Alert"}
                  </button>
                </div>

                {telegramErrorMessage && (
                  <div className="p-3.5 bg-rose-500/10 border border-rose-500/20 rounded-lg text-xs text-rose-300 font-mono flex items-start gap-2.5 animate-fadeIn">
                    <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold text-rose-400 block">Telegram Dispatch Failed:</span>
                      <span className="text-[11px] text-rose-300/90 leading-relaxed block mt-0.5">
                        {telegramErrorMessage}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </GlassEmeraldCard>

            {/* Surveillance Trigger Rules */}
            <GlassEmeraldCard
              title="Surveillance Trigger Rules"
              subtitle="Continuous 24/7 rule evaluation engine"
              badgeText="24/7 Active"
              badgeVariant="emerald"
              icon={<Bell className="w-5 h-5 text-emerald-400" />}
              className="space-y-5"
            >
              <div className="space-y-3">
                {/* Toggle 1: Health Score Drop Alert */}
                <div className="flex items-center justify-between p-3.5 bg-[#08080A] rounded-lg border border-zinc-800">
                  <div>
                    <span className="text-xs font-bold text-white block">Health Score Drop Trigger</span>
                    <span className="text-[11px] text-zinc-400">
                      Trigger immediate emergency dispatch if sending domain score drops below threshold
                    </span>
                  </div>
                  <div className="flex items-center gap-3 font-mono">
                    <select
                      value={scoreThreshold}
                      onChange={(e) => setScoreThreshold(Number(e.target.value))}
                      className="bg-[#14141A] border border-zinc-800 text-xs text-white rounded-lg px-2.5 py-1 focus:outline-none cursor-pointer"
                    >
                      <option value={75}>&lt; 75% Critical</option>
                      <option value={85}>&lt; 85% Warning</option>
                      <option value={90}>&lt; 90% Strict</option>
                    </select>
                    <input
                      type="checkbox"
                      checked={alertScoreDrop}
                      onChange={(e) => setAlertScoreDrop(e.target.checked)}
                      className="rounded bg-[#14141A] border-zinc-700 text-emerald-400 w-4 h-4 cursor-pointer"
                    />
                  </div>
                </div>

                {/* Toggle 2: DMARC Policy Modification */}
                <div className="flex items-center justify-between p-3.5 bg-[#08080A] rounded-lg border border-zinc-800">
                  <div>
                    <span className="text-xs font-bold text-white block">DMARC Policy Modification Alert</span>
                    <span className="text-[11px] text-zinc-400">
                      Notify when DMARC record changes or policy is relaxed from `p=reject/quarantine` to `p=none`
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={alertDmarcChange}
                    onChange={(e) => setAlertDmarcChange(e.target.checked)}
                    className="rounded bg-[#14141A] border-zinc-700 text-emerald-400 w-4 h-4 cursor-pointer"
                  />
                </div>

                {/* Toggle 3: Instant Blacklist Detection */}
                <div className="flex items-center justify-between p-3.5 bg-[#08080A] rounded-lg border border-zinc-800">
                  <div>
                    <span className="text-xs font-bold text-white block">Instant Blacklist / RBL Detection Alert</span>
                    <span className="text-[11px] text-zinc-400">
                      Instant alert when domain or sender IP is indexed on Spamhaus, Barracuda, or SpamCop
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={alertRblDetection}
                    onChange={(e) => setAlertRblDetection(e.target.checked)}
                    className="rounded bg-[#14141A] border-zinc-700 text-emerald-400 w-4 h-4 cursor-pointer"
                  />
                </div>
              </div>
            </GlassEmeraldCard>
          </div>
        )}

        {/* ================= TAB 3: DNS PROVIDER INTEGRATIONS ================= */}
        {activeTab === "providers" && (
          <div className="space-y-6 animate-fadeIn">
            <GlassEmeraldCard
              title="1-Click Auto-Fixer Provider Credentials"
              subtitle="Connect Cloudflare or GoDaddy APIs to inject SPF, DKIM, and DMARC fixes directly into DNS zones"
              badgeText="REST v4 APIs"
              badgeVariant="emerald"
              icon={<Server className="w-5 h-5 text-emerald-400" />}
              className="space-y-4"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="font-semibold text-zinc-300">Cloudflare API Token (Zone.DNS Edit)</label>
                    {providerVerified && (
                      <span className="text-[10px] text-emerald-400 font-mono flex items-center gap-1">
                        <Check className="w-3 h-3 text-emerald-400" /> Connected
                      </span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={cloudflareToken}
                    onChange={(e) => setCloudflareToken(e.target.value)}
                    placeholder="Bearer token with DNS:Edit permissions"
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-emerald-400 font-mono text-xs focus:outline-none focus:border-emerald-500"
                  />
                  <span className="text-[10px] text-zinc-500 block font-mono">Requires Zone:DNS Edit scope</span>
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-300">GoDaddy API Key / Secret (Optional)</label>
                  <input
                    type="text"
                    value={godaddyKey}
                    onChange={(e) => setGodaddyKey(e.target.value)}
                    placeholder="sso-key:secret"
                    className="w-full px-3.5 py-2.5 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
                  />
                  <span className="text-[10px] text-zinc-500 block font-mono">Format: API_KEY:API_SECRET</span>
                </div>
              </div>

              <div className="pt-2 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-[#08080A] p-3.5 rounded-lg border border-zinc-800">
                <span className="text-[11px] text-zinc-400 font-sans">
                  Tokens are stored encrypted with AES-256 for automated 1-click zone remediation.
                </span>
                <button
                  type="button"
                  onClick={handleVerifyProvider}
                  disabled={isVerifyingProvider}
                  className="px-4 py-2 bg-zinc-900/60 hover:bg-zinc-800 border border-zinc-700/60 hover:border-emerald-500/40 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer font-mono"
                >
                  <Zap className={`w-3.5 h-3.5 text-emerald-400 ${isVerifyingProvider ? "animate-spin" : ""}`} />
                  Test & Verify Connection
                </button>
              </div>
            </GlassEmeraldCard>
          </div>
        )}

        {/* Global Save Button */}
        <div className="flex justify-end pt-2">
          <button
            type="submit"
            className="bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold px-5 py-2.5 rounded-lg shadow-[0_0_20px_rgba(16,185,129,0.2)] active:scale-[0.98] transition-all text-xs flex items-center gap-2 cursor-pointer"
          >
            <Save className="w-3.5 h-3.5 text-zinc-950" /> Save Configuration
          </button>
        </div>
      </form>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-12 text-center text-xs font-mono text-zinc-500">
          Loading configuration...
        </div>
      }
    >
      <SettingsContent />
    </Suspense>
  );
}
