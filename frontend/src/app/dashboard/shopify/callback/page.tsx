"use client";

import React, { useEffect, useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ShoppingBag,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ArrowRight,
  Loader2,
} from "lucide-react";
import { apiFetch } from "@/lib/api";

function ShopifyCallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [status, setStatus] = useState<"processing" | "success" | "error">("processing");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [shopDomain, setShopDomain] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function handleExchange() {
      const errorParam = searchParams.get("error");
      const code = searchParams.get("code");
      const shop = searchParams.get("shop");
      const state = searchParams.get("state");

      // 1. Handle explicit Shopify OAuth denial or cancellation
      if (errorParam) {
        if (!isMounted) return;
        setStatus("error");
        setErrorMessage(
          errorParam === "access_denied"
            ? "Shopify authorization was declined. You can connect your store anytime from the Shopify Hub."
            : "Shopify authorization could not be completed. Please try connecting your store again."
        );
        return;
      }

      // 2. Validate presence of required OAuth parameters
      if (!code || !shop || !state) {
        if (!isMounted) return;
        setStatus("error");
        setErrorMessage("Missing required authorization parameters. Please initiate connection from Shopify Hub.");
        return;
      }

      const cleanShop = shop.trim().toLowerCase();
      setShopDomain(cleanShop);

      try {
        // 3. Forward OAuth parameters to existing backend exchange API
        const forwardParams = new URLSearchParams();
        forwardParams.set("code", code);
        forwardParams.set("shop", cleanShop);
        forwardParams.set("state", state);

        const hmac = searchParams.get("hmac");
        if (hmac) forwardParams.set("hmac", hmac);

        const timestamp = searchParams.get("timestamp");
        if (timestamp) forwardParams.set("timestamp", timestamp);

        const res = await apiFetch(`/api/v1/shopify/oauth/callback?${forwardParams.toString()}`, {
          method: "GET",
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(
            errData.detail || "Failed to complete Shopify store connection. Please verify your store domain."
          );
        }

        const data = await res.json();
        if (!isMounted) return;

        setStatus("success");
        setShopDomain(data.shop || cleanShop);

        // 4. Safe internal redirect to dashboard wizard (prevents open redirects)
        const targetShop = encodeURIComponent(data.shop || cleanShop);
        setTimeout(() => {
          if (isMounted) {
            router.push(`/dashboard/wizard?shop=${targetShop}`);
          }
        }, 1200);
      } catch (err: unknown) {
        if (!isMounted) return;
        console.error("Shopify OAuth exchange error:", err);
        setStatus("error");
        setErrorMessage(
          err instanceof Error
            ? err.message
            : "An unexpected error occurred during store authorization. Please try again."
        );
      }
    }

    handleExchange();

    return () => {
      isMounted = false;
    };
  }, [searchParams, router]);

  return (
    <div className="min-h-screen bg-[#050507] text-zinc-100 flex items-center justify-center p-6 selection:bg-emerald-500/20 selection:text-emerald-300 font-sans">
      <div className="relative w-full max-w-lg rounded-2xl border border-white/[0.08] bg-[#0A0A0C]/90 backdrop-blur-2xl p-8 sm:p-10 shadow-2xl shadow-black/80">
        {/* Subtle radial emerald background glow */}
        <div className="absolute -top-24 -right-24 h-48 w-48 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -left-24 h-48 w-48 rounded-full bg-emerald-500/5 blur-3xl pointer-events-none" />

        <div className="relative z-10 flex flex-col items-center text-center space-y-6">
          {/* Header Brand Signal */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <ShoppingBag className="w-5 h-5" />
            </div>
            <span className="text-sm font-mono text-zinc-400 font-semibold tracking-wider uppercase">
              InboundCheck • Shopify Sync
            </span>
          </div>

          {/* State: Processing */}
          {status === "processing" && (
            <div className="space-y-4 py-4">
              <div className="relative flex items-center justify-center">
                <Loader2 className="w-12 h-12 animate-spin text-emerald-400" />
                <ShieldCheck className="w-5 h-5 text-emerald-300 absolute" />
              </div>
              <div className="space-y-2">
                <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                  Connecting Your Shopify Store
                </h1>
                <p className="text-sm text-zinc-400 max-w-sm">
                  Verifying cryptographic signatures and establishing secure deliverability monitoring...
                </p>
                {shopDomain && (
                  <div className="inline-block mt-2 px-3 py-1 rounded-md bg-white/[0.04] border border-white/[0.08] text-xs font-mono text-emerald-400">
                    {shopDomain}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* State: Success */}
          {status === "success" && (
            <div className="space-y-4 py-4">
              <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mx-auto shadow-lg shadow-emerald-950/20">
                <CheckCircle2 className="w-8 h-8" />
              </div>
              <div className="space-y-2">
                <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                  Store Connected Successfully
                </h1>
                <p className="text-sm text-zinc-400 max-w-sm">
                  Authorization verified. Transitioning to deliverability readiness wizard...
                </p>
                {shopDomain && (
                  <div className="inline-block mt-2 px-3 py-1 rounded-md bg-emerald-950/30 border border-emerald-500/20 text-xs font-mono text-emerald-300">
                    {shopDomain}
                  </div>
                )}
              </div>
              <div className="pt-2">
                <Link
                  href={`/dashboard/wizard${shopDomain ? `?shop=${encodeURIComponent(shopDomain)}` : ""}`}
                  className="inline-flex items-center gap-2 text-xs font-mono text-emerald-400 hover:text-emerald-300 transition"
                >
                  Click here if not redirected automatically
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>
          )}

          {/* State: Error */}
          {status === "error" && (
            <div className="space-y-4 py-4">
              <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 mx-auto shadow-lg shadow-amber-950/20">
                <AlertTriangle className="w-8 h-8" />
              </div>
              <div className="space-y-2">
                <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                  Connection Incomplete
                </h1>
                <p className="text-sm text-zinc-400 max-w-sm leading-relaxed">
                  {errorMessage || "We could not verify your Shopify authorization. No changes were made."}
                </p>
              </div>
              <div className="pt-4 flex flex-col sm:flex-row items-center gap-3 justify-center">
                <Link
                  href="/dashboard/shopify"
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.12] text-xs font-mono text-white transition flex items-center justify-center gap-2"
                >
                  <ShoppingBag className="w-3.5 h-3.5" />
                  Return to Shopify Hub
                </Link>
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-xs font-mono text-emerald-300 transition flex items-center justify-center gap-2"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Retry Verification
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ShopifyCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#050507] text-zinc-100 flex items-center justify-center p-6 font-sans">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-8 h-8 animate-spin text-emerald-400" />
            <span className="text-xs font-mono text-zinc-400">Loading callback...</span>
          </div>
        </div>
      }
    >
      <ShopifyCallbackContent />
    </Suspense>
  );
}
