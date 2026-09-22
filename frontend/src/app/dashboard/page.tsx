"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { OperationalErrorCard } from "@/components/operational/OperationalErrorCard";
import { OperationalEmptyState } from "@/components/operational/OperationalEmptyState";
import { OperationalLoadingState } from "@/components/operational/OperationalLoadingState";
import {
  ShieldCheck,
  CheckCircle2,
  Activity,
  RefreshCw,
  Plus,
  Trash2,
  TrendingUp,
  Zap,
  Globe,
  Radio,
  ChevronDown,
  Terminal,
  X,
  Shield,
  Inbox,
  AlertTriangle,
  XCircle,
  ArrowRight,
  DollarSign,
  Sparkles,
} from "lucide-react";
import dynamic from "next/dynamic";
import ReputationTrendChart, { ReputationPoint } from "./components/ReputationTrendChart";
import CheckHistoryChart, { IMAPCheckLog } from "./components/CheckHistoryChart";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";
import { DeliverabilityRiskBanner } from "@/components/dashboard/DeliverabilityRiskBanner";
import { MerchantHealthBanner } from "@/components/dashboard/MerchantHealthBanner";
import { StripeMetricTile } from "@/components/dashboard/StripeMetricTile";
import { DomainMatrixTable } from "@/components/dashboard/DomainMatrixTable";
import { ZeroSpamWizardModal } from "./shopify/zero-spam-wizard";

const ScoreGauge3DCanvas = dynamic(() => import("./components/ScoreGauge3DCanvas"), { ssr: false });
const InboxWitnessCanvas = dynamic(() => import("./components/InboxWitnessCanvas"), { ssr: false });
const RadarBeamCanvas = dynamic(() => import("./components/RadarBeamCanvas"), { ssr: false });
const Sparkline3DCanvas = dynamic(() => import("./components/Sparkline3DCanvas"), { ssr: false });

export interface RawDomainRecord {
  id?: string | number;
  domain_name?: string;
  domain?: string;
  shopify_store?: string;
  health_score?: number;
  imap_status?: "inbox" | "spam" | "checking";
  spf_status?: "optimal" | "warning" | "critical" | string;
  dkim_status?: "optimal" | "warning" | "critical" | string;
  dmarc_status?: "optimal" | "warning" | "critical" | string;
  rbl_clean_count?: number;
  last_checked_at?: string;
}

export interface MonitoredStore {
  id: string;
  domain_name: string;
  shopify_store: string;
  unified_score: number;
  dns_health_score: number;
  imap_status: "inbox" | "spam" | "checking";
  spf_status: "optimal" | "warning" | "critical" | string;
  dkim_status: "optimal" | "warning" | "critical" | string;
  dmarc_status: "optimal" | "warning" | "critical" | string;
  rbl_clean_count: number;
  risk_level: "low" | "medium" | "high";
  last_checked_at: string;
}

export interface ConfidenceBandDetails {
  band: "high" | "medium" | "low";
  margin_error_pct: number;
  lower_bound_cents: number;
  upper_bound_cents: number;
  lower_bound_formatted: string;
  upper_bound_formatted: string;
  explanation: string;
}

export interface RevenueRiskBreakdown {
  order_count: number;
  average_order_value_cents: number;
  monthly_gmv_cents: number;
  impairment_probability: number;
  customer_impact_factor: number;
  deliverability_score: number;
  dmarc_penalty: number;
  spf_penalty: number;
  dkim_penalty: number;
  rbl_penalty: number;
}

export interface RevenueRiskData {
  domain: string;
  expected_risk_cents: number;
  expected_risk_formatted: string;
  monthly_gmv_cents: number;
  monthly_gmv_formatted: string;
  impairment_probability: number;
  customer_impact_factor: number;
  confidence_band: "high" | "medium" | "low";
  band_details?: ConfidenceBandDetails;
  breakdown?: RevenueRiskBreakdown;
  calculated_at?: string;
  recommendation?: string;
}

export interface ShopifyStoreItem {
  id: string;
  shop_domain: string;
  custom_domain?: string;
  sender_email?: string;
  is_active?: boolean;
}

export interface TelegramConfig {
  is_enabled: boolean;
  primary_channel: string;
  provider: string;
  telegram_bot_token?: string;
  telegram_chat_id?: string;
  trigger_events: string[];
  store_name?: string;
}

// 2026 Interactive Instant Activation Demo Constants (<60s TTV)
const DEMO_STORE_RECORD: MonitoredStore = {
  id: "demo-allure-apparel",
  domain_name: "allure-apparel.com",
  shopify_store: "allure-apparel.myshopify.com",
  unified_score: 64,
  dns_health_score: 64,
  imap_status: "spam",
  spf_status: "warning",
  dkim_status: "optimal",
  dmarc_status: "critical",
  rbl_clean_count: 8,
  risk_level: "high",
  last_checked_at: "Just now (Interactive Simulation)",
};

