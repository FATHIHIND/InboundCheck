"use client";

import React, { useState, useEffect } from "react";
import {
  X,
  ShoppingBag,
  ShieldCheck,
  Check,
  RefreshCw,
  Mail,
  Globe,
  Sliders,
  Sparkles,
  AlertCircle,
  Lock
} from "lucide-react";
import { apiFetch } from "@/lib/api";

export type EspProviderType = "shopify" | "klaviyo" | "postmark";

interface StoreSettingsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updatedData?: any) => void;
  initialStoreName?: string;
  initialShopDomain?: string;
  initialCustomDomain?: string;
  initialSenderEmail?: string;
  initialEsp?: EspProviderType;
}

const ESP_OPTIONS: Array<{
  id: EspProviderType;
  name: string;
  badge: string;
  description: string;
}> = [
  {
    id: "shopify",
    name: "Shopify Native Email",
    badge: "Built-in",
    description: "Automatic DKIM CNAME signing & SPF shops.shopify.com include",
  },
  {
    id: "klaviyo",
    name: "Klaviyo Dedicated",
    badge: "Marketing & DTC",
    description: "Multi-selector k1._domainkey DNS routing & abandoned checkout protection",
  },
  {
    id: "postmark",
    name: "Postmark Transactional",
    badge: "Ultra Low Latency",
    description: "Dedicated transactional delivery for order confirmations & tracking updates",
  },
];

