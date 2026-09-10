"use client";

import { useState } from "react";
import { Activity, ShieldCheck, ShieldAlert, Radio, Clock, TrendingUp } from "lucide-react";

export interface ReputationPoint {
  id?: string;
  checked_at: string;
  unified_score: number;
  dns_health_score: number;
  spam_risk_pct: number;
  risk_level: "low" | "medium" | "high";
  blacklist_count: number;
  rbl_status: string;
}



export default function ReputationTrendChart({ data = [] }: { data?: ReputationPoint[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (!data || data.length === 0) {
    return (
      <div className="obsidian-card p-6 rounded-2xl border border-white/[0.08] flex flex-col justify-between space-y-4 shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
          <div>
            <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              Reputation Trajectory & 48h Radar Forecast
            </h3>
            <p className="text-xs text-zinc-400 mt-0.5 font-normal">
              Continuous multi-resolver reputation checks and predictive blacklist risk scoring
            </p>
          </div>
          <span className="text-[11px] font-mono text-zinc-400 px-2.5 py-1 rounded-full bg-zinc-800/80 border border-zinc-700/50">
            Awaiting Data
          </span>
        </div>
        <div className="py-14 text-center space-y-2">
          <Activity className="w-8 h-8 text-zinc-600 mx-auto animate-pulse" />
          <div className="text-xs font-semibold text-zinc-300">No reputation history recorded yet</div>
          <div className="text-[11px] text-zinc-500 max-w-sm mx-auto">
            Periodic background audit checks will compile your domain&apos;s deliverability trajectory over time.
          </div>
        </div>
      </div>
    );
  }

  const currentPoint = data[data.length - 1];
  const firstPoint = data[0];
  const scoreDelta = currentPoint.unified_score - firstPoint.unified_score;

  // SVG Coordinates Math
  const width = 640;
  const height = 210;
  const paddingX = 40;
  const paddingY = 25;
  const chartWidth = width - paddingX * 2;
  const chartHeight = height - paddingY * 2;

  const minScore = 50;
  const maxScore = 100;

  const points = data.map((d, index) => {
    const x = paddingX + (index / (data.length - 1)) * chartWidth;
    const y = height - paddingY - ((d.unified_score - minScore) / (maxScore - minScore)) * chartHeight;
    return { x, y, data: d, index };
  });

  const pathD = points.reduce((acc, point, index, arr) => {
    if (index === 0) return `M ${point.x} ${point.y}`;
    const prev = arr[index - 1];
    const cp1x = prev.x + (point.x - prev.x) / 2;
    const cp1y = prev.y;
    const cp2x = prev.x + (point.x - prev.x) / 2;
    const cp2y = point.y;
    return `${acc} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${point.x} ${point.y}`;
  }, "");

  const areaD = `${pathD} L ${points[points.length - 1].x} ${height - paddingY} L ${points[0].x} ${height - paddingY} Z`;

  const hoveredPoint = hoveredIndex !== null ? points[hoveredIndex] : null;

  return (
    <div className="obsidian-card p-6 rounded-2xl border border-white/[0.08] relative space-y-5 shadow-2xl">
      {/* Header with V2 Unified Scoring Context */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-emerald-400" />
            <h3 className="text-sm font-bold text-white tracking-tight">
              Unified Predictive Score & RBL Timeline
            </h3>
          </div>
          <p className="text-xs text-zinc-400 mt-0.5 font-normal">
            Continuous trajectory reading from <code className="text-emerald-400 font-mono text-[11px]">reputation_checks</code> (DNS × Blacklist Posture)
          </p>
        </div>

        {/* Real V2 Metrics Badges */}
        <div className="grid grid-cols-3 gap-2.5">
          <div className="bg-[#08080A] px-3 py-1.5 rounded-xl border border-white/[0.06]">
            <span className="text-[10px] uppercase font-mono text-zinc-500 block">Unified Score</span>
            <span className="text-xs font-bold text-emerald-400 font-mono block mt-0.5">
              {currentPoint.unified_score}% ({scoreDelta >= 0 ? `+${scoreDelta}%` : `${scoreDelta}%`})
            </span>
          </div>

          <div className="bg-[#14141A] px-3 py-1.5 rounded-xl border border-white/[0.1] shadow-inner">
            <span className="text-[10px] uppercase font-mono text-zinc-400 block">48–72h Risk</span>
            <span className="text-xs font-bold text-emerald-400 font-mono block mt-0.5">
              {currentPoint.spam_risk_pct}% ({currentPoint.risk_level.toUpperCase()})
            </span>
          </div>

          <div className="bg-[#08080A] px-3 py-1.5 rounded-xl border border-white/[0.06]">
            <span className="text-[10px] uppercase font-mono text-zinc-500 block">RBL Incidents</span>
            <span className={`text-xs font-bold font-mono block mt-0.5 ${currentPoint.blacklist_count === 0 ? "text-white" : "text-red-400"}`}>
              {currentPoint.blacklist_count} Listed
            </span>
          </div>
        </div>
      </div>

      {/* Dynamic Glowing Line SVG Graphic with Hover Crosshair */}
      <div className="relative w-full overflow-hidden pt-2">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto overflow-visible">
          <defs>
            <linearGradient id="reputationWaveGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10B981" stopOpacity="0.38" />
              <stop offset="65%" stopColor="#10B981" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#08080A" stopOpacity="0.0" />
            </linearGradient>

            <filter id="emeraldLineGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Grid lines */}
          {[100, 80, 60].map((score) => {
            const y = height - paddingY - ((score - minScore) / (maxScore - minScore)) * chartHeight;
            return (
              <g key={score}>
                <line
                  x1={paddingX}
                  y1={y}
                  x2={width - paddingX}
                  y2={y}
                  stroke="rgba(255, 255, 255, 0.05)"
                  strokeDasharray="3 3"
                />
                <text
                  x={paddingX - 8}
                  y={y + 3}
                  fill="#71717A"
                  fontSize="9"
                  textAnchor="end"
                  fontFamily="monospace"
                >
                  {score}%
                </text>
              </g>
            );
          })}

          {/* Glowing Area Fill */}
          <path d={areaD} fill="url(#reputationWaveGradient)" />

          {/* Glowing Curve Stroke */}
          <path
            d={pathD}
            fill="none"
            stroke="#10B981"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
            filter="url(#emeraldLineGlow)"
          />

          {/* Interactive Crosshair Lines on Hover */}
          {hoveredPoint && (
            <g className="transition-opacity duration-150">
              {/* Vertical Crosshair Line */}
              <line
                x1={hoveredPoint.x}
                y1={paddingY}
                x2={hoveredPoint.x}
                y2={height - paddingY}
                stroke="rgba(16, 185, 129, 0.4)"
                strokeDasharray="2 2"
                strokeWidth="1.5"
              />
              {/* Horizontal Crosshair Line */}
              <line
                x1={paddingX}
                y1={hoveredPoint.y}
                x2={width - paddingX}
                y2={hoveredPoint.y}
                stroke="rgba(16, 185, 129, 0.4)"
                strokeDasharray="2 2"
                strokeWidth="1.5"
              />
            </g>
          )}

          {/* Pulsating Data Point Nodes */}
          {points.map((p) => {
            const nodeColor =
              p.data.risk_level === "high" || p.data.blacklist_count > 0
                ? "#EF4444"
                : p.data.risk_level === "medium"
                ? "#F59E0B"
                : "#10B981";

            const isSelected = hoveredIndex === p.index;

            return (
              <g
                key={p.index}
                className="cursor-pointer group"
                onMouseEnter={() => setHoveredIndex(p.index)}
                onMouseLeave={() => setHoveredIndex(null)}
              >
                {/* Outer Glow Pulse Aura */}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={isSelected ? "10" : "7"}
                  fill={nodeColor}
                  fillOpacity={isSelected ? "0.4" : "0.2"}
                  className="transition-all duration-200"
                />
                <circle
                  cx={p.x}
                  cy={p.y}
                  r="5"
                  fill={nodeColor}
                  stroke="#08080A"
                  strokeWidth="2.5"
                  className="transition-transform group-hover:scale-150"
                />
                <text
                  x={p.x}
                  y={height - 4}
                  fill={isSelected ? "#10B981" : "#71717A"}
                  fontSize="9"
                  fontWeight={isSelected ? "bold" : "normal"}
                  textAnchor="middle"
                  fontFamily="monospace"
                >
                  {p.data.checked_at}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Hover Crosshair Tooltip Overlay */}
        {hoveredPoint && (
          <div className="absolute top-2 right-4 bg-[#14141A]/95 backdrop-blur-md border border-emerald-500/30 p-3 rounded-xl shadow-2xl text-xs space-y-1 z-20 animate-fadeIn font-mono">
            <div className="text-zinc-400 text-[10px] font-bold border-b border-white/[0.06] pb-1">
              {hoveredPoint.data.checked_at} Audit Entry
            </div>
            <div className="text-white font-bold flex items-center justify-between gap-4 pt-0.5">
              <span>Unified Score:</span>
              <span className="text-emerald-400">{hoveredPoint.data.unified_score}%</span>
            </div>
            <div className="text-zinc-300 flex items-center justify-between gap-4 text-[11px]">
              <span>DNS Health:</span>
              <span>{hoveredPoint.data.dns_health_score}%</span>
            </div>
            <div className="text-zinc-300 flex items-center justify-between gap-4 text-[11px]">
              <span>48h Spam Risk:</span>
              <span className="text-emerald-400">{hoveredPoint.data.spam_risk_pct}% ({hoveredPoint.data.risk_level})</span>
            </div>
            <div className="text-zinc-300 flex items-center justify-between gap-4 text-[11px]">
              <span>Blacklist:</span>
              <span className={hoveredPoint.data.blacklist_count > 0 ? "text-red-400" : "text-emerald-400"}>
                {hoveredPoint.data.rbl_status}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
