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

const DEFAULT_IMAP_LOGS: IMAPCheckLog[] = [
  { id: "chk_1", order_id: "#10542", folder: "inbox", received_at: "10 mins ago", latency_sec: 4.2, dns_subscore: 100, overall_score: 98 },
  { id: "chk_2", order_id: "#10541", folder: "inbox", received_at: "1 hour ago", latency_sec: 3.8, dns_subscore: 100, overall_score: 96 },
  { id: "chk_3", order_id: "#10540", folder: "spam", received_at: "3 hours ago", latency_sec: 8.5, dns_subscore: 70, overall_score: 55 },
  { id: "chk_4", order_id: "#10539", folder: "inbox", received_at: "6 hours ago", latency_sec: 4.1, dns_subscore: 95, overall_score: 94 },
  { id: "chk_5", order_id: "#10538", folder: "inbox", received_at: "12 hours ago", latency_sec: 3.9, dns_subscore: 100, overall_score: 95 },
];

export default function CheckHistoryChart({ logs = DEFAULT_IMAP_LOGS }: { logs?: IMAPCheckLog[] }) {
  const [selectedFolder, setSelectedFolder] = useState<"all" | "inbox" | "spam">("all");

  const filteredLogs = selectedFolder === "all"
    ? logs
    : logs.filter((l) => l.folder === selectedFolder);

  const inboxRate = Math.round(
    (logs.filter((l) => l.folder === "inbox").length / (logs.length || 1)) * 100
  );

  return (
    <div className="obsidian-card p-6 rounded-2xl border border-white/[0.08] flex flex-col justify-between space-y-5 shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
        <div>
          <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
            <Inbox className="w-4 h-4 text-emerald-400" />
            IMAP Ingestion & Simulation Feed
          </h3>
          <p className="text-xs text-zinc-400 mt-0.5 font-normal">
            Real order trigger → IMAP inbox folder verification
          </p>
        </div>

        <span className="text-xs font-mono font-bold px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-[0_0_12px_rgba(16,185,129,0.15)] flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
          {inboxRate}% Primary Inbox
        </span>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 text-[11px] font-mono">
        <button
          type="button"
          onClick={() => setSelectedFolder("all")}
          className={`px-3 py-1 rounded-lg transition-all duration-200 cursor-pointer ${
            selectedFolder === "all" ? "bg-[#1C1C24] text-white font-bold border border-white/[0.1]" : "text-zinc-400 hover:text-white"
          }`}
        >
          All Checks ({logs.length})
        </button>
        <button
          type="button"
          onClick={() => setSelectedFolder("inbox")}
          className={`px-3 py-1 rounded-lg transition-all duration-200 cursor-pointer flex items-center gap-1.5 ${
            selectedFolder === "inbox" ? "bg-emerald-500/20 text-emerald-300 font-bold border border-emerald-500/30" : "text-zinc-400 hover:text-white"
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          Inbox ({logs.filter((l) => l.folder === "inbox").length})
        </button>
        <button
          type="button"
          onClick={() => setSelectedFolder("spam")}
          className={`px-3 py-1 rounded-lg transition-all duration-200 cursor-pointer flex items-center gap-1.5 ${
            selectedFolder === "spam" ? "bg-red-500/20 text-red-300 font-bold border border-red-500/30" : "text-zinc-400 hover:text-white"
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
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
              className="flex items-center justify-between p-3 bg-[#08080A] rounded-xl border border-white/[0.04] hover:border-emerald-500/30 hover:bg-[#0E0E12] transition-all duration-200 group"
            >
              <div className="flex items-center gap-3">
                {log.folder === "inbox" ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 group-hover:scale-110 transition-transform" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-400 flex-shrink-0 group-hover:scale-110 transition-transform" />
                )}
                <div>
                  <span className="font-bold text-white block text-[11px]">{log.order_id}</span>
                  <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                    <Clock className="w-2.5 h-2.5" /> {log.received_at} • {log.latency_sec}s
                  </span>
                </div>
              </div>

              <div className="text-right flex items-center gap-2">
                <span
                  className={`text-[10px] font-bold px-2 py-0.5 rounded-full inline-flex items-center gap-1 transition-all duration-200 group-hover:scale-105 ${
                    log.folder === "inbox"
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                      : "bg-red-500/10 text-red-400 border border-red-500/20"
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${log.folder === "inbox" ? "bg-emerald-400 animate-pulse" : "bg-red-400 animate-pulse"}`} />
                  {log.folder.toUpperCase()}
                </span>
                <span className="text-[10px] text-zinc-400 block font-mono">
                  DNS: {log.dns_subscore}%
                </span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Summary Footer with Live Glowing Pulse */}
      <div className="pt-2 border-t border-white/[0.04] flex items-center justify-between text-[11px] font-mono text-zinc-400">
        <span>IMAP Witness Worker:</span>
        <span className="text-emerald-400 font-bold flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-full">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          Synced & Listening
        </span>
      </div>
    </div>
  );
}
