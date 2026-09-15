"use client";

import React, { useState, useRef } from "react";
import { CheckCircle2, AlertTriangle, ShieldCheck, Flame, ArrowUpRight } from "lucide-react";

interface AuditTicketProps {
  type: "storefront" | "radar";
}

export function ShopifyAuditTicket({ type }: AuditTicketProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [glare, setGlare] = useState({ x: 50, y: 50, opacity: 0 });
  const [tilt, setTilt] = useState({ x: 0, y: 0 });

  const isRadar = type === "radar";

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    const rotateX = ((y - centerY) / centerY) * -6;
    const rotateY = ((x - centerX) / centerX) * 8;

    setTilt({ x: rotateX, y: rotateY });
    setGlare({
      x: (x / rect.width) * 100,
      y: (y / rect.height) * 100,
      opacity: 1,
    });
  };

  const handleMouseLeave = () => {
    setTilt({ x: 0, y: 0 });
    setGlare((prev) => ({ ...prev, opacity: 0 }));
  };

  return (
    <div className="ticket-container w-full max-w-[420px]">
      <div
        ref={cardRef}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        style={{
          transform: glare.opacity
            ? `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg) scale(1.02)`
            : undefined,
        }}
        className={`ticket-pass ${
          isRadar ? "ticket-pass-leak border-rose-900/40 hover:border-rose-500/40" : "border-emerald-500/30 hover:border-emerald-500/50"
        } rounded-3xl border relative overflow-hidden shadow-2xl transition-all duration-300 flex flex-col justify-between`}
      >
        {/* Holographic Sheen Reflection Overlay */}
        <div
          className="pointer-events-none absolute inset-0 transition-opacity duration-300 rounded-3xl z-30"
          style={{
            opacity: glare.opacity * 0.45,
            background: `radial-gradient(circle 360px at ${glare.x}% ${glare.y}%, rgba(255, 255, 255, 0.35), transparent 70%), linear-gradient(135deg, ${
              isRadar ? "rgba(244, 63, 94, 0.2)" : "rgba(16, 185, 129, 0.2)"
            } 0%, transparent 50%, rgba(255, 255, 255, 0.1) 100%)`,
            mixBlendMode: "overlay",
          }}
        />

        {/* Top Header & Content Body */}
        <div className="p-7 space-y-5 relative z-10">
          {/* Top Label & Badge */}
          <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono tracking-wider uppercase text-gray-400 font-semibold">
                {isRadar ? "INBOUNDCHECK RADAR AUDIT" : "STORE FRONT REPORT"}
              </span>
            </div>
            <span
              className={`text-[10px] font-mono font-bold px-2.5 py-1 rounded-full border flex items-center gap-1.5 ${
                isRadar
                  ? "bg-rose-950/60 text-rose-400 border-rose-800/60"
                  : "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
              }`}
            >
              {isRadar ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" />
                  DELIVERABILITY BLINDSPOT
                </>
              ) : (
                <>
                  <CheckCircle2 size={12} className="text-emerald-400" />
                  SHOPIFY STATUS: NORMAL
                </>
              )}
            </span>
          </div>

          {/* Title & Subtitle */}
          <div>
            <h3
              className={`text-2xl sm:text-3xl font-bold tracking-tight ${
                isRadar ? "text-rose-400" : "text-white"
              }`}
            >
              {isRadar ? "240 Receipts in Spam" : "1,000 Orders Placed"}
            </h3>
            <p className="text-xs text-gray-400 font-sans mt-1">
              {isRadar
                ? "Blocked by Gmail & Yahoo 2024 filters"
                : "Store receipts dispatched automatically"}
            </p>
          </div>

          {/* Key Metrics / Details Grid */}
          <div className="space-y-2.5 font-mono text-xs pt-1">
            {isRadar ? (
              <>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-gray-400">Spam Placement</span>
                  <span className="text-rose-400 font-bold">24% of Total Orders</span>
                </div>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-gray-400">Customer Disputes</span>
                  <span className="text-rose-300 font-semibold">42 &ldquo;Where&apos;s my order?&rdquo; tickets</span>
                </div>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-gray-400">Monthly GMV at Risk</span>
                  <span className="text-rose-400 font-bold">-$4,200.00</span>
                </div>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-rose-900/30 flex items-center justify-between">
                  <span className="text-gray-400">Root Cause</span>
                  <span className="text-amber-400 font-semibold">Missing SPF / Broken DKIM</span>
                </div>
              </>
            ) : (
              <>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                  <span className="text-gray-400">Tracking Emails</span>
                  <span className="text-white font-semibold">1,000 Dispatched</span>
                </div>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                  <span className="text-gray-400">Store Health</span>
                  <span className="text-emerald-400 font-semibold">100% (Assumed)</span>
                </div>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                  <span className="text-gray-400">Customer Support</span>
                  <span className="text-white font-semibold">Normal Volume</span>
                </div>
                <div className="p-3 bg-[#0A0E13]/90 rounded-xl border border-white/[0.06] flex items-center justify-between">
                  <span className="text-gray-400">Shopify Notification</span>
                  <span className="text-emerald-400 font-semibold flex items-center gap-1">
                    <CheckCircle2 size={13} /> Sent Successfully
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Notched Perforation Divider Line */}
        <div className="relative w-full py-2 z-20">
          {/* Left Circular Notch Cutout */}
          <div className="absolute -left-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-black border-r border-white/20 shadow-[inset_-2px_0_4px_rgba(0,0,0,0.8)]" />
          {/* Right Circular Notch Cutout */}
          <div className="absolute -right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-black border-l border-white/20 shadow-[inset_2px_0_4px_rgba(0,0,0,0.8)]" />
          {/* Dashed Separator Line */}
          <div className="border-t border-dashed border-white/20 mx-4" />
        </div>

        {/* Stub & Barcode Section */}
        <div className="p-7 pt-2 space-y-4 relative z-10">
          <div className="flex items-center justify-between text-xs font-mono">
            <div>
              <span className="text-[10px] text-gray-500 block">AUDIT PASS ID</span>
              <span className="text-white font-bold tracking-wider">
                {isRadar ? "ALERT-SPAM-DETECTED" : "SHOP-OK-2026"}
              </span>
            </div>
            <div className="text-right">
              {isRadar ? (
                <div className="flex items-baseline gap-1">
                  <span className="text-[10px] text-rose-500 font-mono">LOSS:</span>
                  <span className="text-2xl font-black text-rose-400 tracking-tight font-mono">
                    -24%
                  </span>
                </div>
              ) : (
                <div>
                  <span className="text-[10px] text-gray-500 block">STATUS</span>
                  <span className="text-emerald-400 font-semibold font-mono">
                    ASSUMED SAFE
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* SVG Barcode */}
          <div className="flex items-center justify-between pt-1 opacity-70">
            <svg
              className={`h-7 w-48 ${isRadar ? "text-rose-400/80" : "text-emerald-400/80"}`}
              viewBox="0 0 160 28"
              fill="currentColor"
            >
              <rect x="0" y="0" width="3" height="28" />
              <rect x="5" y="0" width="1" height="28" />
              <rect x="8" y="0" width="4" height="28" />
              <rect x="14" y="0" width="2" height="28" />
              <rect x="18" y="0" width="1" height="28" />
              <rect x="21" y="0" width="3" height="28" />
              <rect x="26" y="0" width="1" height="28" />
              <rect x="29" y="0" width="4" height="28" />
              <rect x="35" y="0" width="2" height="28" />
              <rect x="39" y="0" width="3" height="28" />
              <rect x="44" y="0" width="1" height="28" />
              <rect x="47" y="0" width="4" height="28" />
              <rect x="53" y="0" width="2" height="28" />
              <rect x="57" y="0" width="1" height="28" />
              <rect x="60" y="0" width="3" height="28" />
              <rect x="65" y="0" width="2" height="28" />
              <rect x="69" y="0" width="4" height="28" />
              <rect x="75" y="0" width="1" height="28" />
              <rect x="78" y="0" width="3" height="28" />
              <rect x="83" y="0" width="2" height="28" />
              <rect x="87" y="0" width="4" height="28" />
              <rect x="93" y="0" width="1" height="28" />
              <rect x="96" y="0" width="2" height="28" />
              <rect x="100" y="0" width="3" height="28" />
              <rect x="105" y="0" width="1" height="28" />
              <rect x="108" y="0" width="2" height="28" />
              <rect x="112" y="0" width="4" height="28" />
              <rect x="118" y="0" width="1" height="28" />
              <rect x="121" y="0" width="3" height="28" />
              <rect x="126" y="0" width="2" height="28" />
              <rect x="130" y="0" width="1" height="28" />
              <rect x="133" y="0" width="3" height="28" />
              <rect x="138" y="0" width="2" height="28" />
              <rect x="142" y="0" width="4" height="28" />
              <rect x="148" y="0" width="1" height="28" />
              <rect x="151" y="0" width="3" height="28" />
              <rect x="156" y="0" width="2" height="28" />
            </svg>
            <span className="text-[10px] font-mono text-gray-500">
              {isRadar ? "VERIFIED RBL FAIL" : "VERIFIED STORE PASS"}
            </span>
          </div>

          <p className="text-[11px] text-gray-400 font-sans italic border-t border-white/[0.06] pt-3">
            {isRadar
              ? "InboundCheck eliminates this blindspot with 24/7 proactive DNS and deliverability monitoring."
              : "“Everything looks green in Shopify admin. Merchants assume deliveries are 100% successful.”"}
          </p>
        </div>
      </div>
    </div>
  );
}

export function ShopifyAuditPasses() {
  return (
    <div className="flex flex-col md:flex-row items-center justify-center gap-8 w-full">
      <ShopifyAuditTicket type="storefront" />
      <ShopifyAuditTicket type="radar" />
    </div>
  );
}

export default ShopifyAuditPasses;
