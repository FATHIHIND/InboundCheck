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
  AlertTriangle,
  Lock
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { formatApiErrorMessage } from "@/lib/apiResource";
import { AccessibleDialog } from "@/components/ui/AccessibleDialog";

export type EspProviderType = "shopify" | "klaviyo" | "postmark";

interface StoreSettingsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updatedData?: any) => void;
  storeId?: string;
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
  storeId,
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

  // Disconnect State
  const [isConfirmDisconnectOpen, setIsConfirmDisconnectOpen] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

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
      setIsConfirmDisconnectOpen(false);
      setIsDisconnecting(false);
      setDisconnectError(null);
    }
  }, [isOpen, initialStoreName, initialShopDomain, initialCustomDomain, initialSenderEmail, initialEsp, storeId]);

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
          store_id: storeId,
          store_name: storeName.trim(),
          shop_domain: shopDomain.trim(),
          custom_domain: customDomain.trim().toLowerCase(),
          sender_email: senderEmail.trim().toLowerCase(),
          esp_provider: espProvider,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(formatApiErrorMessage(body.detail || body.message || body) || "Unable to save store configuration.");
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

  // Immutable store disconnect targeting
  const targetSelector = storeId || initialShopDomain;
  const targetDisplayName = initialShopDomain || initialStoreName || "Shopify Store";
  const canDisconnect = Boolean(targetSelector);

  const handleDisconnect = async () => {
    if (!targetSelector) {
      setDisconnectError("No valid store identifier found to disconnect.");
      return;
    }

    setIsDisconnecting(true);
    setDisconnectError(null);

    try {
      const res = await apiFetch(`/api/v1/shopify/stores/${encodeURIComponent(targetSelector)}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(formatApiErrorMessage(body.detail || body.message || body) || "Failed to disconnect store.");
      }

      const data = await res.json();
      setIsConfirmDisconnectOpen(false);
      setIsDisconnecting(false);
      onSuccess({ disconnected: true, ...data });
      onClose();
    } catch (err: any) {
      setIsDisconnecting(false);
      setDisconnectError(err?.message || "Failed to disconnect store.");
    }
  };

  return (
    <>
      <AccessibleDialog
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="store-drawer-title"
      className="justify-end overflow-hidden animate-fadeIn"
      panelClassName="h-full w-full max-w-xl overflow-y-auto border-l border-slate-200 bg-white shadow-2xl animate-slideInRight flex flex-col justify-between"
    >
        {/* Drawer Header */}
        <div className="p-6 border-b border-slate-200 bg-white sticky top-0 z-10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-600">
                <ShoppingBag className="w-5 h-5" />
              </div>
              <div>
                <h2 id="store-drawer-title" className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
                  Configure Store Sender Profile
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Protect Store GMV &amp; prevent silent spam drops on transactional order receipts
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close drawer"
              className="p-2 rounded-md text-slate-400 hover:text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200 transition cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Drawer Body Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-6 flex-1 font-sans">
          {errorMessage && (
            <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-700 flex items-start gap-2.5 animate-fadeIn">
              <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {saveSuccess && (
            <div className="p-3.5 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-center gap-2 animate-fadeIn font-mono">
              <Check className="w-4 h-4 text-emerald-600" />
              <span>Store profile updated successfully. Synchronizing deliverability state...</span>
            </div>
          )}

          {/* Section 1: Merchant Store Identity */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-700 font-mono flex items-center gap-1.5">
                <ShoppingBag className="w-3.5 h-3.5" />
                Store Identity
              </span>
              <span className="text-[11px] text-slate-500 font-mono">Customer-Facing</span>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700">
                Store Name
              </label>
              <input
                type="text"
                value={storeName}
                onChange={(e) => setStoreName(e.target.value)}
                placeholder="e.g. Apex Apparel Store"
                required
                className="ic-input font-sans"
              />
              <p className="text-[11px] text-slate-500">
                The friendly brand display name shown on Order Confirmation Receipts and Tracking Notifications.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700">
                Shopify myshopify Domain
              </label>
              <input
                type="text"
                value={shopDomain}
                onChange={(e) => setShopDomain(e.target.value)}
                placeholder="brand-store.myshopify.com"
                className="ic-input font-mono"
              />
              <p className="text-[11px] text-slate-500">
                Internal Shopify administration handle.
              </p>
            </div>
          </div>

          {/* Section 2: Transactional Sending Domain & Email */}
          <div className="space-y-4 pt-2 border-t border-slate-200">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-700 font-mono flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5" />
                Deliverability &amp; Sender Domain
              </span>
              <span className="text-[11px] text-slate-500 font-mono">Google &amp; Yahoo 2024 Compliance</span>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700">
                Official Sending Domain
              </label>
              <input
                type="text"
                value={customDomain}
                onChange={(e) => setCustomDomain(e.target.value)}
                placeholder="e.g. apexapparel.com"
                required
                className="ic-input font-mono"
              />
              <p className="text-[11px] text-slate-500">
                Primary branded apex or subdomain. Official Domain DNS Records (SPF, DKIM, DMARC) will align to this domain.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700">
                Transactional Sender Email
              </label>
              <input
                type="email"
                value={senderEmail}
                onChange={(e) => setSenderEmail(e.target.value)}
                placeholder="e.g. orders@apexapparel.com"
                required
                className="ic-input font-mono"
              />
              <p className="text-[11px] text-slate-500">
                Used to dispatch customer receipts and tracking numbers. Must match your authenticated sending domain to avoid customer disputes (chargebacks).
              </p>
            </div>
          </div>

          {/* Section 3: Integrated ESP Selector */}
          <div className="space-y-3 pt-2 border-t border-slate-200">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-700 font-mono flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5" />
                Integrated ESP Service
              </span>
              <span className="text-[11px] text-slate-500 font-mono">DKIM Selector Routing</span>
            </div>

            <div className="grid grid-cols-1 gap-2.5">
              {ESP_OPTIONS.map((esp) => {
                const isSelected = espProvider === esp.id;
                return (
                  <button
                    type="button"
                    key={esp.id}
                    onClick={() => setEspProvider(esp.id)}
                    aria-pressed={isSelected}
                    className={`w-full p-3.5 rounded-lg border transition-all cursor-pointer flex items-start justify-between gap-3 shadow-2xs text-left focus-visible:ring-2 focus-visible:ring-emerald-600 ${
                      isSelected
                        ? "bg-emerald-50/70 border-emerald-300"
                        : "bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50/60"
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-slate-900">{esp.name}</span>
                        <span
                          className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
                            isSelected
                              ? "bg-emerald-100 text-emerald-800 border border-emerald-300 font-semibold"
                              : "bg-slate-100 text-slate-600 border border-slate-200"
                          }`}
                        >
                          {esp.badge}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-600 leading-relaxed">
                        {esp.description}
                      </p>
                    </div>

                    <div
                      className={`w-5 h-5 rounded-full border flex items-center justify-center shrink-0 mt-0.5 ${
                        isSelected
                          ? "bg-emerald-600 border-emerald-600 text-white"
                          : "border-slate-300 bg-white"
                      }`}
                    >
                      {isSelected && <Check className="w-3.5 h-3.5 stroke-[3]" />}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Commercial Protection Guarantee Notice */}
          <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-lg space-y-1 text-xs">
            <div className="flex items-center gap-1.5 text-emerald-800 font-bold">
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
              <span>Commercial Deliverability Guarantee</span>
            </div>
            <p className="text-[11px] text-slate-600 leading-relaxed">
              Updating your sending profile ensures full Google &amp; Yahoo 2024 Sender Compliance, protecting Order Confirmation Receipts, Tracking Numbers, and Abandoned Cart Recovery emails from silent spam drops.
            </p>
          </div>

          {/* Danger Zone: Disconnect Store */}
          <div className="p-4 bg-rose-50/70 border border-rose-200 rounded-lg space-y-3">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-xs font-bold text-rose-950 uppercase tracking-wider">
                  Danger Zone: Disconnect Store
                </h4>
                <p className="text-[11px] text-rose-800 mt-1 leading-relaxed">
                  Revokes Shopify sync credentials and stops order receipt tracking. DNS monitoring history and your SaaS subscription remain active and unaffected.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-rose-200/80">
              <div className="text-[11px] text-slate-700">
                Target: <span className="font-mono font-medium text-slate-900">{canDisconnect ? targetDisplayName : "No active store"}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setDisconnectError(null);
                  setIsConfirmDisconnectOpen(true);
                }}
                disabled={!canDisconnect || isDisconnecting || isSaving}
                className="px-3 py-1.5 text-xs font-semibold text-rose-700 hover:text-white bg-white hover:bg-rose-600 border border-rose-300 hover:border-rose-600 rounded-md transition shadow-2xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Disconnect Store
              </button>
            </div>
            {!canDisconnect && (
              <p className="text-[11px] text-slate-500 italic">
                No active store identifier is currently bound to this drawer to disconnect.
              </p>
            )}
          </div>
        </form>

        {/* Drawer Footer Actions */}
        <div className="p-6 border-t border-slate-200 bg-white sticky bottom-0 z-10 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving || isDisconnecting}
            className="bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 font-medium px-4 py-2 rounded-md transition cursor-pointer text-xs shadow-2xs"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSaving || isDisconnecting}
            className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-5 py-2.5 rounded-md transition-all shadow-xs active:scale-95 disabled:opacity-50 flex items-center gap-2 cursor-pointer text-xs"
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
      </AccessibleDialog>

      {/* Accessible Confirmation Dialog for Merchant-Initiated Store Disconnection */}
      <AccessibleDialog
        isOpen={isConfirmDisconnectOpen}
        onClose={() => !isDisconnecting && setIsConfirmDisconnectOpen(false)}
        labelledBy="confirm-disconnect-title"
        className="z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs animate-fadeIn"
        panelClassName="w-full max-w-md bg-white rounded-xl shadow-2xl border border-slate-200 p-6 space-y-4"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-rose-100 border border-rose-200 flex items-center justify-center text-rose-600 shrink-0 mt-0.5">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h3 id="confirm-disconnect-title" className="text-base font-bold text-slate-900">
              Disconnect {targetDisplayName}?
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Confirm merchant-initiated store disconnection
            </p>
          </div>
        </div>

        <div className="text-xs text-slate-600 space-y-2.5 bg-slate-50 border border-slate-200 rounded-lg p-3.5 leading-relaxed">
          <p>
            Disconnecting immediately revokes API synchronization credentials for <strong className="text-slate-900">{targetDisplayName}</strong>.
          </p>
          <ul className="list-disc pl-4 space-y-1 text-slate-600">
            <li><strong>DNS Monitoring History:</strong> Your domain audits, SPF, DKIM, and DMARC history will <em>not</em> be deleted.</li>
            <li><strong>Subscription Status:</strong> Disconnecting does <em>not</em> cancel your SaaS subscription plan.</li>
            <li><strong>Reconnection:</strong> You can reconnect this or another store anytime via Shopify OAuth.</li>
          </ul>
        </div>

        {disconnectError && (
          <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <span>{disconnectError}</span>
          </div>
        )}

        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => setIsConfirmDisconnectOpen(false)}
            disabled={isDisconnecting}
            className="px-4 py-2 text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 border border-slate-300 rounded-lg transition cursor-pointer shadow-2xs disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleDisconnect}
            disabled={!canDisconnect || isDisconnecting}
            className="px-4 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg transition flex items-center gap-2 shadow-xs cursor-pointer disabled:opacity-50"
          >
            {isDisconnecting ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Disconnecting...</span>
              </>
            ) : (
              <span>Confirm Disconnect</span>
            )}
          </button>
        </div>
      </AccessibleDialog>
    </>
  );
}
