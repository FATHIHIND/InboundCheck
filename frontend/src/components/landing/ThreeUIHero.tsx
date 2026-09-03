"use client";

import React from "react";
import { EmeraldHorizonBackground as AtTheHorizon } from "@designcodeio/threeui/components/EmeraldHorizonBackground";
import "@designcodeio/threeui/style.css";

export default function ThreeUIHero({
  className = "",
}: {
  className?: string;
}) {
  return (
    <div
      className={`pointer-events-none absolute inset-0 overflow-hidden select-none z-0 ${className}`}
      aria-hidden="true"
    >
      {/* 3D WebGL Scene Component from @designcodeio/threeui */}
      <div className="absolute inset-0 w-full h-full opacity-60">
        <AtTheHorizon
          speed={0.8}
          waveScale={1.2}
          variation={1.0}
          glow={1.4}
          vignette={0.8}
          className="w-full h-full"
        />
      </div>

      {/* Radial opacity masking & central contrast vignette for high readability */}
      <div className="absolute inset-0 bg-radial from-transparent via-[#08080A]/40 to-[#08080A]/90 pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(8,8,10,0.3)_0%,rgba(8,8,10,0.85)_100%)] pointer-events-none" />
    </div>
  );
}
