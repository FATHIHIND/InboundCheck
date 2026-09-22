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

    const badgeClass = isOptimal
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : isWarn
      ? "bg-amber-50 text-amber-700 border-amber-200"
      : "bg-rose-50 text-rose-700 border-rose-200";

    const dotClass = isOptimal
      ? "bg-emerald-500"
      : isWarn
      ? "bg-amber-500"
      : "bg-rose-500";

    return (
      <span className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full inline-flex items-center gap-1.5 border ${badgeClass}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
        {status.toUpperCase()}
      </span>
    );
  };

  const renderPlacementPill = (score: number) => {
    if (score >= 85) {
      return (
        <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1 w-fit">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          <Inbox className="w-3 h-3" />
          INBOX
        </span>
      );
    }
    if (score >= 60) {
      return (
        <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1 w-fit">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          <AlertTriangle className="w-3 h-3" />
          AT RISK
        </span>
      );
    }
    return (
      <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 flex items-center gap-1 w-fit">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
        <XCircle className="w-3 h-3" />
        FAILING
      </span>
    );
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden shadow-xs">
      {/* Live Mock Simulation Header Banner */}
      {isDemoActive && (
        <div className="p-4 border-b border-emerald-200 bg-emerald-50/70 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 border border-emerald-300 flex items-center justify-center shrink-0">
              <Sparkles className="w-4 h-4 text-emerald-700" />
            </div>
            <div>
              <div className="text-xs font-bold text-slate-900 flex items-center gap-2">
                <span>Interactive Simulation Mode: {stores[0]?.domain_name || "allure-apparel.com"}</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-semibold uppercase">
                  Live Mock Scenario
                </span>
              </div>
              <p className="text-[11px] text-slate-600 mt-0.5">
                Simulating store DNS audit scenario: 3 misconfigured records, estimated $2,400/wk delivery risk, and 1-click repair triggers.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onAddStore}
              className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs rounded-md transition-colors shadow-xs"
            >
              Add Real Store Domain →
            </button>
            {onExitDemo && (
              <button
                type="button"
                onClick={onExitDemo}
                className="px-3 py-1.5 bg-white hover:bg-slate-100 text-slate-700 font-mono text-xs rounded-md border border-slate-300 transition-colors"
              >
                Exit Demo
              </button>
            )}
          </div>
        </div>
      )}

      {/* Financial Table Toolbar */}
      <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-white">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 tracking-tight flex items-center gap-2">
            <Shield className="w-4 h-4 text-emerald-600" />
            Monitored Stores &amp; Verified Sending Domains
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Live DNS records, customer inbox placement status, and on-demand diagnostic inspector.
          </p>
        </div>
        <span className="text-[11px] font-mono font-medium text-slate-600 px-2.5 py-0.5 rounded-full bg-slate-100 border border-slate-200">
          {stores.length} Active Stores
        </span>
      </div>

      {/* Dense High-Precision Data Grid */}
      <div className="overflow-x-auto max-h-[560px] overflow-y-auto scrollbar-thin">
        <table className="w-full text-left text-xs font-mono border-collapse" role="grid">
          <thead className="sticky top-0 z-10 bg-slate-50 border-b border-slate-200 text-[11px] font-mono font-semibold uppercase tracking-wider text-slate-600">
            <tr>
              <th scope="col" className="py-3 px-4 text-left">Domain Name</th>
              <th scope="col" className="py-3 px-4 text-left">Shopify Store</th>
              <th scope="col" className="py-3 px-4 text-left">Placement</th>
              <th scope="col" className="py-3 px-4 text-left">SPF</th>
              <th scope="col" className="py-3 px-4 text-left">DKIM</th>
              <th scope="col" className="py-3 px-4 text-left">DMARC</th>
              <th scope="col" className="py-3 px-4 text-center">Score</th>
              <th scope="col" className="py-3 px-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-700 bg-white">
            {stores.map((store) => (
              <tr
                key={store.id}
                onClick={() => onInspect(store.domain_name)}
                className={`cursor-pointer transition-colors ${
                  auditingId === store.id
                    ? "bg-emerald-50/60 border-l-2 border-l-emerald-600"
                    : "hover:bg-slate-50/80"
                }`}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    onInspect(store.domain_name);
                  }
                }}
              >
                {/* Domain Name */}
                <td className="py-3 px-4 font-semibold text-slate-900 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                  <span className="truncate max-w-[180px] sm:max-w-[280px] inline-block" title={store.domain_name}>
                    {store.domain_name}
                  </span>
                </td>

                {/* Shopify Store */}
                <td className="py-3 px-4 text-slate-500 text-[11px]">
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
                      ? "text-emerald-700"
                      : store.unified_score >= 60
                      ? "text-amber-700"
                      : "text-rose-700"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      store.unified_score >= 85 ? "bg-emerald-500" : store.unified_score >= 60 ? "bg-amber-500" : "bg-rose-500"
                    }`} />
                    {store.unified_score}%
                  </span>
                </td>

                {/* Actions */}
                <td className="py-3 px-4 text-right">
                  <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      onClick={() => onReAudit(store.id, store.domain_name)}
                      disabled={auditingId === store.id}
                      className="px-2.5 py-1.5 bg-white hover:bg-slate-50 border border-slate-200 hover:border-slate-300 text-slate-700 font-semibold rounded-md shadow-2xs transition-colors text-xs inline-flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                      title="Run on-demand DNS audit"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${auditingId === store.id ? "animate-spin text-emerald-600" : ""}`} />
                      <span>Audit</span>
                    </button>

                    <Link
                      href={`/dashboard/inspector?domain=${encodeURIComponent(store.domain_name)}`}
                      className="px-2.5 py-1.5 bg-white hover:bg-slate-50 border border-slate-200 hover:border-slate-300 text-emerald-700 font-semibold rounded-md shadow-2xs transition-colors text-xs inline-flex items-center gap-1.5"
                      title="Open full inspector"
                    >
                      <Terminal className="w-3.5 h-3.5" />
                      <span>Inspect</span>
                    </Link>

                    <button
                      type="button"
                      onClick={() => onOpenDeleteModal(store.id, store.domain_name)}
                      className="p-1.5 bg-white hover:bg-rose-50 border border-slate-200 hover:border-rose-200 text-slate-400 hover:text-rose-600 rounded-md transition-colors inline-flex items-center justify-center cursor-pointer shadow-2xs"
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

export default DomainMatrixTable;
