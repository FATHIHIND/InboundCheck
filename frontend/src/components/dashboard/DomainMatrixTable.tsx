"use client";

import React from "react";
import Link from "next/link";
import {
  Shield,
  RefreshCw,
  Terminal,
  Trash2,
  Sparkles,
  Inbox,
  AlertTriangle,
  XCircle,
} from "lucide-react";
import { MonitoredStore } from "@/app/dashboard/page";

export interface DomainMatrixTableProps {
  stores: MonitoredStore[];
  isDemoActive?: boolean;
  auditingId?: string | null;
  onReAudit: (id: string, domainName: string) => void;
  onInspect: (domainName: string) => void;
  onOpenDeleteModal: (id: string, domainName: string) => void;
  onAddStore: () => void;
  onExitDemo?: () => void;
}

export function DomainMatrixTable({
  stores,
  isDemoActive = false,
  auditingId,
  onReAudit,
  onInspect,
  onOpenDeleteModal,
  onAddStore,
  onExitDemo,
}: DomainMatrixTableProps) {
  const renderProtocolPill = (status: string, label: string) => {
    const isOptimal = status === "optimal";
    const isWarn = status === "warning" || status === "warn";
    const isMissing = status === "missing" || status === "failed" || status === "critical";

    const badgeClass = isOptimal
      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
      : isWarn
      ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
      : "bg-rose-500/10 text-rose-400 border-rose-500/30";

    const dotClass = isOptimal
      ? "bg-emerald-400"
      : isWarn
      ? "bg-amber-400"
      : "bg-rose-400";

    return (
      <span className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full inline-flex items-center gap-1.5 border ${badgeClass}`}>
        <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${dotClass}`} />
        {status.toUpperCase()}
      </span>
    );
  };

  const renderPlacementPill = (score: number) => {
    if (score >= 85) {
      return (
        <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1 w-fit">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <Inbox className="w-3 h-3" />
          INBOX
        </span>
      );
    }
    if (score >= 60) {
      return (
        <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1 w-fit">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
          <AlertTriangle className="w-3 h-3" />
          AT RISK
        </span>
      );
    }
    return (
      <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1 w-fit">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" />
        <XCircle className="w-3 h-3" />
        FAILING
      </span>
    );
  };

  return (
    <div className="rounded-xl border border-white/[0.08] bg-[#0A0A0C] overflow-hidden shadow-2xl">
      {/* Live Mock Simulation Header Banner */}
      {isDemoActive && (
        <div className="p-4 border-b border-emerald-500/20 bg-gradient-to-r from-emerald-950/40 via-[#0A0A0C] to-cyan-950/40 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center shrink-0">
              <Sparkles className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <div className="text-xs font-bold text-white flex items-center gap-2">
                <span>Interactive Simulation Mode: {stores[0]?.domain_name || "allure-apparel.com"}</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-semibold uppercase">
                  Live Mock Scenario
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 mt-0.5">
                Simulating store DNS audit scenario: 3 misconfigured records, estimated $2,400/wk delivery risk, and 1-click repair triggers.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onAddStore}
              className="px-3.5 py-2 bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs rounded-xl transition-all shadow-[0_0_15px_rgba(16,185,129,0.25)] min-h-[44px]"
            >
              Add Real Store Domain →
            </button>
            {onExitDemo && (
              <button
                type="button"
                onClick={onExitDemo}
                className="px-3 py-2 bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white font-mono text-xs rounded-xl border border-white/10 transition-colors min-h-[44px]"
              >
                Exit Demo
              </button>
            )}
          </div>
        </div>
      )}

      {/* Carbon Table Toolbar */}
      <div className="p-4 sm:p-5 border-b border-white/[0.06] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-[#0E1217]">
        <div>
          <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
            <Shield className="w-4 h-4 text-emerald-400" />
            Monitored Stores &amp; Verified Sending Domains
          </h3>
          <p className="text-xs text-zinc-400 mt-0.5">
            Live DNS records, customer inbox placement status, and on-demand diagnostic inspector.
          </p>
        </div>
        <span className="text-[10px] font-mono font-semibold text-zinc-400 px-2.5 py-0.5 rounded-full bg-[#0A0A0C] border border-white/[0.08]">
          {stores.length} Active Stores
        </span>
      </div>

      {/* Dense High-Precision Data Grid */}
      <div className="overflow-x-auto max-h-[560px] overflow-y-auto scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent hover:scrollbar-thumb-emerald-500/40">
        <table className="w-full text-left text-xs font-mono border-collapse" role="grid">
          <thead className="sticky top-0 z-10 bg-[#0E1217] backdrop-blur-md border-b border-white/[0.08] text-[10px] font-mono uppercase tracking-wider text-zinc-400">
            <tr>
              <th scope="col" className="py-3 px-4 font-semibold text-left">Domain Name</th>
              <th scope="col" className="py-3 px-4 font-semibold text-left">Shopify Store</th>
              <th scope="col" className="py-3 px-4 font-semibold text-left">Placement</th>
              <th scope="col" className="py-3 px-4 font-semibold text-left">SPF</th>
              <th scope="col" className="py-3 px-4 font-semibold text-left">DKIM</th>
              <th scope="col" className="py-3 px-4 font-semibold text-left">DMARC</th>
              <th scope="col" className="py-3 px-4 font-semibold text-center">Score</th>
              <th scope="col" className="py-3 px-4 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05] text-zinc-300">
            {stores.map((store) => (
              <tr
                key={store.id}
                onClick={() => onInspect(store.domain_name)}
                className={`carbon-table-row cursor-pointer transition-colors ${
                  auditingId === store.id
                    ? "bg-emerald-500/5 border-l-2 border-l-emerald-500/40"
                    : "hover:bg-white/[0.02]"
                }`}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    onInspect(store.domain_name);
                  }
                }}
              >
                {/* Domain Name */}
                <td className="py-3 px-4 font-bold text-white flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
                  <span className="truncate max-w-[180px] sm:max-w-[280px] inline-block" title={store.domain_name}>
                    {store.domain_name}
                  </span>
                </td>

                {/* Shopify Store */}
                <td className="py-3 px-4 text-zinc-400 text-[11px]">
                  {store.shopify_store}
                </td>

                {/* Placement */}
                <td className="py-3 px-4">
                  {renderPlacementPill(store.unified_score)}
                </td>

                {/* Protocol Badges */}
                <td className="py-3 px-4">{renderProtocolPill(store.spf_status, "SPF")}</td>
                <td className="py-3 px-4">{renderProtocolPill(store.dkim_status, "DKIM")}</td>
                <td className="py-3 px-4">{renderProtocolPill(store.dmarc_status, "DMARC")}</td>

                {/* Unified Score */}
                <td className="py-3 px-4 text-center">
                  <span className={`font-bold tabular-nums text-xs inline-flex items-center gap-1 ${
                    store.unified_score >= 85
                      ? "text-emerald-400"
                      : store.unified_score >= 60
                      ? "text-amber-400"
                      : "text-rose-400"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      store.unified_score >= 85 ? "bg-emerald-400" : store.unified_score >= 60 ? "bg-amber-400" : "bg-rose-400"
                    }`} />
                    {store.unified_score}%
                  </span>
                </td>

                {/* Actions */}
                <td className="py-3 px-4 text-right">
                  <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      onClick={() => onReAudit(store.id, store.domain_name)}
                      disabled={auditingId === store.id}
                      className="min-h-[38px] px-2.5 py-1.5 bg-[#0A0A0C] hover:bg-[#121820] border border-white/[0.08] hover:border-emerald-500/40 text-zinc-300 font-bold rounded-lg transition-all text-xs inline-flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                      title="Run on-demand DNS audit"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${auditingId === store.id ? "animate-spin text-emerald-400" : ""}`} />
                      <span>Audit</span>
                    </button>

                    <Link
                      href={`/dashboard/inspector?domain=${encodeURIComponent(store.domain_name)}`}
                      className="min-h-[38px] px-2.5 py-1.5 bg-[#0A0A0C] hover:bg-[#121820] border border-white/[0.08] hover:border-emerald-500/40 text-emerald-400 font-bold rounded-lg transition-all text-xs inline-flex items-center gap-1.5"
                      title="Open full inspector"
                    >
                      <Terminal className="w-3.5 h-3.5" />
                      <span>Inspect</span>
                    </Link>

                    <button
                      type="button"
                      onClick={() => onOpenDeleteModal(store.id, store.domain_name)}
                      className="min-h-[38px] min-w-[38px] p-2 bg-[#0A0A0C] hover:bg-rose-500/10 border border-white/[0.08] hover:border-rose-500/30 text-zinc-500 hover:text-rose-400 rounded-lg transition inline-flex items-center justify-center cursor-pointer"
                      title="Delete monitored domain"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
