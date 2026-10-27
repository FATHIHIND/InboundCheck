"use client";

import React from "react";

export default function ScoreGauge3DCanvas({
  score = 94,
  className = "",
}: {
  score?: number | null;
  className?: string;
}) {
  const hasValidScore = score !== null && score !== undefined && !isNaN(score);
  const clampedScore = hasValidScore ? Math.min(100, Math.max(0, score)) : 0;

  // Gauge geometry:
  // Circle radius r = 44, cx = 60, cy = 60
  // Circumference = 2 * PI * 44 = 276.46
  // Gauge arc covers 270 degrees (3/4 of circle) = 207.35
  const circumference = 276.46;
  const maxArc = 207.35;
  const arcLength = hasValidScore ? (clampedScore / 100) * maxArc : 0;

  return (
    <div
      className={`relative flex items-center justify-center ${className}`}
      role="img"
      aria-label={`Domain deliverability health score: ${hasValidScore ? `${clampedScore} out of 100` : "not evaluated"}`}
    >
      <svg
        viewBox="0 0 120 120"
        className="w-full h-full max-h-28 block pointer-events-none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="scoreGaugeGradient" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#059669" />
            <stop offset="50%" stopColor="#10B981" />
            <stop offset="100%" stopColor="#34D399" />
          </linearGradient>
          <radialGradient id="scoreGaugeGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#10B981" stopOpacity="0.18" />
            <stop offset="60%" stopColor="#10B981" stopOpacity="0.04" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient radial glow core */}
        <circle cx="60" cy="60" r="48" fill="url(#scoreGaugeGlow)" />

        {/* Base Track Arc (270 deg, starts at 135 deg / bottom-left) */}
        <circle
          cx="60"
          cy="60"
          r="44"
          fill="none"
          stroke="#E2E8F0"
          strokeWidth="7"
          strokeDasharray={`${maxArc} ${circumference}`}
          strokeLinecap="round"
          transform="rotate(135 60 60)"
        />

        {/* Active Illuminated Emerald Arc based on Score */}
        {hasValidScore && (
          <circle
            cx="60"
            cy="60"
            r="44"
            fill="none"
            stroke="url(#scoreGaugeGradient)"
            strokeWidth="7.5"
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeLinecap="round"
            transform="rotate(135 60 60)"
            className="transition-[stroke-dasharray] duration-700 ease-out motion-reduce:transition-none"
          />
        )}
      </svg>

      {/* Numerical score readout centered inside the gauge */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
        <span className="text-3xl font-extrabold text-slate-950 font-mono tracking-tight leading-none">
          {hasValidScore ? clampedScore : "--"}
        </span>
        <span className="text-[10px] font-mono font-bold tracking-widest text-emerald-700 uppercase mt-1">
          / 100 HEALTH
        </span>
      </div>
    </div>
  );
}
