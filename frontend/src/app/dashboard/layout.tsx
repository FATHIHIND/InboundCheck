"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import {
  LayoutDashboard,
  Radio,
  ShoppingBag,
  Sliders,
  LogOut,
  CreditCard,
  Sparkles,
  TerminalSquare,
  Menu,
  X,
  ShieldCheck,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { BackendStatusBadge } from "@/components/operational/BackendStatusBadge";
import { apiFetch } from "@/lib/api";
import { TrialCountdownBanner } from "@/components/billing/TrialCountdownBanner";
import { ObsidianPaywallModal } from "@/components/billing/ObsidianPaywallModal";

interface SubscriptionState {
  tier: string;
  subscription_status: string;
  trial_days_remaining: number;
  trial_ends_at: string | null;
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionState | null>(null);

  // Load authenticated user profile details and subscription status
  useEffect(() => {
    async function loadUserAndSubscription() {
      try {
        const supabase = createClient();
        const { data: { user } } = await supabase.auth.getUser();
        if (user?.email) {
          setUserEmail(user.email);
        }

        const subRes = await apiFetch("/api/v1/billing/subscription");
        if (subRes.ok) {
          const subData = await subRes.json();
          setSubscription({
            tier: subData.subscription_tier || subData.tier || "starter",
            subscription_status: subData.subscription_status || "trialing",
            trial_days_remaining: subData.trial_days_remaining ?? 3,
            trial_ends_at: subData.trial_ends_at || null,
          });
        }
      } catch {
        // Fallback gracefully in offline / dev mode
      }
    }
    loadUserAndSubscription();
  }, [pathname]);

  // Automatically close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [pathname]);

