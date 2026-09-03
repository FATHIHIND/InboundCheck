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
  X
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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

  const isActive = (path: string) => pathname === path;

  return (
    <div className="min-h-screen bg-[#08080A] text-white flex flex-col md:flex-row font-sans">
      {/* Mobile Top Header */}
      <div className="md:hidden flex items-center justify-between p-4 border-b border-white/[0.08] bg-[#0E0E12]/95 backdrop-blur-md sticky top-0 z-50">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shadow-[0_0_12px_rgba(16,185,129,0.25)]">
            <svg
              className="w-3.5 h-3.5 text-emerald-400"
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
          <span className="font-bold text-sm tracking-tight text-white">inboundcheck</span>
          <span className="text-[10px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.5 rounded">
            PRO
          </span>
        </Link>
        <button
          type="button"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Toggle navigation menu"
          aria-expanded={mobileMenuOpen}
          className="p-2 text-zinc-400 hover:text-white transition cursor-pointer"
        >
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile Backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/70 backdrop-blur-xs md:hidden"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Streamlined Enterprise Governance Sidebar */}
      <aside
        className={`fixed md:sticky top-0 left-0 z-40 h-screen w-64 bg-[#08080A] border-r border-white/[0.08] flex flex-col justify-between p-4 transition-transform duration-200 ${
          mobileMenuOpen ? "translate-x-0 bg-[#0E0E12]" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="space-y-6 overflow-y-auto pr-1">
          {/* Bespoke Emerald SVG Logo Header */}
          <Link href="/dashboard" className="px-2 py-2 flex items-center gap-3 group">
            <div className="w-8 h-8 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shadow-[0_0_15px_rgba(16,185,129,0.2)] group-hover:border-emerald-500/50 group-hover:shadow-[0_0_20px_rgba(16,185,129,0.35)] transition duration-200">
              <svg
                className="w-4 h-4 text-emerald-400"
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
                <span className="font-bold text-base tracking-tight text-white">inboundcheck</span>
                <span className="text-[10px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.5 rounded">
                  PRO
                </span>
              </div>
              <span className="text-xs text-zinc-500 font-mono tracking-wide">DNS & Deliverability Hub</span>
            </div>
          </Link>

          {/* Governance Navigation Groups */}
          <div className="space-y-6 text-xs">
            {/* Group 1: Core Governance */}
            <div className="space-y-1">
              <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400/70 uppercase font-semibold pl-2 mb-2 select-none block">
                CORE GOVERNANCE
              </span>
              <Link
                href="/dashboard"
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <LayoutDashboard strokeWidth={1.75} size={18} />
                <span>Overview</span>
              </Link>
              <Link
                href="/dashboard/shopify"
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard/shopify")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <ShoppingBag strokeWidth={1.75} size={18} />
                <span>Shopify Sync</span>
              </Link>
            </div>

            {/* Group 2: Diagnostics & Radar */}
            <div className="space-y-1">
              <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400/70 uppercase font-semibold pl-2 mb-2 select-none block">
                DIAGNOSTICS & RADAR
              </span>
              <Link
                href="/dashboard/inspector"
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard/inspector")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <TerminalSquare strokeWidth={1.75} size={18} />
                <span>DNS Inspector</span>
              </Link>
              <Link
                href="/dashboard/radar"
                className={`flex items-center justify-between px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard/radar")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Radio strokeWidth={1.75} size={18} />
                  <span>Blacklist Radar</span>
                </div>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              </Link>
              <Link
                href="/dashboard/content-lab"
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard/content-lab")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <Sparkles strokeWidth={1.75} size={18} />
                <span>AI Content Lab</span>
              </Link>
            </div>

            {/* Group 3: Configuration */}
            <div className="space-y-1">
              <span className="text-[10px] font-mono tracking-[0.2em] text-emerald-400/70 uppercase font-semibold pl-2 mb-2 select-none block">
                CONFIGURATION
              </span>
              <Link
                href="/dashboard/settings"
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard/settings")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <Sliders strokeWidth={1.75} size={18} />
                <span>Alerts & Settings</span>
              </Link>
              <Link
                href="/dashboard/billing"
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors duration-150 font-medium ${
                  isActive("/dashboard/billing")
                    ? "text-emerald-400 bg-emerald-500/[0.08] border border-emerald-500/20"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <CreditCard strokeWidth={1.75} size={18} />
                <span>Billing Portal</span>
              </Link>
            </div>
          </div>
        </div>

        {/* Bottom Status & Sign Out */}
        <div className="pt-4 border-t border-white/[0.08] space-y-2 font-mono text-xs">
          <div className="flex items-center justify-between px-2 text-zinc-400">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[11px] text-zinc-300">Live Telemetry</span>
            </div>
            <span className="text-[10px] text-zinc-500 font-mono">RFC 1035</span>
          </div>

          <button
            type="button"
            onClick={handleSignOut}
            className="w-full flex items-center gap-2 px-3 py-2 text-zinc-400 hover:text-red-400 rounded-lg hover:bg-white/[0.02] transition-colors duration-150 cursor-pointer text-xs font-sans"
          >
            <LogOut strokeWidth={1.75} size={16} />
            <span>Logout</span>
          </button>
        </div>
      </aside>

      {/* Main App Canvas */}
      <main className="flex-1 min-w-0 p-4 sm:p-6 md:p-8 overflow-y-auto">
        <div className="max-w-7xl mx-auto space-y-6">
          {children}
        </div>
      </main>
    </div>
  );
}