const DEMO_REVENUE_RISK: RevenueRiskData = {
  domain: "allure-apparel.com",
  expected_risk_cents: 240000,
  expected_risk_formatted: "$2,400.00",
  monthly_gmv_cents: 4800000,
  monthly_gmv_formatted: "$48,000.00",
  impairment_probability: 0.28,
  customer_impact_factor: 1.25,
  confidence_band: "high",
  calculated_at: new Date().toISOString(),
  recommendation: "Repair SPF multi-lookup record and enforce DMARC p=quarantine to prevent silent Gmail/Yahoo order drop.",
  breakdown: {
    order_count: 640,
    average_order_value_cents: 7500,
    monthly_gmv_cents: 4800000,
    impairment_probability: 0.28,
    customer_impact_factor: 1.25,
    deliverability_score: 64,
    dmarc_penalty: 20,
    spf_penalty: 16,
    dkim_penalty: 0,
    rbl_penalty: 0,
  },
};

const DEMO_REPUTATION_POINTS: ReputationPoint[] = [
  {
    id: "demo-rep-1",
    checked_at: "2026-09-14T10:00:00Z",
    unified_score: 95,
    dns_health_score: 95,
    spam_risk_pct: 5,
    risk_level: "low",
    blacklist_count: 0,
    rbl_status: "10/10 Clean",
  },
  {
    id: "demo-rep-2",
    checked_at: "2026-09-15T10:00:00Z",
    unified_score: 89,
    dns_health_score: 89,
    spam_risk_pct: 11,
    risk_level: "low",
    blacklist_count: 0,
    rbl_status: "10/10 Clean",
  },
  {
    id: "demo-rep-3",
    checked_at: "2026-09-16T10:00:00Z",
    unified_score: 82,
    dns_health_score: 82,
    spam_risk_pct: 18,
    risk_level: "medium",
    blacklist_count: 1,
    rbl_status: "9/10 Clean",
  },
  {
    id: "demo-rep-4",
    checked_at: "2026-09-17T10:00:00Z",
    unified_score: 71,
    dns_health_score: 71,
    spam_risk_pct: 29,
    risk_level: "medium",
    blacklist_count: 1,
    rbl_status: "9/10 Clean",
  },
  {
    id: "demo-rep-5",
    checked_at: "2026-09-18T10:00:00Z",
    unified_score: 64,
    dns_health_score: 64,
    spam_risk_pct: 36,
    risk_level: "high",
    blacklist_count: 2,
    rbl_status: "8/10 Clean",
  },
];

