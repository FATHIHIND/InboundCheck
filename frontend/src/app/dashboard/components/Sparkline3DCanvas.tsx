"use client";

import React from "react";

export default function Sparkline3DCanvas({ className = "" }: { className?: string }) {
  // Trajectory points: [12, 9, 7, 5, 4, 3, 2] mapped to viewBox 0 0 160 50
  // Downward risk trajectory safely under 5% threshold
  const pathD = "M 12 15 L 35 22 L 57 26 L 80 31 L 103 33 L 125 35 L 148 38";
  const areaD = "M 12 15 L 35 22 L 57 26 L 80 31 L 103 33 L 125 35 L 148 38 L 148 46 L 12 46 Z";

  return (
    <div
      className={`pointer-events-none absolute inset-0 w-full h-full overflow-hidden flex items-center justify-end ${className}`}
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 160 50"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
        preserveAspectRatio="xMaxYMid meet"
      >
        <title>48-72h Risk Trajectory Sparkline showing low risk trajectory below 5%</title>
        <defs>
          <linearGradient id="sparklineStrokeGrad" x1="12" y1="25" x2="148" y2="25" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#10B981" />
            <stop offset="100%" stopColor="#34D399" />
          </linearGradient>
          <linearGradient id="sparklineAreaGrad" x1="80" y1="15" x2="80" y2="46" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#10B981" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Shaded trajectory area */}
        <path d={areaD} fill="url(#sparklineAreaGrad)" />

        {/* Crisp trajectory stroke */}
        <path
          d={pathD}
          stroke="url(#sparklineStrokeGrad)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Target endpoint node representing terminal 48-72h forecast risk */}
        <circle cx="148" cy="38" r="5" fill="#10B981" fillOpacity="0.25" />
        <circle cx="148" cy="38" r="2.5" fill="#34D399" />
      </svg>
    </div>
  );
}
