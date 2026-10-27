"use client";

import React from "react";

export default function InboxWitnessCanvas({ className = "" }: { className?: string }) {
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
          <radialGradient id="witnessBeaconGlow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(164 36) scale(24)">
            <stop offset="0%" stopColor="#34D399" stopOpacity="0.45" />
            <stop offset="50%" stopColor="#10B981" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient glow */}
        <circle cx="164" cy="36" r="22" fill="url(#witnessBeaconGlow)" />

        {/* Concentric telemetry witness rings */}
        <circle cx="164" cy="36" r="28" stroke="#10B981" strokeOpacity="0.12" strokeWidth="1" strokeDasharray="3 3" />
        <circle cx="164" cy="36" r="18" stroke="#10B981" strokeOpacity="0.22" strokeWidth="1.2" />
        <circle cx="164" cy="36" r="9" stroke="#10B981" strokeOpacity="0.38" strokeWidth="1.5" />

        {/* Active beacon core node */}
        <circle cx="164" cy="36" r="3.5" fill="#10B981" />
      </svg>
    </div>
  );
}
