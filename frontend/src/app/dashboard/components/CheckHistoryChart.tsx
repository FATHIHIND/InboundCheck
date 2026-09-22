"use client";

import { useState } from "react";
import { MailCheck, AlertTriangle, XCircle, CheckCircle2, Clock, Inbox, ShieldCheck } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export interface IMAPCheckLog {
  id: string;
  order_id: string;
  folder: "inbox" | "spam" | "not_found";
  received_at: string;
  latency_sec: number;
  dns_subscore: number;
  overall_score: number;
}

export default function CheckHistoryChart({ logs = [] }: { logs?: IMAPCheckLog[] }) {
  const [selectedFolder, setSelectedFolder] = useState<"all" | "inbox" | "spam">("all");

  const filteredLogs = selectedFolder === "all"
    ? logs
    : logs.filter((l) => l.folder === selectedFolder);

  const inboxRate = logs.length > 0
    ? Math.round((logs.filter((l) => l.folder === "inbox").length / logs.length) * 100)
    : 0;

  if (logs.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 flex flex-col justify-between space-y-5 shadow-xs">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-2">
              <Inbox className="w-4 h-4 text-emerald-600" />
              Store Inbox Deliverability Feed
            </h3>
            <p className="text-xs text-slate-500 mt-0.5 font-normal">
              Live verification of customer receipts and order notification delivery
            </p>
          </div>
          <span className="text-xs font-mono text-slate-600 px-3 py-1 rounded-full bg-slate-50 border border-slate-200">
            Monitoring Store Deliverability
          </span>
        </div>
        <div className="py-12 text-center space-y-2 font-mono">
          <Inbox className="w-7 h-7 text-slate-400 mx-auto" />
          <div className="text-xs font-semibold text-slate-700">Monitoring store inbox deliverability...</div>
          <div className="text-[11px] text-slate-500 max-w-sm mx-auto">
            Live order receipts and customer notification verification events will appear here as orders process.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 flex flex-col justify-between space-y-5 shadow-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 pb-3">
        <div>
          <h3 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <Inbox className="w-4 h-4 text-emerald-600" />
            Store Inbox Deliverability Feed
          </h3>
          <p className="text-xs text-slate-500 mt-0.5 font-normal">
            Live verification of customer receipts and order notification delivery
          </p>
        </div>

        <span className="text-xs font-mono font-bold px-3 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-ping" />
          {inboxRate}% Primary Inbox
        </span>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 text-[11px] font-mono">
        <button
          type="button"
          onClick={() => setSelectedFolder("all")}
          className={`px-3 py-1 rounded-md transition-all duration-200 cursor-pointer ${
            selectedFolder === "all" ? "bg-slate-100 text-slate-900 font-bold border border-slate-300" : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
          }`}
        >
          All Checks ({logs.length})
        </button>
        <button
          type="button"
          onClick={() => setSelectedFolder("inbox")}
          className={`px-3 py-1 rounded-md transition-all duration-200 cursor-pointer flex items-center gap-1.5 ${
            selectedFolder === "inbox" ? "bg-emerald-50 text-emerald-800 font-bold border border-emerald-300" : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-600" />
          Inbox ({logs.filter((l) => l.folder === "inbox").length})
        </button>
        <button
          type="button"
          onClick={() => setSelectedFolder("spam")}
          className={`px-3 py-1 rounded-md transition-all duration-200 cursor-pointer flex items-center gap-1.5 ${
            selectedFolder === "spam" ? "bg-rose-50 text-rose-800 font-bold border border-rose-300" : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-rose-600" />
          Spam ({logs.filter((l) => l.folder === "spam").length})
        </button>
      </div>

      {/* Staggered Entry Motion Live Order List */}
      <div className="space-y-2.5 overflow-y-auto max-h-[190px] pr-1 font-mono text-xs">
        <AnimatePresence>
          {filteredLogs.map((log, idx) => (
            <motion.div
              key={log.id}
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.25, delay: idx * 0.05 }}
              className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-200 hover:border-slate-300 hover:bg-slate-100/70 transition-all duration-150 group"
            >
              <div className="flex items-center gap-3">
                {log.folder === "inbox" ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0 group-hover:scale-110 transition-transform" />
                ) : (
                  <XCircle className="w-4 h-4 text-rose-600 flex-shrink-0 group-hover:scale-110 transition-transform" />
                )}
                <div>
                  <span className="font-bold text-slate-900 block text-[11px]">{log.order_id}</span>
                  <span className="text-[10px] text-slate-500 flex items-center gap-1">
                    <Clock className="w-2.5 h-2.5" /> {log.received_at} • {log.latency_sec}s
                  </span>
                </div>
              </div>

              <div className="text-right flex items-center gap-2">
                <span
                  className={`text-[10px] font-bold px-2 py-0.5 rounded-full inline-flex items-center gap-1 transition-all duration-150 group-hover:scale-105 ${
                    log.folder === "inbox"
                      ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                      : "bg-rose-50 text-rose-800 border border-rose-200"
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${log.folder === "inbox" ? "bg-emerald-600 animate-pulse" : "bg-rose-600 animate-pulse"}`} />
                  {log.folder.toUpperCase()}
                </span>
                <span className="text-[10px] text-slate-500 block font-mono">
                  DNS: {log.dns_subscore}%
                </span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Summary Footer with Live Status */}
      <div className="pt-2 border-t border-slate-200 flex items-center justify-between text-[11px] font-mono text-slate-500">
        <span>Inbox Placement Surveillance:</span>
        <span className="text-emerald-800 font-bold flex items-center gap-1.5 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-full">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-600"></span>
          </span>
          Synced &amp; Listening
        </span>
      </div>
    </div>
  );
}
