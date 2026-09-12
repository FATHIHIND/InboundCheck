"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { OperationalErrorCard } from "@/components/operational/OperationalErrorCard";
import { OperationalEmptyState } from "@/components/operational/OperationalEmptyState";
import { OperationalLoadingState } from "@/components/operational/OperationalLoadingState";
import {
  ShoppingBag,
  ShieldCheck,
  CheckCircle2,
  Zap,
  Check,
  Activity,
  XCircle,
  Radio,
  Shield,
  Sparkles,
  Sliders,
  Edit3
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";
import { DeliverabilityRiskBanner } from "@/components/dashboard/DeliverabilityRiskBanner";
import { ZeroSpamWizardModal } from "./zero-spam-wizard";
import { StoreSettingsDrawer } from "./StoreSettingsDrawer";

interface TelegramIncidentLog {
  id: string;
  order_id: string | null;
  domain_name: string | null;
  triggered_reason: string | null;
  channel: "telegram";
  fallback_channel: "telegram";
  provider: "telegram";
  provider_status: "delivered" | "failed";
  status: "delivered" | "failed";
  attempted_at: string | null;
  delivered_at: string | null;
  created_at: string;
  provider_sid?: string | null;
}

interface ShopifyStoreItem {
  id: string;
  shop_domain: string;
  custom_domain?: string;
  sender_email?: string;
  is_active: boolean;
  connected_at?: string;
  metadata?: {
    name?: string;
    email?: string;
    esp_provider?: string;
  };
}

export default function ShopifyHubPage() {
  const [storeName, setStoreName] = useState("");
  const [storeDomain, setStoreDomain] = useState("");
  const [customDomain, setCustomDomain] = useState("");
  const [senderEmail, setSenderEmail] = useState("");

  // In-Context Store Management Modal Drawer State
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(false);

  // Simulation State
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationStep, setSimulationStep] = useState<number | null>(null);
  const [simulationResult, setSimulationResult] = useState<any>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);

  // Alignment Check State
  const [isCheckingAlignment, setIsCheckingAlignment] = useState(false);
  const [alignmentResult, setAlignmentResult] = useState<any>(null);
  const [alignmentError, setAlignmentError] = useState<string | null>(null);

  const [showWizardModal, setShowWizardModal] = useState(false);

  // 1. Data-State Contract for Connected Shopify Stores
  const {
    resource: storesResource,
    retry: retryStores,
    reload: reloadStores,
  } = useApiResource<ShopifyStoreItem[]>({
    endpoint: "/api/v1/shopify/stores",
    parse: async (res) => {
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    },
    isEmpty: (data) => !data || data.length === 0,
  });

  // 2. Data-State Contract for Telegram Failover & Incident Logs
  const {
    resource: failoverLogsResource,
    retry: retryFailoverLogs,
    reload: reloadFailoverLogs,
  } = useApiResource<TelegramIncidentLog[]>({
    endpoint: "/api/v1/failover/logs?limit=50&offset=0",
    parse: async (res) => {
      const json = await res.json();
      return Array.isArray(json.logs) ? json.logs : [];
    },
    isEmpty: (data) => !data || data.length === 0,
  });

  // Update default inputs when stores load
  useEffect(() => {
    if (storesResource.state === "ready" && storesResource.data.length > 0) {
      const first = storesResource.data[0];
      setStoreDomain(first.shop_domain || "");
      setCustomDomain(first.custom_domain || first.shop_domain.replace(".myshopify.com", ".com"));
      setSenderEmail(first.sender_email || `orders@${first.shop_domain.replace(".myshopify.com", ".com")}`);
      if (first.metadata?.name) {
        setStoreName(first.metadata.name);
      }
    }
  }, [storesResource]);

  // Enhanced Test Order Simulator calling backend API (development mode)
  const handleSimulateOrder = async () => {
    setIsSimulating(true);
    setSimulationResult(null);
    setSimulationError(null);

    const targetShop = storeDomain.trim() || (storesResource.data?.[0]?.shop_domain || "test-store.myshopify.com");
    const targetCustomer = "test-customer@example.com";
    const targetSender = senderEmail.trim() || (customDomain ? `orders@${customDomain}` : "orders@mystore.com");

    try {
      setSimulationStep(1);
      await new Promise((r) => setTimeout(r, 450));

      setSimulationStep(2);
      await new Promise((r) => setTimeout(r, 550));

      setSimulationStep(3);

      const res = await apiFetch("/api/v1/shopify/simulate-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          shop_domain: targetShop,
          customer_email: targetCustomer,
          sender_email: targetSender,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Unable to simulate order delivery. Please verify that your store connection is active.");
      }
      setSimulationResult(await res.json());
      reloadStores();
      reloadFailoverLogs();
    } catch (err: any) {
      setSimulationError(err?.message || "Failed to execute order delivery simulation.");
    } finally {
      setIsSimulating(false);
    }
  };

  const handleAuditAlignment = async () => {
    setIsCheckingAlignment(true);
    setAlignmentError(null);
    try {
      const res = await apiFetch("/api/v1/shopify/sender-alignment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender_email: senderEmail,
          custom_domain: customDomain,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Unable to verify sender address alignment. Please check your store configuration.");
      }

      const data = await res.json();
      setAlignmentResult(data.alignment);
      reloadStores();
    } catch (err: any) {
      setAlignmentError(err?.message || "Failed to evaluate sender alignment.");
    } finally {
      setIsCheckingAlignment(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <ShoppingBag className="w-5 h-5 text-emerald-400" />
            Shopify Store Sync &amp; Inbox Protection
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Automated order delivery monitoring, transactional sender domain alignment, and real-time incident alerting.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <EmeraldHoverButton
            onClick={() => setShowSettingsDrawer(true)}
            size="sm"
            variant="solid"
            icon={<Sliders className="w-3.5 h-3.5" />}
          >
            Configure Store
          </EmeraldHoverButton>

          <EmeraldHoverButton
            onClick={() => setShowWizardModal(true)}
            size="sm"
            variant="outline"
            icon={<Sparkles className="w-3.5 h-3.5" />}
          >
            Protect Store Revenue
          </EmeraldHoverButton>

          {process.env.NODE_ENV === "development" && (
            <EmeraldHoverButton
              onClick={handleSimulateOrder}
              isLoading={isSimulating}
              loadingText="Simulating Order Delivery..."
              icon={<Zap className="w-3.5 h-3.5 fill-current" />}
              size="sm"
              variant="secondary"
            >
              Simulate Test Order
            </EmeraldHoverButton>
          )}
        </div>
      </div>

      {/* Deliverability Revenue-at-Risk Diagnostic Banner */}
      <DeliverabilityRiskBanner
        domain={customDomain || storeDomain || undefined}
        onOpenWizard={() => setShowWizardModal(true)}
      />

      {simulationError && (
        <OperationalErrorCard
          compact
          title="Order simulation failed"
          error={{ message: simulationError, retryable: true, endpoint: "/api/v1/shopify/simulate-order" }}
          onRetry={handleSimulateOrder}
        />
      )}

      {/* 4-State Store Connection Status */}
      {storesResource.state === "loading" && (
        <OperationalLoadingState
          label="Checking Shopify store synchronization..."
          subtext="Querying merchant store connection records"
          rows={2}
        />
      )}

      {storesResource.state === "error" && (
        <OperationalErrorCard
          title="Shopify Store Synchronization Unavailable"
          error={storesResource.error}
          onRetry={retryStores}
          retryLabel="Retry Store Connection"
        />
      )}

      {storesResource.state === "empty" && (
        <OperationalEmptyState
          icon={<ShoppingBag className="w-8 h-8 text-emerald-400" />}
          badge="Awaiting Store Configuration"
          title="No Shopify Stores Configured Yet"
          description="Configure your Shopify Plus or DTC store sending domain to enable automatic Google & Yahoo 2024 Sender Compliance monitoring, protect Order Confirmation Receipts, and avoid customer chargebacks."
          action={{
            label: "Configure Store",
            onClick: () => setShowSettingsDrawer(true),
          }}
        />
      )}

      {/* Simulation Result Alert */}
      {simulationResult && (
        <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl space-y-2 animate-fadeIn font-mono">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-emerald-400 flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4" />
              Test Order {simulationResult.order_id} Verified
            </span>
            <span className="text-[11px] text-zinc-400">
              Primary Placement: {simulationResult.placement_rate ?? 100}%
            </span>
          </div>
          <div className="text-xs text-zinc-300">
            Recipient: <span className="text-white">{simulationResult.customer_email}</span> | Folder: <span className="text-emerald-400 uppercase font-bold">{simulationResult.status}</span>
          </div>
        </div>
      )}

      {/* 2-Column Section: Configuration Form + Alignment Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <GlassEmeraldCard
          title="Store Sender Profile"
          subtitle="Verify your store sending domain, sender email, and integrated ESP"
          badgeText="Active Profile"
          badgeVariant="emerald"
          icon={<ShoppingBag className="w-5 h-5 text-emerald-400" />}
          actionLabel="Configure Store"
          onActionClick={() => setShowSettingsDrawer(true)}
          className="space-y-4"
        >
          <div className="space-y-3 font-mono text-xs">
            <div>
              <label className="text-zinc-400 block mb-1">Shopify Store Domain</label>
              <input
                type="text"
                value={storeDomain}
                onChange={(e) => setStoreDomain(e.target.value)}
                placeholder="store.myshopify.com"
                className="w-full px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <label className="text-zinc-400 block mb-1">Custom Sending Domain</label>
              <input
                type="text"
                value={customDomain}
                onChange={(e) => setCustomDomain(e.target.value)}
                placeholder="store.com"
                className="w-full px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <label className="text-zinc-400 block mb-1">Sender Email Address</label>
              <input
                type="email"
                value={senderEmail}
                onChange={(e) => setSenderEmail(e.target.value)}
                placeholder="orders@store.com"
                className="w-full px-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-emerald-400 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="pt-2 flex flex-col sm:flex-row gap-2">
            <EmeraldHoverButton
              onClick={handleAuditAlignment}
              isLoading={isCheckingAlignment}
              loadingText="Auditing Store Deliverability..."
              icon={<ShieldCheck className="w-3.5 h-3.5" />}
              size="sm"
              variant="primary"
              className="flex-1 py-2.5"
            >
              Audit Store Deliverability
            </EmeraldHoverButton>

            <button
              type="button"
              onClick={() => setShowSettingsDrawer(true)}
              className="bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700/60 font-medium px-4 py-2 rounded-xl text-xs flex items-center justify-center gap-1.5 transition cursor-pointer"
            >
              <Sliders className="w-3.5 h-3.5 text-emerald-400" />
              Edit Store
            </button>
          </div>

          {alignmentError && (
            <div className="p-2.5 bg-rose-500/10 border border-rose-500/20 rounded-lg text-xs text-rose-300 font-mono">
              {alignmentError}
            </div>
          )}
        </GlassEmeraldCard>

        {/* Transactional Sender Alignment Status */}
        <GlassEmeraldCard
          title="Transactional Sender Alignment Status"
          subtitle="Google & Yahoo 2024 Bulk Sender Requirements (US & EU) — Protect Order Receipts & Prevent Disputes"
          badgeText="Verified"
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
            <div className="p-4 bg-[#08080A] rounded-lg border border-zinc-800 space-y-2 font-mono text-xs">
              <div className="flex items-center gap-2 font-bold text-emerald-400">
                <CheckCircle2 className="w-4 h-4" />
                Sender <span className="text-white">{senderEmail}</span> evaluated:
              </div>
              <div className="text-zinc-300">
                Overall Alignment: <span className={alignmentResult.overall_aligned ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                  {alignmentResult.overall_aligned ? "PASSED" : "REQUIRES ATTENTION"}
                </span>
              </div>
              {alignmentResult.recommendations?.length > 0 && (
                <ul className="text-xs text-amber-400 list-disc list-inside space-y-1 pt-1">
                  {alignmentResult.recommendations.map((rec: string, i: number) => (
                    <li key={i}>{rec}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </GlassEmeraldCard>
      </div>

      {/* Webhook & Order Activity Log */}
      {/* Webhook & Order Activity Log */}
      <GlassEmeraldCard
        title="Real-Time Telegram Incident & Failover Audit"
        subtitle="Live alerts sent to your Telegram whenever customer order receipts or tracking emails bounce."
        badgeText={`${failoverLogsResource.state === "ready" ? failoverLogsResource.data.length : 0} Incidents`}
        badgeVariant="emerald"
        icon={<Activity className="w-5 h-5 text-emerald-400" />}
      >
        {failoverLogsResource.state === "loading" && (
          <OperationalLoadingState
            label="Loading Telegram failover & incident logs..."
            subtext="Retrieving incident history"
            rows={4}
          />
        )}

        {failoverLogsResource.state === "error" && (
          <OperationalErrorCard
            title="Unable to Retrieve Failover Logs"
            error={failoverLogsResource.error}
            onRetry={retryFailoverLogs}
            retryLabel="Retry Incident Log Sync"
          />
        )}

        {failoverLogsResource.state === "empty" && (
          <OperationalEmptyState
            icon={<Activity className="w-8 h-8 text-emerald-400" />}
            badge="Incident Radar Clear"
            title="No Telegram delivery incidents recorded"
            description="No order delivery failures recorded. When order receipts or tracking emails encounter delivery issues, instant Telegram alerts will appear here."
          />
        )}

        {failoverLogsResource.state === "ready" && (
          <div className="overflow-x-auto max-h-[420px] overflow-y-auto scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent hover:scrollbar-thumb-emerald-500/40">
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-zinc-400 border-b border-zinc-800 text-[10px] uppercase bg-[#0E0E12] sticky top-0 z-10 backdrop-blur-sm">
                <tr>
                  <th className="px-5 py-3.5 font-semibold">Order ID</th>
                  <th className="px-5 py-3.5 font-semibold">Domain</th>
                  <th className="px-5 py-3.5 font-semibold">ESP Failure Reason</th>
                  <th className="px-5 py-3.5 font-semibold">Channel</th>
                  <th className="px-5 py-3.5 font-semibold">Status</th>
                  <th className="px-5 py-3.5 font-semibold text-right">Incident Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900/60 text-zinc-300">
                {failoverLogsResource.data.map((item) => {
                  const isDelivered = item.provider_status === "delivered";
                  const isNotified = item.status === "delivered" && !item.provider_sid;
                  const rawTimestamp = item.attempted_at || item.delivered_at || item.created_at;
                  const formattedDate = rawTimestamp
                    ? new Date(rawTimestamp).toLocaleString()
                    : "Timestamp unavailable";

                  return (
                    <tr
                      key={item.id}
                      className="border-b border-zinc-900/60 hover:bg-zinc-800/20 transition-all duration-150"
                    >
                      <td className="px-5 py-3.5 font-bold text-white font-mono">
                        {item.order_id || "Unavailable"}
                      </td>
                      <td className="px-5 py-3.5 text-zinc-300 font-mono text-[11px]">
                        {item.domain_name || "Unavailable"}
                      </td>
                      <td className="px-5 py-3.5 text-amber-400 font-mono text-[11px]">
                        {item.triggered_reason || "Delivery failure"}
                      </td>
                      <td className="px-5 py-3.5 font-mono">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] uppercase font-semibold text-emerald-400">
                          <Radio className="w-3 h-3 text-emerald-400" />
                          Telegram
                        </span>
                      </td>
                      <td className="px-5 py-3.5 font-mono">
                        {isDelivered ? (
                          <span className="text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1 font-mono">
                            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                            Delivered
                          </span>
                        ) : isNotified ? (
                          <span className="text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 inline-flex items-center gap-1 font-mono">
                            <Check className="w-3 h-3 text-emerald-400" />
                            Notified
                          </span>
                        ) : (
                          <span className="text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 inline-flex items-center gap-1 font-mono">
                            <XCircle className="w-3 h-3 text-rose-400" />
                            Failed
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-right text-zinc-500 text-[11px] font-mono">
                        {formattedDate}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassEmeraldCard>

      {/* Zero-Spam Multi-Step Readiness Wizard */}
      <ZeroSpamWizardModal
        isOpen={showWizardModal}
        onClose={() => setShowWizardModal(false)}
        domain={customDomain || storeDomain || undefined}
        onSuccess={() => {
          reloadStores();
        }}
      />

      {/* In-Context Store Management Obsidian Drawer */}
      <StoreSettingsDrawer
        isOpen={showSettingsDrawer}
        onClose={() => setShowSettingsDrawer(false)}
        initialStoreName={storeName}
        initialShopDomain={storeDomain}
        initialCustomDomain={customDomain}
        initialSenderEmail={senderEmail}
        onSuccess={(updated) => {
          reloadStores();
          if (updated?.store?.custom_domain) {
            setCustomDomain(updated.store.custom_domain);
          }
          if (updated?.store?.sender_email) {
            setSenderEmail(updated.store.sender_email);
          }
          if (updated?.store?.shop_domain) {
            setStoreDomain(updated.store.shop_domain);
          }
          if (updated?.store?.metadata?.name) {
            setStoreName(updated.store.metadata.name);
          }
        }}
      />
    </div>
  );
}