  // Close mobile menu via Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileMenuOpen(false);
      }
    };
    if (mobileMenuOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileMenuOpen]);

  const handleSignOut = async () => {
    try {
      const supabase = createClient();
      await supabase.auth.signOut();
    } catch {
      // Ignored in local dev mode
    }
    router.push("/");
    router.refresh();
  };

  const isOverviewActive = pathname === "/dashboard";
  const isStoresActive = pathname.startsWith("/dashboard/shopify") || pathname.startsWith("/dashboard/wizard");
  const isActionCenterActive = pathname.startsWith("/dashboard/inspector") || pathname.startsWith("/dashboard/radar");
  const isSettingsActive = pathname.startsWith("/dashboard/settings") || pathname.startsWith("/dashboard/billing");
  const isOptimizerActive = pathname.startsWith("/dashboard/content-lab");

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col md:flex-row font-sans">
      {/* Mobile Top Header */}
      <div className="md:hidden flex items-center justify-between p-4 border-b border-slate-200 bg-white sticky top-0 z-50 shadow-2xs">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center">
            <svg
              className="w-3.5 h-3.5 text-emerald-700"
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
          <span className="font-bold text-sm tracking-tight text-slate-900">inboundcheck</span>
          <span className="text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded">
            PRO
          </span>
        </Link>
        <button
          type="button"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Toggle navigation menu"
          aria-expanded={mobileMenuOpen}
          className="p-2 text-slate-500 hover:text-slate-900 transition-colors cursor-pointer"
        >
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile Backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/40 backdrop-blur-xs md:hidden"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Streamlined Enterprise Governance Sidebar (Style Option A) */}
      <aside
        className={`fixed md:sticky top-0 left-0 z-40 h-screen w-64 bg-white border-r border-slate-200 flex flex-col justify-between p-4 transition-transform duration-200 shadow-xs ${
          mobileMenuOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="space-y-6 overflow-y-auto pr-1">
          {/* Logo Header */}
          <Link href="/dashboard" className="px-2 py-2 flex items-center gap-3 group">
            <div className="w-8 h-8 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center transition-colors group-hover:border-emerald-300">
              <svg
                className="w-4 h-4 text-emerald-700"
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
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-bold text-base tracking-tight text-slate-900">inboundcheck</span>
                <span className="text-[10px] font-mono font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded">
                  PRO
                </span>
              </div>
              <span className="text-xs font-semibold text-emerald-700 font-mono tracking-normal">Shopify Email Shield</span>
            </div>
          </Link>

          {/* Merchant-Centric Governance Navigation */}
          <nav className="space-y-1 font-sans" aria-label="Main merchant navigation">
            <span className="text-slate-400 font-bold text-[10px] tracking-widest uppercase pl-2 mb-2 block font-mono">
              MERCHANT PLATFORM
            </span>

            {/* 1. Overview */}
            <Link
              href="/dashboard"
              aria-current={isOverviewActive ? "page" : undefined}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md transition-colors text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                isOverviewActive
                  ? "text-emerald-800 bg-emerald-50 border-r-2 border-emerald-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              }`}
            >
              <LayoutDashboard strokeWidth={2} size={18} />
              <span>Overview</span>
            </Link>

            {/* 2. Stores & Domains */}
            <Link
              href="/dashboard/shopify"
              aria-current={isStoresActive ? "page" : undefined}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md transition-colors text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                isStoresActive
                  ? "text-emerald-800 bg-emerald-50 border-r-2 border-emerald-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              }`}
            >
              <ShoppingBag strokeWidth={2} size={18} />
              <span>Stores &amp; Domains</span>
            </Link>

            {/* 3. Action Center */}
            <Link
              href="/dashboard/inspector"
              aria-current={isActionCenterActive ? "page" : undefined}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md transition-colors text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                isActionCenterActive
                  ? "text-emerald-800 bg-emerald-50 border-r-2 border-emerald-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              }`}
            >
              <ShieldCheck strokeWidth={2} size={18} />
              <span>Action Center</span>
            </Link>

            {/* 4. Settings & Billing */}
            <Link
              href="/dashboard/settings"
              aria-current={isSettingsActive ? "page" : undefined}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md transition-colors text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                isSettingsActive
                  ? "text-emerald-800 bg-emerald-50 border-r-2 border-emerald-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              }`}
            >
              <Sliders strokeWidth={2} size={18} />
              <span>Settings &amp; Billing</span>
            </Link>

            {/* 5. Template Optimizer */}
            <Link
              href="/dashboard/content-lab"
              aria-current={isOptimizerActive ? "page" : undefined}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md transition-colors text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                isOptimizerActive
                  ? "text-emerald-800 bg-emerald-50 border-r-2 border-emerald-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              }`}
            >
              <Sparkles strokeWidth={2} size={18} />
              <span>Template Optimizer</span>
            </Link>
          </nav>
        </div>

        {/* Compact Single-Row User Profile & Operational Footer */}
        <div className="pt-3 border-t border-slate-200 space-y-2 font-sans text-xs">
          <div className="flex items-center justify-between px-1">
            <BackendStatusBadge />
            <Link
              href="/dashboard/settings"
              title="Store Settings & Alerts"
              className="p-1.5 rounded-md text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors flex items-center gap-1 text-[11px]"
            >
              <Sliders size={14} />
            </Link>
          </div>

          {/* Consolidated Compact Profile Bar */}
          <div className="flex items-center justify-between px-2.5 py-2 rounded-lg bg-slate-50 border border-slate-200 gap-2 shadow-2xs">
            <div className="flex items-center gap-2 min-w-0">
              <div className="relative shrink-0">
                <div className="w-7 h-7 rounded-md bg-emerald-100 border border-emerald-200 flex items-center justify-center text-emerald-800 font-bold text-xs font-mono">
                  {userEmail ? userEmail.charAt(0).toUpperCase() : "M"}
                </div>
                {/* Inline green pulse dot for active monitoring */}
                <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-500 border border-white" />
              </div>
              <div className="min-w-0">
                <span className="block max-w-[120px] truncate text-xs font-medium text-slate-800">
                  {userEmail ? userEmail.split("@")[0] : "Merchant"}
                </span>
              </div>
            </div>

            {/* Compact logout icon button */}
            <button
              type="button"
              onClick={handleSignOut}
              title="Sign Out"
              aria-label="Sign Out"
              className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors cursor-pointer shrink-0"
            >
              <LogOut strokeWidth={2} size={15} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main App Canvas */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto bg-slate-50">
        {/* Sticky Trial Countdown Banner */}
        {subscription?.subscription_status === "trialing" && (
          <TrialCountdownBanner
            daysRemaining={subscription.trial_days_remaining}
            trialEndsAt={subscription.trial_ends_at}
          />
        )}

        <main className="flex-1 min-w-0 p-4 sm:p-6 md:p-8">
          <div className="max-w-7xl mx-auto space-y-6">
            {children}
          </div>
        </main>

        {/* Full-Screen Paywall Modal on Expiration */}
        {subscription?.subscription_status === "expired" && pathname !== "/dashboard/billing" && (
          <ObsidianPaywallModal />
        )}
      </div>
    </div>
  );
}
