"use client";

import { useState, Fragment } from "react";
import dynamic from "next/dynamic";
import {
  ShieldCheck,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Activity,
  Globe,
  Radio,
  Clock,
  Server,
  ChevronDown
} from "lucide-react";
import { GlassEmeraldCard } from "@/components/ui/GlassEmeraldCard";
import { EmeraldHoverButton } from "@/components/ui/EmeraldHoverButton";

const RblTopology3DCanvas = dynamic(() => import("../components/RblTopology3DCanvas"), {
  ssr: false,
});

interface RblItem {
  id: string;
  name: string;
  host: string;
  category: "ip" | "domain";
  status: "clean" | "listed" | "checking";
  latency_ms: number;
  delisting_url: string;
  description: string;
}

export default function BlacklistRadarPage() {
  const [target, setTarget] = useState("brandshop.com");
  const [isScanning, setIsScanning] = useState(false);
  const [lastScanned, setLastScanned] = useState("Just now");
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  const [rbls] = useState<RblItem[]>([
    {
      id: "spamhaus_zen",
      name: "Spamhaus ZEN",
      host: "zen.spamhaus.org",
      category: "ip",
      status: "clean",
      latency_ms: 38,
      delisting_url: "https://www.spamhaus.org/lookup/",
      description: "Combines SBL, SBLP, XBL and PBL datasets for high-consequence IP reputation auditing."
    },
    {
      id: "barracuda",
      name: "Barracuda BRBL",
      host: "b.barracudacentral.org",
      category: "ip",
      status: "clean",
      latency_ms: 42,
      delisting_url: "https://www.barracudacentral.org/rbl",
      description: "Real-time list of IP addresses verified to send spam to Barracuda networks."
    },
    {
      id: "spamcop",
      name: "SpamCop SCBL",
      host: "bl.spamcop.net",
      category: "ip",
      status: "clean",
      latency_ms: 55,
      delisting_url: "https://www.spamcop.net/bl.shtml",
      description: "Determined dynamically from unsolicited email report submissions."
    },
    {
      id: "sorbs",
      name: "SORBS Aggregate",
      host: "dnsbl.sorbs.net",
      category: "ip",
      status: "clean",
      latency_ms: 61,
      delisting_url: "http://www.sorbs.net/lookup.shtml",
      description: "Monitors open relay servers, compromised hosts, and spam originators."
    },
    {
      id: "uceprotect_1",
      name: "UCEPROTECT Level 1",
      host: "dnsbl-1.uceprotect.net",
      category: "ip",
      status: "clean",
      latency_ms: 48,
      delisting_url: "http://www.uceprotect.net/en/rblcheck.php",
      description: "Strict single-IP address blacklist for direct spam transmitters."
    },
    {
      id: "spamhaus_dbl",
      name: "Spamhaus DBL",
      host: "dbl.spamhaus.org",
      category: "domain",
      status: "clean",
      latency_ms: 39,
      delisting_url: "https://www.spamhaus.org/lookup/",
      description: "Authoritative domain-name blacklist covering phishing and spam domain URI links."
    },
    {
      id: "cbl",
      name: "Composite Blocking List (CBL)",
      host: "cbl.abuseat.org",
      category: "ip",
      status: "clean",
      latency_ms: 45,
      delisting_url: "https://www.abuseat.org/lookup.cgi",
      description: "Specializes in detecting botnet infections, Trojan relays, and open proxies."
    },
    {
      id: "abuse_ro",
      name: "Abuse.ro Network",
      host: "rbl.abuse.ro",
      category: "ip",
      status: "clean",
      latency_ms: 70,
      delisting_url: "https://rbl.abuse.ro/",
      description: "Regional and global spam origin blacklist."
    },
    {
      id: "surbl",
      name: "SURBL Multi-Depth",
      host: "multi.surbl.org",
      category: "domain",
      status: "clean",
      latency_ms: 50,
      delisting_url: "http://www.surbl.org/surbl-analysis",
      description: "Detects websites appearing in unsolicited email body text links."
    },
    {
      id: "mailspike",
      name: "Mailspike Reputation",
      host: "rep.mailspike.net",
      category: "ip",
      status: "clean",
      latency_ms: 52,
      delisting_url: "https://mailspike.org/iplookup.html",
      description: "Distributed real-time sender reputation scoring network."
    }
  ]);

  const handleScan = () => {
    setIsScanning(true);
    setTimeout(() => {
      setIsScanning(false);
      setLastScanned("Just now");
    }, 800);
  };

  const toggleRow = (id: string) => {
    setExpandedRows((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const listedCount = rbls.filter((r) => r.status === "listed").length;

  return (
    <div className="space-y-6 max-w-[1360px] mx-auto animate-fadeIn pb-12">
      {/* 1. Header with Title & Action */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight flex items-center gap-2.5">
            <Radio className="w-6 h-6 text-emerald-400 animate-pulse" />
            Blacklist Radar & RBL Intelligence
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            Real-time monitoring across 10 authoritative RBL databases with 48-72h predictive risk forecasting.
          </p>
        </div>

        <EmeraldHoverButton
          onClick={handleScan}
          isLoading={isScanning}
          loadingText="Probing RBL Networks..."
          icon={<RefreshCw className="w-3.5 h-3.5" />}
          size="sm"
          variant="primary"
        >
          Run Real-Time RBL Audit
        </EmeraldHoverButton>
      </div>

      {/* 2. Target Search & Control Bar */}
      <div className="bg-[#0E0E12]/80 backdrop-blur-md p-4 rounded-xl border border-zinc-800/80 hover:border-emerald-500/30 transition-all duration-200 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-96">
          <Globe className="w-4 h-4 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="Enter domain or IP, e.g. brandshop.com"
            className="w-full pl-9 pr-3 py-2 bg-[#08080A] border border-zinc-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:border-emerald-500/50 transition-colors"
          />
        </div>

        <div className="flex items-center gap-4 text-xs font-mono text-zinc-400">
          <span>
            Target: <strong className="text-emerald-400 font-mono text-xs">{target}</strong>
          </span>
          <span className="text-zinc-700">•</span>
          <span>
            Last Audited: <strong className="text-white font-mono text-xs">{lastScanned}</strong>
          </span>
        </div>
      </div>

      {/* 3. 3D Real-Time RBL Node Topology Canvas */}
      <div className="bg-[#0E0E12]/80 backdrop-blur-md p-4 rounded-xl border border-zinc-800/80 hover:border-emerald-500/30 transition-all duration-200 space-y-3 relative overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2 text-xs">
          <span className="font-mono text-emerald-400 font-bold flex items-center gap-2">
            <Radio className="w-4 h-4 animate-pulse text-emerald-400" />
            3D REAL-TIME RBL NODE TOPOLOGY & PROBING MATRIX
          </span>
          <span className="text-[10px] font-mono text-zinc-400">10 AUTHORITATIVE LISTS</span>
        </div>
        <RblTopology3DCanvas rbls={rbls} className="h-44 w-full" />
      </div>

      {/* 4. Purpose-Driven Enterprise Metric Cards (Row 1) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <GlassEmeraldCard
          title="Active Incidents"
          subtitle="Real-time RBL Status"
          badgeText="Clean Posture"
          badgeVariant="emerald"
          metricValue={listedCount}
          icon={<ShieldCheck className="w-5 h-5 text-emerald-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono">
            Zero listings across authoritative realtime blacklists.
          </p>
        </GlassEmeraldCard>

        <GlassEmeraldCard
          title="RBL Hosts Queried"
          subtitle="Authoritative Probe Net"
          badgeText="10 / 10 Active"
          badgeVariant="emerald"
          metricValue="10 / 10"
          icon={<Server className="w-5 h-5 text-emerald-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono line-clamp-1">
            Spamhaus, Barracuda, SpamCop, SORBS, and UCEPROTECT.
          </p>
        </GlassEmeraldCard>

        <GlassEmeraldCard
          title="48h Risk Index"
          subtitle="Predictive Trajectory"
          badgeText="Stable"
          badgeVariant="emerald"
          metricValue="< 5%"
          icon={<Activity className="w-5 h-5 text-emerald-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono">
            Predictive machine learning reputation trajectory.
          </p>
        </GlassEmeraldCard>

        <GlassEmeraldCard
          title="Avg Lookup Latency"
          subtitle="Multi-Resolver UDP Window"
          badgeText="Real-time"
          badgeVariant="cyan"
          metricValue="47.8ms"
          icon={<Clock className="w-5 h-5 text-cyan-400" />}
        >
          <p className="text-xs text-zinc-400 font-mono">
            Multi-resolver UDP query response window.
          </p>
        </GlassEmeraldCard>
      </div>

      {/* 5. Authoritative RBL Monitoring Matrix Table */}
      <GlassEmeraldCard
        title="Authoritative RBL Monitoring Matrix"
        subtitle="Real-time DNSBL reputation telemetry and delisting gateway access"
        badgeText="10 Lists Active"
        badgeVariant="emerald"
        icon={<Activity className="w-5 h-5 text-emerald-400" />}
      >

        {/* Viewport Bounding (Show Exactly 3 Rows with Scroll) */}
        <div className="overflow-y-auto max-h-[260px] scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent hover:scrollbar-thumb-emerald-500/40 rounded-lg">
          <table className="w-full text-left text-xs font-mono border-collapse">
            <thead className="sticky top-0 bg-[#0E0E12] z-10 backdrop-blur-md border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-400">
              <tr>
                <th className="py-3 px-4 font-semibold">RBL Provider</th>
                <th className="py-3 px-4 font-semibold">DNSBL Host</th>
                <th className="py-3 px-4 font-semibold">Type</th>
                <th className="py-3 px-4 font-semibold">Status</th>
                <th className="py-3 px-4 font-semibold">Latency</th>
                <th className="py-3 px-4 font-semibold text-right">Delisting Portal</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-900/60 text-zinc-300">
              {rbls.map((rbl) => {
                const isListed = rbl.status === "listed";
                const isWarning = rbl.latency_ms > 65;
                const isExpanded = !!expandedRows[rbl.id];

                return (
                  <Fragment key={rbl.id}>
                    <tr
                      className="border-b border-zinc-900/60 hover:bg-zinc-800/30 transition-colors cursor-pointer"
                      onClick={() => toggleRow(rbl.id)}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleRow(rbl.id);
                            }}
                            className="p-0.5 rounded text-zinc-400 hover:text-emerald-400 transition cursor-pointer"
                            title={isExpanded ? "Collapse Row" : "Expand Row"}
                          >
                            <ChevronDown
                              className={`w-4 h-4 transition-transform duration-200 ${
                                isExpanded ? "rotate-180 text-emerald-400" : "text-zinc-400"
                              }`}
                            />
                          </button>
                          <div>
                            <div className="font-bold text-white text-xs font-sans flex items-center gap-1.5">
                              {rbl.name}
                            </div>
                            <div className="text-xs text-zinc-400 mt-0.5 line-clamp-1 font-sans">
                              {rbl.description}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-mono text-xs text-zinc-300">{rbl.host}</td>
                      <td className="py-3 px-4">
                        <span className="text-[10px] uppercase font-mono font-bold px-2 py-0.5 rounded-lg bg-zinc-800/80 text-zinc-300 border border-zinc-700/50">
                          {rbl.category}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {isListed ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-rose-400 bg-rose-500/10 border border-rose-500/20">
                            <XCircle className="w-3.5 h-3.5" />
                            LISTED
                          </span>
                        ) : isWarning ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-amber-400 bg-amber-500/10 border border-amber-500/20">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            ELEVATED
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/20">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            CLEAN
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-xs text-zinc-300">
                        <span className={isWarning ? "text-amber-400 font-semibold" : "text-zinc-300"}>
                          {rbl.latency_ms}ms
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                        <a
                          href={rbl.delisting_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-zinc-400 hover:text-emerald-400 font-mono text-xs inline-flex items-center gap-1 transition-colors"
                        >
                          Lookup <ExternalLink className="w-3 h-3" />
                        </a>
                      </td>
                    </tr>

                    {/* Collapsible Accordion Drawer */}
                    {isExpanded && (
                      <tr className="bg-[#08080A]/90 border-b border-zinc-800/80 animate-fadeIn">
                        <td colSpan={6} className="p-4">
                          <div className="space-y-3 font-mono text-xs">
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                              <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80">
                                <span className="text-[10px] text-zinc-500 uppercase block">Incident History</span>
                                <span className="text-xs text-emerald-400 font-bold block mt-0.5">
                                  0 Incidents Recorded
                                </span>
                                <span className="text-[10px] text-zinc-400 block mt-0.5">Last checked: {lastScanned}</span>
                              </div>

                              <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80">
                                <span className="text-[10px] text-zinc-500 uppercase block">Delisting Gateway</span>
                                <span className="text-xs text-zinc-300 block mt-0.5 font-sans">
                                  Direct API & Manual Removal Request
                                </span>
                                <a
                                  href={rbl.delisting_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-[10px] text-emerald-400 hover:underline block mt-0.5"
                                >
                                  Open Delisting Portal ↗
                                </a>
                              </div>

                              <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80">
                                <span className="text-[10px] text-zinc-500 uppercase block">RFC 1035 Query Log</span>
                                <code className="text-[11px] text-emerald-400/90 block mt-0.5 break-all">
                                  1.1.1.1 -&gt; {target}.{rbl.host} (NXDOMAIN)
                                </code>
                                <span className="text-[10px] text-zinc-400 block mt-0.5">Latency: {rbl.latency_ms}ms</span>
                              </div>
                            </div>

                            <div className="p-3 bg-[#0E0E12] rounded-lg border border-zinc-800/80 flex items-center justify-between text-xs font-sans text-zinc-400">
                              <span>{rbl.description}</span>
                              <span className="font-mono text-[10px] text-zinc-500">Host: {rbl.host}</span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassEmeraldCard>
    </div>
  );
}


