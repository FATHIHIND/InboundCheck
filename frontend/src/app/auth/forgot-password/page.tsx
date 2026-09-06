"use client";

import { useState } from "react";
import Link from "next/link";
import { ShieldCheck, Mail, ArrowRight, ArrowLeft, Check, AlertCircle } from "lucide-react";
import { supabase } from "@/lib/supabase/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const handleResetRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
        throw new Error("Supabase authentication is not configured in environment.");
      }

      const cleanEmail = email.trim().toLowerCase();
      if (!cleanEmail) {
        throw new Error("Please enter a valid email address.");
      }

      const redirectUrl = `${window.location.origin}/auth/callback?next=/auth/reset-password`;
      const { error } = await supabase.auth.resetPasswordForEmail(cleanEmail, {
        redirectTo: redirectUrl,
      });

      if (error) {
        throw error;
      }

      setSuccessMessage(
        `If an account exists for ${cleanEmail}, a secure password reset link has been dispatched. Please check your inbox and spam folder.`
      );
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to send reset instructions. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#09090b] flex items-center justify-center p-4 bg-grid-pattern relative">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-emerald-500/10 blur-[140px] pointer-events-none rounded-full" />

      <div className="w-full max-w-md glass-card rounded-2xl p-8 border border-zinc-800 relative z-10">
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center space-x-2.5 mb-4">
            <div className="w-9 h-9 rounded-xl bg-emerald-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <ShieldCheck className="w-5 h-5 text-black font-bold" />
            </div>
            <span className="font-extrabold text-xl tracking-tight text-white">InboundCheck</span>
          </Link>
          <h1 className="text-2xl font-extrabold text-white">Reset your password</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Enter your account email to receive a secure recovery link
          </p>
        </div>

        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {successMessage ? (
          <div className="space-y-5">
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-start gap-3">
              <Check className="w-5 h-5 text-emerald-400 mt-0.5 shrink-0" />
              <div>
                <p className="font-bold text-emerald-300 text-sm">Recovery Link Sent</p>
                <p className="mt-1 text-zinc-300 leading-relaxed">{successMessage}</p>
              </div>
            </div>

            <div className="pt-2 text-center">
              <Link
                href="/auth/login"
                className="inline-flex items-center gap-2 text-sm font-semibold text-emerald-400 hover:text-emerald-300 transition"
              >
                <ArrowLeft className="w-4 h-4" />
                Return to sign in
              </Link>
            </div>
          </div>
        ) : (
          <form onSubmit={handleResetRequest} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-zinc-300 mb-1.5">
                Work email address
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3.5" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="merchant@brandshop.com"
                  className="w-full pl-10 pr-4 py-2.5 bg-zinc-950/80 border border-zinc-800 rounded-xl text-white placeholder-zinc-500 text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3 bg-emerald-400 hover:bg-emerald-300 text-black font-bold rounded-xl text-sm transition shadow-lg shadow-emerald-500/25 flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
            >
              {isLoading ? "Sending Link..." : "Send Password Recovery Link"}
              <ArrowRight className="w-4 h-4" />
            </button>

            <div className="pt-4 border-t border-zinc-800/80 text-center">
              <Link
                href="/auth/login"
                className="inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white transition"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Back to sign in
              </Link>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