export function StoreSettingsDrawer({
  isOpen,
  onClose,
  onSuccess,
  initialStoreName = "",
  initialShopDomain = "",
  initialCustomDomain = "",
  initialSenderEmail = "",
  initialEsp = "shopify",
}: StoreSettingsDrawerProps) {
  const [storeName, setStoreName] = useState(initialStoreName);
  const [shopDomain, setShopDomain] = useState(initialShopDomain);
  const [customDomain, setCustomDomain] = useState(initialCustomDomain);
  const [senderEmail, setSenderEmail] = useState(initialSenderEmail);
  const [espProvider, setEspProvider] = useState<EspProviderType>(initialEsp);

  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync state whenever drawer opens with new props
  useEffect(() => {
    if (isOpen) {
      setStoreName(initialStoreName || (initialShopDomain ? initialShopDomain.replace(".myshopify.com", "") : "My Brand Store"));
      setShopDomain(initialShopDomain || "");
      setCustomDomain(initialCustomDomain || (initialShopDomain ? initialShopDomain.replace(".myshopify.com", ".com") : ""));
      setSenderEmail(initialSenderEmail || (initialCustomDomain ? `orders@${initialCustomDomain}` : "orders@store.com"));
      setEspProvider(initialEsp || "shopify");
      setErrorMessage(null);
      setSaveSuccess(false);
    }
  }, [isOpen, initialStoreName, initialShopDomain, initialCustomDomain, initialSenderEmail, initialEsp]);

  // Keyboard dismiss (Escape)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setErrorMessage(null);

    try {
      // 1. Call the store-settings API
      const res = await apiFetch("/api/v1/shopify/store-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          store_name: storeName.trim(),
          shop_domain: shopDomain.trim(),
          custom_domain: customDomain.trim().toLowerCase(),
          sender_email: senderEmail.trim().toLowerCase(),
          esp_provider: espProvider,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Unable to save store configuration.");
      }

      const data = await res.json();
      setSaveSuccess(true);
      setTimeout(() => {
        setIsSaving(false);
        onSuccess(data);
        onClose();
      }, 600);
    } catch (err: any) {
      setIsSaving(false);
      setErrorMessage(err?.message || "Failed to update store settings.");
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="store-drawer-title"
      className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-md flex justify-end animate-fadeIn"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="w-full max-w-xl h-full bg-[#0f141c] border-l border-emerald-500/15 shadow-2xl flex flex-col justify-between overflow-y-auto animate-slideInRight"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer Header */}
        <div className="p-6 border-b border-emerald-500/15 bg-[#0a0d12]/60 backdrop-blur-sm sticky top-0 z-10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                <ShoppingBag className="w-5 h-5" />
              </div>
              <div>
                <h2 id="store-drawer-title" className="text-base font-bold text-white tracking-tight flex items-center gap-2">
                  Configure Store Sender Profile
                </h2>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Protect Store GMV &amp; prevent silent spam drops on transactional order receipts
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close drawer"
              className="p-2 rounded-xl text-zinc-400 hover:text-white bg-slate-900/80 hover:bg-slate-800 border border-slate-700/60 transition cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Drawer Body Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-6 flex-1 font-sans">
          {errorMessage && (
            <div className="p-3.5 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300 flex items-start gap-2.5 animate-fadeIn">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {saveSuccess && (
            <div className="p-3.5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-xs text-emerald-300 flex items-center gap-2 animate-fadeIn font-mono">
              <Check className="w-4 h-4 text-emerald-400" />
              <span>Store profile updated successfully. Synchronizing deliverability state...</span>
            </div>
          )}

          {/* Section 1: Merchant Store Identity */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono flex items-center gap-1.5">
                <ShoppingBag className="w-3.5 h-3.5" />
                Store Identity
              </span>
              <span className="text-[11px] text-zinc-400 font-mono">Customer-Facing</span>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-300">
                Store Name
              </label>
              <input
                type="text"
                value={storeName}
                onChange={(e) => setStoreName(e.target.value)}
                placeholder="e.g. Apex Apparel Store"
                required
                className="w-full px-3.5 py-2.5 bg-[#0a0d12] border border-slate-700/60 focus:border-emerald-500/60 rounded-xl text-white text-xs font-sans focus:outline-none transition"
              />
              <p className="text-[11px] text-zinc-400">
                The friendly brand display name shown on Order Confirmation Receipts and Tracking Notifications.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-300">
                Shopify myshopify Domain
              </label>
              <input
                type="text"
                value={shopDomain}
                onChange={(e) => setShopDomain(e.target.value)}
                placeholder="brand-store.myshopify.com"
                className="w-full px-3.5 py-2.5 bg-[#0a0d12] border border-slate-700/60 focus:border-emerald-500/60 rounded-xl text-zinc-300 text-xs font-mono focus:outline-none transition"
              />
              <p className="text-[11px] text-zinc-400">
                Internal Shopify administration handle.
              </p>
            </div>
          </div>

          {/* Section 2: Transactional Sending Domain & Email */}
          <div className="space-y-4 pt-2 border-t border-slate-800">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5" />
                Deliverability &amp; Sender Domain
              </span>
              <span className="text-[11px] text-zinc-400 font-mono">Google &amp; Yahoo 2024 Compliance</span>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-300">
                Official Sending Domain
              </label>
              <input
                type="text"
                value={customDomain}
                onChange={(e) => setCustomDomain(e.target.value)}
                placeholder="e.g. apexapparel.com"
                required
                className="w-full px-3.5 py-2.5 bg-[#0a0d12] border border-slate-700/60 focus:border-emerald-500/60 rounded-xl text-white text-xs font-mono focus:outline-none transition"
              />
              <p className="text-[11px] text-zinc-400">
                Primary branded apex or subdomain. Official Domain DNS Records (SPF, DKIM, DMARC) will align to this domain.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-300">
                Transactional Sender Email
              </label>
              <input
                type="email"
                value={senderEmail}
                onChange={(e) => setSenderEmail(e.target.value)}
                placeholder="e.g. orders@apexapparel.com"
                required
                className="w-full px-3.5 py-2.5 bg-[#0a0d12] border border-slate-700/60 focus:border-emerald-500/60 rounded-xl text-emerald-400 text-xs font-mono focus:outline-none transition"
              />
              <p className="text-[11px] text-zinc-400">
                Used to dispatch customer receipts and tracking numbers. Must match your authenticated sending domain to avoid customer disputes (chargebacks).
              </p>
            </div>
          </div>

          {/* Section 3: Integrated ESP Selector */}
          <div className="space-y-3 pt-2 border-t border-slate-800">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5" />
                Integrated ESP Service
              </span>
              <span className="text-[11px] text-zinc-400 font-mono">DKIM Selector Routing</span>
            </div>

            <div className="grid grid-cols-1 gap-2.5">
              {ESP_OPTIONS.map((esp) => {
                const isSelected = espProvider === esp.id;
                return (
                  <div
                    key={esp.id}
                    onClick={() => setEspProvider(esp.id)}
                    className={`p-3.5 rounded-xl border transition-all cursor-pointer flex items-start justify-between gap-3 ${
                      isSelected
                        ? "bg-emerald-500/10 border-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.15)]"
                        : "bg-[#0a0d12] border-slate-800 hover:border-slate-700"
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">{esp.name}</span>
                        <span
                          className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
                            isSelected
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold"
                              : "bg-slate-800/60 text-slate-400 border border-slate-700/40"
                          }`}
                        >
                          {esp.badge}
                        </span>
                      </div>
                      <p className="text-[11px] text-zinc-400 leading-relaxed">
                        {esp.description}
                      </p>
                    </div>

                    <div
                      className={`w-5 h-5 rounded-full border flex items-center justify-center shrink-0 mt-0.5 ${
                        isSelected
                          ? "bg-emerald-500 border-emerald-400 text-slate-950"
                          : "border-slate-700 bg-slate-900"
                      }`}
                    >
                      {isSelected && <Check className="w-3.5 h-3.5 stroke-[3]" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Commercial Protection Guarantee Notice */}
          <div className="p-3.5 bg-[#0a0d12] border border-emerald-500/20 rounded-xl space-y-1 text-xs">
            <div className="flex items-center gap-1.5 text-emerald-400 font-bold">
              <ShieldCheck className="w-4 h-4" />
              <span>Commercial Deliverability Guarantee</span>
            </div>
            <p className="text-[11px] text-zinc-400 leading-relaxed">
              Updating your sending profile ensures full Google &amp; Yahoo 2024 Sender Compliance, protecting Order Confirmation Receipts, Tracking Numbers, and Abandoned Cart Recovery emails from silent spam drops.
            </p>
          </div>
        </form>

        {/* Drawer Footer Actions */}
        <div className="p-6 border-t border-emerald-500/15 bg-[#0a0d12]/60 backdrop-blur-sm sticky bottom-0 z-10 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700/60 font-medium px-4 py-2 rounded-xl transition cursor-pointer text-xs"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSaving}
            className="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-5 py-2.5 rounded-xl transition-all shadow-lg shadow-emerald-500/20 active:scale-95 disabled:opacity-50 flex items-center gap-2 cursor-pointer text-xs"
          >
            {isSaving ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span>Saving Profile...</span>
              </>
            ) : (
              <>
                <ShieldCheck className="w-4 h-4" />
                <span>Save Store Configuration</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
