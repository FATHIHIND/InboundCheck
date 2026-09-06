"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ShieldCheck, Lock, ArrowRight, Check, AlertCircle } from "lucide-react";
import { supabase } from "@/lib/supabase/client";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isSessionReady, setIsSessionReady] = useState(false);

  useEffect(() => {
    // Check if recovery session is active or exchange hash / code
    const checkSession = async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (session) {
          setIsSessionReady(true);
        }
      } catch (err) {
        console.warn("Session retrieval on password reset:", err);
      }
    };

    checkSession();

    // Listen for PASSWORD_RECOVERY auth event
    const { data: authListener } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") {
        setIsSessionReady(true);
      }
    });

    return () => {
      authListener.subscription.unsubscribe();
    };
  }, []);

  const handlePasswordUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      if (password.length < 8) {
        throw new Error("Password must be at least 8 characters in length.");
      }

      if (password !== confirmPassword) {
        throw new Error("Passwords do not match. Please ensure both fields match.");
      }

      const { data, error } = await supabase.auth.updateUser({
        password: password,
      });

      if (error) {
        throw error;
      }

      setSuccessMessage("Your password has been successfully updated! Redirecting to dashboard...");

      // Redirect after 2 seconds
      setTimeout(() => {
        router.push("/dashboard");
      }, 2000);
    } catch (err: any) {
      setErrorMessage(
        err.message || "Failed to update password. Your recovery link may have expired."
      );
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
          <h1 className="text-2xl font-extrabold text-white">Create new password</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Choose a strong password with at least 8 characters
          </p>
        </div>

        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {successMessage && (
          <div className="mb-4 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-start gap-3">
            <Check className="w-5 h-5 text-emerald-400 mt-0.5 shrink-0" />
            <div>
              <p className="font-bold text-emerald-300 text-sm">Password Updated!</p>
              <p className="mt-1 text-zinc-300">{successMessage}</p>
            </div>
          </div>
        )}

        <form onSubmit={handlePasswordUpdate} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-zinc-300 mb-1.5">New password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3.5" />
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                className="w-full pl-10 pr-4 py-2.5 bg-zinc-950/80 border border-zinc-800 rounded-xl text-white placeholder-zinc-500 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-zinc-300 mb-1.5">
              Confirm new password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3.5" />
              <input
                type="password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter your new password"
                className="w-full pl-10 pr-4 py-2.5 bg-zinc-950/80 border border-zinc-800 rounded-xl text-white placeholder-zinc-500 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading || Boolean(successMessage)}
            className="w-full py-3 bg-emerald-400 hover:bg-emerald-300 text-black font-bold rounded-xl text-sm transition shadow-lg shadow-emerald-500/25 flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
          >
            {isLoading ? "Updating Password..." : "Update Password"}
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>

        <div className="mt-6 pt-6 border-t border-zinc-800 text-center text-xs text-zinc-400">
          Remember your password?{" "}
          <Link href="/auth/login" className="text-emerald-400 font-semibold hover:underline">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