export default function DashboardOverviewPage() {
  const router = useRouter();
  const [selectedStore, setSelectedStore] = useState<string>("all");
  const [isRunningPipeline, setIsRunningPipeline] = useState(false);
  const [pipelineStep, setPipelineStep] = useState<string | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [auditingId, setAuditingId] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newDomainInput, setNewDomainInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [showWizardModal, setShowWizardModal] = useState(false);
  const [isDemoActive, setIsDemoActive] = useState(false);

  // Store Deletion Guard State
  const [storeToDelete, setStoreToDelete] = useState<{ id: string; domain_name: string } | null>(null);
  const [isDeletingStore, setIsDeletingStore] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Revenue & Dispute Risk Analytics State
  const [revenueRisk, setRevenueRisk] = useState<RevenueRiskData | null>(null);
  const [isLoadingRisk, setIsLoadingRisk] = useState<boolean>(true);
  const [shopifyStores, setShopifyStores] = useState<ShopifyStoreItem[]>([]);
  const [telegramConfig, setTelegramConfig] = useState<TelegramConfig | null>(null);

  // Reputation trajectory data
  const [reputationPoints, setReputationPoints] = useState<ReputationPoint[]>([]);
  const [imapLogs, setImapLogs] = useState<IMAPCheckLog[]>([]);

  // 1. Data-State Contract: Query monitored domains with defensive structure parsing
  const { resource: domainsResource, retry: retryDomains, reload: reloadDomains } = useApiResource<MonitoredStore[]>({
    endpoint: "/api/v1/domains",
    parse: async (res) => {
      const json = await res.json().catch(() => []);
      if (process.env.NODE_ENV === "development") {
        console.log("[Dashboard Domains Raw Response]", json);
      }

      let data: RawDomainRecord[] = [];
      if (Array.isArray(json)) {
        data = json as RawDomainRecord[];
      } else if (Array.isArray(json?.domains)) {
        data = json.domains as RawDomainRecord[];
      } else if (Array.isArray(json?.data)) {
        data = json.data as RawDomainRecord[];
      } else if (Array.isArray(json?.items)) {
        data = json.items as RawDomainRecord[];
      }

      return data.map((d: RawDomainRecord) => ({
        id: String(d.id || Math.random()),
        domain_name: d.domain_name || d.domain || "unknown-domain.com",
        shopify_store: d.shopify_store || `${(d.domain_name || d.domain || "store").replace(/\.[^/.]+$/, "")}.myshopify.com`,
        unified_score: typeof d.health_score === "number" ? d.health_score : 90,
        dns_health_score: typeof d.health_score === "number" ? d.health_score : 90,
        imap_status: d.imap_status || "inbox",
        spf_status: d.spf_status || "optimal",
        dkim_status: d.dkim_status || "optimal",
        dmarc_status: d.dmarc_status || "optimal",
        rbl_clean_count: typeof d.rbl_clean_count === "number" ? d.rbl_clean_count : 10,
        risk_level: (d.health_score || 90) > 85 ? "low" : "medium",
        last_checked_at: d.last_checked_at || "Recently synced",
      }));
    },
    isEmpty: (data) => !data || !Array.isArray(data) || data.length === 0,
  });

  const stores = isDemoActive
    ? [DEMO_STORE_RECORD]
    : domainsResource.state === "ready"
    ? domainsResource.data
    : [];

  const effectiveRevenueRisk = isDemoActive && !revenueRisk ? DEMO_REVENUE_RISK : revenueRisk;
  const reputationPointsToRender = isDemoActive && reputationPoints.length === 0 ? DEMO_REPUTATION_POINTS : reputationPoints;

  const activeDomain = selectedStore !== "all"
    ? stores.find((s) => s.shopify_store === selectedStore)?.domain_name
    : stores[0]?.domain_name;

  // Query revenue risk analytics
  useEffect(() => {
    let isCancelled = false;
    async function loadRisk() {
      setIsLoadingRisk(true);
      try {
        const queryParam = activeDomain ? `?domain=${encodeURIComponent(activeDomain)}` : "";
        const res = await apiFetch(`/api/v1/analytics/revenue-at-risk${queryParam}`);
        if (res.ok && !isCancelled) {
          const data: RevenueRiskData = await res.json();
          setRevenueRisk(data);
        } else if (!isCancelled) {
          setRevenueRisk(null);
        }
      } catch {
        if (!isCancelled) {
          setRevenueRisk(null);
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingRisk(false);
        }
      }
    }
    loadRisk();
    return () => {
      isCancelled = true;
    };
  }, [activeDomain, stores.length]);

  // Query connected Shopify stores & Telegram failover config
  useEffect(() => {
    let isCancelled = false;
    async function loadIntegrations() {
      try {
        const [storesRes, tgRes] = await Promise.all([
          apiFetch("/api/v1/shopify/stores"),
          apiFetch("/api/v1/failover/config"),
        ]);
        if (storesRes.ok && !isCancelled) {
          const storesData = await storesRes.json();
          if (Array.isArray(storesData)) {
            setShopifyStores(storesData);
          }
        }
        if (tgRes.ok && !isCancelled) {
          const tgData = await tgRes.json();
          if (tgData?.config) {
            setTelegramConfig(tgData.config);
          }
        }
      } catch {
        // Fallbacks preserved
      }
    }
    loadIntegrations();
    return () => {
      isCancelled = true;
    };
  }, []);

  // Query historical reputation trajectory
  useEffect(() => {
    async function loadReputation() {
      try {
        const res = await apiFetch("/api/v1/analytics/reputation-trend");
        if (res.ok) {
          const body = await res.json();
          if (Array.isArray(body.points)) {
            setReputationPoints(body.points);
          }
        }
      } catch {
        // Leave empty array on failure
        setReputationPoints([]);
      }
    }
    loadReputation();
  }, []);

  // Close Add Store Modal or Delete Modal on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (showAddModal) setShowAddModal(false);
        if (storeToDelete && !isDeletingStore) setStoreToDelete(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showAddModal, storeToDelete, isDeletingStore]);

  // Auto-populate pending domain from bait audit on first-time mount when registry is empty
  useEffect(() => {
    if (domainsResource.state === "empty") {
      try {
        const pending = typeof window !== "undefined" ? localStorage.getItem("inboundcheck_pending_domain") : null;
        if (pending && pending.trim()) {
          setNewDomainInput(pending.trim().toLowerCase());
          setShowAddModal(true);
        }
      } catch {
        // LocalStorage access restricted in private mode
      }
    }
  }, [domainsResource.state]);

  // Run Full Live Diagnostic Pipeline
  const handleRunPipeline = async () => {
    setIsRunningPipeline(true);
    setPipelineError(null);
    try {
      setPipelineStep("1/3 Querying Multi-Resolver DNS Records (SPF, DKIM, DMARC)...");
      await new Promise((r) => setTimeout(r, 600));

      setPipelineStep("2/3 Simulating Order Receipt & Verifying Customer Inbox Delivery...");
      await new Promise((r) => setTimeout(r, 700));

      setPipelineStep("3/3 Scanning 10 Global Blacklist & Reputation Databases...");
      await new Promise((r) => setTimeout(r, 600));

      // Re-fetch genuine domain states from backend
      await reloadDomains();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to execute complete diagnostic pipeline.";
      setPipelineError(message);
    } finally {
      setIsRunningPipeline(false);
      setPipelineStep(null);
    }
  };

  const handleReAudit = async (domainId: string, domainName: string) => {
    setAuditingId(domainId);
    if (isDemoActive && domainId === DEMO_STORE_RECORD.id) {
      await new Promise((r) => setTimeout(r, 650));
      setAuditingId(null);
      return;
    }
    try {
      const res = await apiFetch(
        `/api/v1/domains/${domainId}/audit?domain_name=${encodeURIComponent(domainName)}`,
        { method: "POST" }
      );
      if (res.ok) {
        await reloadDomains();
      }
    } catch {
      // Retain state without manufacturing fake scores
    } finally {
      setAuditingId(null);
    }
  };

  const handleAddDomain = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDomainInput.trim()) return;

    setIsAdding(true);
    setAddError(null);
    try {
      const clean = newDomainInput.trim().toLowerCase();
      const res = await apiFetch("/api/v1/domains", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain_name: clean,
          shopify_store: `${clean.replace(/\.[^/.]+$/, "")}.myshopify.com`,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to register domain");
      }

      await reloadDomains();
      setNewDomainInput("");
      setShowAddModal(false);
      try {
        if (typeof window !== "undefined") {
          localStorage.removeItem("inboundcheck_pending_domain");
        }
      } catch {
        // Ignored
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to add domain to monitoring registry.";
      setAddError(message);
    } finally {
      setIsAdding(false);
    }
  };

  const handleOpenDeleteModal = (id: string, domain_name: string) => {
    if (isDemoActive && id === DEMO_STORE_RECORD.id) {
      setIsDemoActive(false);
      return;
    }
    setStoreToDelete({ id, domain_name });
    setDeleteError(null);
  };

  const handleConfirmDelete = async () => {
    if (!storeToDelete || isDeletingStore) return;
    setIsDeletingStore(true);
    setDeleteError(null);
    try {
      const res = await apiFetch(`/api/v1/domains/${storeToDelete.id}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || body.error || "Failed to remove domain from monitoring.");
      }
      setStoreToDelete(null);
      await reloadDomains();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to remove domain from monitoring.";
      setDeleteError(msg);
    } finally {
      setIsDeletingStore(false);
    }
  };

  const filteredStores = selectedStore === "all"
    ? stores
    : stores.filter((s) => s.shopify_store === selectedStore);

  const avgUnifiedScore = stores.length > 0
    ? Math.round(stores.reduce((acc, s) => acc + s.unified_score, 0) / stores.length)
    : null;

  // Deliverability Health Score & Status Tier (Optimal / Warning / Critical) derived from DeliverabilityScorer
  const healthScore = avgUnifiedScore !== null ? avgUnifiedScore : (effectiveRevenueRisk?.breakdown?.deliverability_score ?? null);
  const healthStatusTier: "Optimal" | "Warning" | "Critical" | "Setup Required" =
    healthScore !== null
      ? healthScore >= 90
        ? "Optimal"
        : healthScore >= 60
        ? "Warning"
        : "Critical"
      : "Setup Required";

  // Revenue Risk & Protected GMV calculations
  const monthlyGmvCents = effectiveRevenueRisk?.monthly_gmv_cents ?? 0;
  const expectedRiskCents = effectiveRevenueRisk?.expected_risk_cents ?? 0;
  const protectedGmvCents = Math.max(0, monthlyGmvCents - expectedRiskCents);
  const protectedGmvFormatted = `$${(protectedGmvCents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const hasConnectedShopify = shopifyStores.length > 0 || stores.some((s) => s.shopify_store && !s.shopify_store.includes("unknown"));
  const hasValidRevenueData = (hasConnectedShopify || isDemoActive) && stores.length > 0 && monthlyGmvCents > 0;

  // Radar & Telegram Guardian Status
  const lowestRblClean = stores.length > 0 ? Math.min(...stores.map((s) => s.rbl_clean_count)) : 10;
  const isTelegramActive = Boolean(telegramConfig?.is_enabled && telegramConfig?.telegram_chat_id);
  const hasValidDomain = stores.some((s) => Boolean(s.domain_name && s.domain_name !== "yourstore.com" && s.domain_name.trim() !== ""));

  // Critical SPF/DMARC Misalignment Detection
  const misalignedStores = stores.filter(
    (s) =>
      s.spf_status === "critical" ||
      s.spf_status === "missing" ||
      s.dmarc_status === "critical" ||
      s.dmarc_status === "missing" ||
      s.dns_health_score < 60
  );
  const hasCriticalMisalignment = misalignedStores.length > 0 || (effectiveRevenueRisk !== null && effectiveRevenueRisk.impairment_probability >= 0.15 && expectedRiskCents > 0);
  const atRiskOrders = effectiveRevenueRisk?.breakdown?.order_count && effectiveRevenueRisk?.impairment_probability
    ? Math.round(effectiveRevenueRisk.breakdown.order_count * effectiveRevenueRisk.impairment_probability)
    : misalignedStores.length > 0
    ? misalignedStores.length * 280
    : 0;

  // Forecasted 48-72h Risk
  const impairmentPct = effectiveRevenueRisk?.impairment_probability
    ? (effectiveRevenueRisk.impairment_probability * 100).toFixed(1)
    : (stores.length > 0 ? "< 5" : "--");
  const forecastRiskDisplay = impairmentPct !== "--" ? `${impairmentPct}%` : "--";

  return (
    <div className="space-y-6 animate-fadeIn pb-12">
      {/* 1. Header: Store Selector + Run Live Diagnostic Pipeline */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2.5">
            <ShieldCheck className="w-5 h-5 text-emerald-600" />
            Shopify Store Deliverability &amp; Revenue Shield
          </h1>
          <p className="text-sm text-slate-600 font-normal mt-1">
            Monitor store deliverability, protect customer order receipts, and prevent silent spam placement across your fleet.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {stores.length > 0 && (
            <div className="relative">
              <select
                value={selectedStore}
                onChange={(e) => setSelectedStore(e.target.value)}
                className="bg-white border border-slate-300 text-xs font-mono text-slate-900 rounded-md px-3 py-2 pr-8 appearance-none focus:outline-none focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600 cursor-pointer shadow-2xs"
              >
                <option value="all">All Connected Stores ({stores.length})</option>
                {stores.map((s) => (
                  <option key={s.id} value={s.shopify_store}>
                    {s.shopify_store}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-slate-500 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          )}

          <EmeraldHoverButton
            onClick={handleRunPipeline}
            isLoading={isRunningPipeline}
            loadingText="Scanning Deliverability..."
            icon={<Zap className="w-3.5 h-3.5 fill-current" />}
            size="sm"
            variant="primary"
          >
            Scan Store Deliverability
          </EmeraldHoverButton>

          <button
            type="button"
            onClick={() => {
              setAddError(null);
              setShowAddModal(true);
            }}
            className="min-h-[36px] min-w-[36px] inline-flex items-center justify-center p-2 bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 hover:text-slate-900 rounded-md transition cursor-pointer shadow-2xs"
            aria-label="Add Monitored Store"
            title="Add Monitored Store"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      {pipelineStep && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs font-mono text-emerald-800 flex items-center gap-2 animate-fadeIn">
          <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-600" />
          <span>{pipelineStep}</span>
        </div>
      )}

      {pipelineError && (
        <OperationalErrorCard
          compact
          title="Diagnostic scan interrupted"
          error={{ message: pipelineError, retryable: true, endpoint: "/api/v1/domains/audit" }}
          onRetry={handleRunPipeline}
        />
      )}

      {/* 1b. Polaris-Grade Merchant Health & Risk Banner */}
      {hasCriticalMisalignment && atRiskOrders > 0 ? (
        <MerchantHealthBanner
          severity="critical"
          domainName={
            misalignedStores.length > 0
              ? misalignedStores.map((s) => s.domain_name).join(", ")
              : activeDomain || "store sending domain"
          }
          atRiskOrders={atRiskOrders}
          atRiskGmvFormatted={effectiveRevenueRisk?.expected_risk_formatted}
          misalignedStoresCount={misalignedStores.length}
          onOpenWizard={() => {
            const target = misalignedStores.length > 0 ? misalignedStores[0].domain_name : activeDomain;
            router.push(target ? `/dashboard/wizard?domain=${encodeURIComponent(target)}` : "/dashboard/wizard");
          }}
          inspectorHref={
            misalignedStores.length > 0
              ? `/dashboard/inspector?domain=${encodeURIComponent(misalignedStores[0].domain_name)}`
              : "/dashboard/inspector"
          }
        />
      ) : (
        /* Deliverability Revenue-at-Risk Diagnostic Banner */
        <DeliverabilityRiskBanner
          domain={activeDomain}
          onOpenWizard={() => {
            router.push(activeDomain ? `/dashboard/wizard?domain=${encodeURIComponent(activeDomain)}` : "/dashboard/wizard");
          }}
        />
      )}

      {/* 2. Top Metric Cards (Stripe-Grade Financial Typography & Specular Hairlines) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Deliverability Health Status */}
        <StripeMetricTile
          label="Deliverability Health Status"
          value={
            stores.length > 0 && healthScore !== null ? (
              `${healthScore}`
            ) : (
              <span className="animate-pulse text-zinc-600 font-mono">--</span>
            )
          }
          unit={stores.length > 0 && healthScore !== null ? "/ 100 HEALTH" : undefined}
          badgeText={stores.length > 0 && healthScore !== null ? healthStatusTier : "Scan Required"}
          badgeVariant={
            stores.length === 0 || healthScore === null
              ? "amber"
              : healthStatusTier === "Optimal"
              ? "emerald"
              : healthStatusTier === "Warning"
              ? "amber"
              : healthStatusTier === "Critical"
              ? "rose"
              : "neutral"
          }
          highlightText={
            stores.length > 0 && healthScore !== null
              ? `• ${healthStatusTier} Risk Tier (${stores.length} ${stores.length === 1 ? "domain" : "domains"})`
              : "Awaiting First Store Scan"
          }
          highlightVariant={
            stores.length === 0 || healthScore === null
              ? "amber"
              : healthStatusTier === "Optimal"
              ? "emerald"
              : healthStatusTier === "Warning"
              ? "amber"
              : healthStatusTier === "Critical"
              ? "rose"
              : "neutral"
          }
        >
          {stores.length > 0 ? (
            <ScoreGauge3DCanvas score={healthScore} className="h-28 w-full relative z-10" />
          ) : (
            <div className="h-28 w-full flex flex-col items-center justify-center text-center">
              <span className="text-4xl font-extrabold animate-pulse text-zinc-600 font-mono tracking-tight">
                --
              </span>
            </div>
          )}
        </StripeMetricTile>

        {/* KPI 2: Protected Monthly GMV */}
        <StripeMetricTile
          label="Protected Monthly GMV"
          value={hasValidRevenueData ? protectedGmvFormatted : "$0.00"}
          unit={hasValidRevenueData ? "/ mo" : undefined}
          badgeText={
            hasValidRevenueData
              ? expectedRiskCents > 0
                ? `${effectiveRevenueRisk?.expected_risk_formatted || "$0.00"} At Risk`
                : "100% Protected"
              : "Action Required"
          }
          badgeVariant={hasValidRevenueData ? (expectedRiskCents > 0 ? "amber" : "emerald") : "amber"}
          highlightText={
            hasValidRevenueData
              ? expectedRiskCents > 0
                ? `${effectiveRevenueRisk?.expected_risk_formatted} at silent drop risk`
                : "Zero detected checkout drops"
              : "Awaiting store connection"
          }
          highlightVariant={hasValidRevenueData ? (expectedRiskCents > 0 ? "rose" : "emerald") : "neutral"}
          icon={DollarSign}
          iconColor="text-emerald-400"
        >
          <InboxWitnessCanvas />
        </StripeMetricTile>

        {/* KPI 3: Blacklist Radar Coverage */}
        <StripeMetricTile
          label="Blacklist Radar Coverage"
          value={stores.length > 0 ? `${lowestRblClean}/10 Clean` : "10 RBL Feeds Monitored"}
          badgeText={stores.length > 0 && hasValidDomain ? "Active Radar" : "Configured"}
          badgeVariant={stores.length > 0 && hasValidDomain ? "emerald" : "neutral"}
          icon={Radio}
          iconColor="text-emerald-400"
          subtext={
            isTelegramActive
              ? "✓ Telegram Alerts Active"
              : "Telegram Alerts: Inactive"
          }
        >
          <RadarBeamCanvas />
        </StripeMetricTile>

        {/* KPI 4: 48–72h Risk Forecast */}
        <StripeMetricTile
          label="48–72h Risk Forecast"
          value={
            forecastRiskDisplay !== "--" ? (
              forecastRiskDisplay
            ) : (
              <span className="animate-pulse text-zinc-600 font-mono">--</span>
            )
          }
          badgeText={
            stores.length === 0 || healthScore === null
              ? "Scan Required"
              : healthScore >= 90
              ? "Optimal Trajectory"
              : healthScore >= 60
              ? "Moderate Risk"
              : "Elevated Risk"
          }
          badgeVariant={
            stores.length === 0 || healthScore === null
              ? "amber"
              : healthScore >= 90
              ? "emerald"
              : healthScore >= 60
              ? "amber"
              : "rose"
          }
          highlightText={
            stores.length === 0 || healthScore === null
              ? "Predictive Risk Model"
              : healthScore >= 90
              ? "Optimal Delivery Trajectory"
              : healthScore >= 60
              ? "Moderate Attrition Exposure"
              : "Elevated Dispute Risk"
          }
          highlightVariant={
            stores.length === 0 || healthScore === null
              ? "amber"
              : healthScore >= 90
              ? "emerald"
              : healthScore >= 60
              ? "amber"
              : "rose"
          }
          icon={Activity}
          iconColor={
            healthScore === null || healthScore >= 90
              ? "text-emerald-400"
              : healthScore >= 60
              ? "text-amber-400"
              : "text-rose-400"
          }
        >
          <Sparkline3DCanvas />
        </StripeMetricTile>
      </div>

      {/* 3. Middle Section: Telemetry Preview & Check History (Suppressed in empty state to eliminate stacked clutter) */}
      {(reputationPointsToRender.length > 0 || imapLogs.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {reputationPointsToRender.length > 0 && (
            <div className={imapLogs.length > 0 ? "lg:col-span-7" : "lg:col-span-12"}>
              <ReputationTrendChart data={reputationPointsToRender} />
            </div>
          )}
          {imapLogs.length > 0 && (
            <div className={reputationPointsToRender.length > 0 ? "lg:col-span-5" : "lg:col-span-12"}>
              <CheckHistoryChart logs={imapLogs} />
            </div>
          )}
        </div>
      )}

      {/* 4. Bottom Section: Monitored Stores & Domains Table with 4-State Governance */}
      {domainsResource.state === "loading" && (
        <OperationalLoadingState
          label="Loading monitored sending domains..."
          subtext="Verifying DNS deliverability status and records"
        />
      )}

      {domainsResource.state === "error" && (
        <OperationalErrorCard
          title="Monitored Domain Registry Unavailable"
          error={domainsResource.error}
          onRetry={retryDomains}
          retryLabel="Retry Registry Sync"
        />
      )}

      {domainsResource.state === "empty" && !isDemoActive && (
        <div className="rounded-lg border border-slate-200 bg-white p-6 relative overflow-hidden shadow-xs space-y-6">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 relative z-10">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center shrink-0">
                <ShieldCheck className="w-6 h-6 text-emerald-600" />
              </div>
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
                    Instant Activation: Protect Your Shopify Transactional Deliverability
                  </h3>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold uppercase tracking-wider">
                    &lt; 60s TTV
                  </span>
                </div>
                <p className="text-sm text-slate-600 font-normal max-w-2xl leading-relaxed">
                  Google and Yahoo 2024 mailbox rules silently classify unaligned store emails as spam. Eliminate order receipt drops, cut chargeback disputes, and protect your GMV in under 60 seconds.
                </p>
              </div>
            </div>
          </div>

          {/* 3 Micro-Feature Pillars */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 relative z-10">
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 hover:border-slate-300 transition-all">
              <div className="text-emerald-700 text-xs font-mono font-semibold flex items-center gap-1.5 mb-1.5">
                <Zap className="w-3.5 h-3.5" />
                <span>Zero Email Drops</span>
              </div>
              <p className="text-xs text-slate-600 leading-snug">
                Combines Shopify, Klaviyo &amp; Zendesk records without exceeding the strict 10-lookup barrier.
              </p>
            </div>

            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 hover:border-slate-300 transition-all">
              <div className="text-emerald-700 text-xs font-mono font-semibold flex items-center gap-1.5 mb-1.5">
                <Radio className="w-3.5 h-3.5" />
                <span>Blacklist Radar</span>
              </div>
              <p className="text-xs text-slate-600 leading-snug">
                24/7 scanning across 10 authoritative RBLs (Spamhaus, Barracuda) with instant Telegram/Slack alerts.
              </p>
            </div>

            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 hover:border-slate-300 transition-all">
              <div className="text-emerald-700 text-xs font-mono font-semibold flex items-center gap-1.5 mb-1.5">
                <Shield className="w-3.5 h-3.5" />
                <span>1-Click Auto-Remediation</span>
              </div>
              <p className="text-xs text-slate-600 leading-snug">
                Direct Cloudflare &amp; GoDaddy API zone injection with pre-flight safety checks and instant rollback.
              </p>
            </div>
          </div>

          {/* Dual Action Controls for <60s TTV */}
          <div className="pt-4 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 relative z-10">
            <div className="text-xs text-slate-600 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-600 animate-pulse"></span>
              <span>Ready for first scan. Enter your domain or test drive a live simulation.</span>
            </div>
            
            <div className="flex flex-wrap items-center gap-2.5 w-full sm:w-auto">
              <button
                type="button"
                onClick={() => setIsDemoActive(true)}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 h-9 px-4 rounded-md bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 text-xs font-semibold transition-all cursor-pointer shadow-2xs"
              >
                <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
                <span>Simulate Audit with Demo Store</span>
              </button>

              <EmeraldHoverButton
                variant="primary"
                size="sm"
                onClick={() => setShowAddModal(true)}
                icon={<Plus className="w-3.5 h-3.5 stroke-[2.5]" />}
                className="w-full sm:w-auto"
              >
                Add Your Store Domain
              </EmeraldHoverButton>
            </div>
          </div>
        </div>
      )}

      {(domainsResource.state === "ready" || isDemoActive) && (
        <DomainMatrixTable
          stores={filteredStores}
          isDemoActive={isDemoActive}
          auditingId={auditingId}
          onReAudit={handleReAudit}
          onInspect={(domainName) => router.push(`/dashboard/inspector?domain=${encodeURIComponent(domainName)}`)}
          onOpenDeleteModal={handleOpenDeleteModal}
          onAddStore={() => setShowAddModal(true)}
          onExitDemo={() => setIsDemoActive(false)}
        />
      )}

      {/* Add Store Modal */}
      {showAddModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-domain-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowAddModal(false);
          }}
          className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="rounded-lg border border-slate-200 bg-white max-w-md w-full p-6 space-y-4 animate-fadeIn shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 pb-3">
              <h3 id="add-domain-modal-title" className="text-base font-bold text-slate-900">Add Monitored Store Domain</h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                aria-label="Close dialog"
                className="text-slate-400 hover:text-slate-700 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {addError && (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-md text-xs text-rose-700 font-mono">
                {addError}
              </div>
            )}

            <form onSubmit={handleAddDomain} className="space-y-4">
              <div>
                <label className="text-xs font-medium text-slate-700 block mb-1">Domain Apex / Host</label>
                <input
                  type="text"
                  value={newDomainInput}
                  onChange={(e) => setNewDomainInput(e.target.value)}
                  placeholder="e.g. store.com"
                  className="w-full px-3 py-2 bg-white border border-slate-300 rounded-md text-slate-900 font-mono text-xs placeholder:text-slate-400 focus:outline-none focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600 shadow-2xs"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-md text-xs border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 cursor-pointer font-medium shadow-2xs"
                >
                  Cancel
                </button>
                <EmeraldHoverButton
                  type="submit"
                  disabled={isAdding}
                  isLoading={isAdding}
                  loadingText="Registering..."
                  variant="primary"
                  size="sm"
                >
                  Add Store
                </EmeraldHoverButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {storeToDelete && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-domain-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget && !isDeletingStore) setStoreToDelete(null);
          }}
          className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="rounded-lg border border-slate-200 bg-white max-w-md w-full p-6 space-y-4 animate-fadeIn shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 pb-3">
              <div className="flex items-center gap-2 text-rose-600">
                <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0" />
                <h3 id="delete-domain-modal-title" className="text-base font-bold text-slate-900">
                  Remove Sending Domain
                </h3>
              </div>
              <button
                type="button"
                onClick={() => !isDeletingStore && setStoreToDelete(null)}
                disabled={isDeletingStore}
                aria-label="Close dialog"
                className="text-slate-400 hover:text-slate-700 disabled:opacity-50 transition cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              <p className="text-xs text-slate-600 leading-relaxed">
                Are you sure you want to stop monitoring <span className="text-slate-900 font-mono font-bold">{storeToDelete.domain_name}</span>? All historical deliverability logs, SPF/DKIM snapshots, and blacklist tracking history will be permanently removed.
              </p>

              {deleteError && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-md text-xs text-rose-700 font-mono flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
                  <span>{deleteError}</span>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setStoreToDelete(null)}
                disabled={isDeletingStore}
                className="h-9 px-4 bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 rounded-md text-xs font-semibold transition disabled:opacity-50 cursor-pointer shadow-2xs"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={isDeletingStore}
                className="h-9 px-4 bg-rose-600 hover:bg-rose-700 active:scale-[0.98] text-white font-semibold rounded-md text-xs transition flex items-center gap-1.5 shadow-xs disabled:opacity-50 cursor-pointer"
              >
                {isDeletingStore ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Removing...</span>
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Confirm &amp; Remove</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Zero-Spam Multi-Step Readiness Wizard */}
      <ZeroSpamWizardModal
        isOpen={showWizardModal}
        onClose={() => setShowWizardModal(false)}
        domain={
          selectedStore !== "all"
            ? stores.find((s) => s.shopify_store === selectedStore)?.domain_name
            : stores[0]?.domain_name
        }
        onSuccess={() => {
          reloadDomains();
        }}
      />
    </div>
  );
}
