"use client";

import React from "react";

export default function RadarBeamCanvas({ className = "" }: { className?: string }) {
  return (
    <div
      className={`pointer-events-none absolute inset-0 w-full h-full overflow-hidden ${className}`}
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 200 80"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
        preserveAspectRatio="xMaxYMid meet"
      >
        <defs>
          <linearGradient id="radarSweepGrad" x1="170" y1="40" x2="198" y2="24" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#10B981" stopOpacity="0.28" />
            <stop offset="60%" stopColor="#10B981" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Concentric radar range rings */}
        <circle cx="170" cy="40" r="32" stroke="#10B981" strokeOpacity="0.12" strokeWidth="1" />
        <circle cx="170" cy="40" r="20" stroke="#10B981" strokeOpacity="0.18" strokeWidth="1" />
        <circle cx="170" cy="40" r="8" stroke="#10B981" strokeOpacity="0.26" strokeWidth="1" />

        {/* Radar crosshairs */}
        <line x1="138" y1="40" x2="202" y2="40" stroke="#10B981" strokeOpacity="0.15" strokeWidth="1" strokeDasharray="2 3" />
        <line x1="170" y1="8" x2="170" y2="72" stroke="#10B981" strokeOpacity="0.15" strokeWidth="1" strokeDasharray="2 3" />

        {/* Radar beam sector sweep */}
        <path
          d="M 170 40 L 198 24 A 32 32 0 0 0 170 8 Z"
          fill="url(#radarSweepGrad)"
        />

        {/* Center radar origin point */}
        <circle cx="170" cy="40" r="2.5" fill="#059669" />
      </svg>
    </div>
  );
}
