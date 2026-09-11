"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ShieldCheck, Mail, Lock, ArrowRight, Check, AlertCircle, RefreshCw } from "lucide-react";
import { supabase } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [showResendAction, setShowResendAction] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedPref = localStorage.getItem("inboundcheck_remember_me");
      if (savedPref !== null) {
        setRememberMe(savedPref !== "false");
      }
    }
  }, []);

  const handleRememberMeChange = (checked: boolean) => {
    setRememberMe(checked);
    if (typeof window !== "undefined") {
      localStorage.setItem("inboundcheck_remember_me", checked ? "true" : "false");
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage("");
    setSuccessMessage("");
    setShowResendAction(false);

    try {
      if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
        throw new Error("Supabase authentication is not configured in environment.");
      }

      const cleanEmail = email.trim().toLowerCase();

      // Persist session preference
      if (typeof window !== "undefined") {
        localStorage.setItem("inboundcheck_remember_me", rememberMe ? "true" : "false");
      }

      const { data, error } = await supabase.auth.signInWithPassword({
        email: cleanEmail,
        password,
      });

      if (error) {
        throw error;
      }

      if (!data?.session) {
        throw new Error("Invalid credentials or session could not be established.");
      }

      router.push("/dashboard");
    } catch (err: any) {
      const rawMsg = err.message || "Failed to sign in";
      const lower = rawMsg.toLowerCase();

      if (lower.includes("email not confirmed") || lower.includes("not confirmed")) {
        setErrorMessage("Please check your email to confirm your account first before signing in.");
        setShowResendAction(true);
      } else if (lower.includes("invalid login credentials")) {
        setErrorMessage(
          "Invalid email or password. If you recently registered, please ensure your email has been confirmed."
        );
        setShowResendAction(true);
      } else {
        setErrorMessage(rawMsg);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleResendConfirmation = async () => {
    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail) {
      setErrorMessage("Please enter your email address above to resend the confirmation email.");
      return;
    }

    setIsResending(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const { error } = await supabase.auth.resend({
        type: "signup",
        email: cleanEmail,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      });

      if (error) {
        throw error;
      }

      setSuccessMessage(
        `Confirmation email has been dispatched to ${cleanEmail}. Please check your inbox and spam folder.`
      );
      setShowResendAction(false);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to resend confirmation email.");
    } finally {
      setIsResending(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setIsGoogleLoading(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
        throw new Error("Supabase authentication is not configured in environment.");
      }

      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
          queryParams: {
            access_type: "offline",
            prompt: "consent",
          },
        },
      });

      if (error) {
        throw error;
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to initiate Google sign-in.");
      setIsGoogleLoading(false);
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
          <h1 className="text-2xl font-extrabold text-white">Welcome back</h1>
          <p className="text-xs text-zinc-400 mt-1">Sign in to monitor your Shopify domain deliverability</p>
        </div>

        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex flex-col gap-2">
            <div className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
              <span>{errorMessage}</span>
            </div>
            {showResendAction && (
              <button
                type="button"
                onClick={handleResendConfirmation}
                disabled={isResending}
                className="mt-1 self-start inline-flex items-center gap-1.5 text-xs text-emerald-400 hover:text-emerald-300 font-semibold underline disabled:opacity-50 cursor-pointer"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isResending ? "animate-spin" : ""}`} />
                {isResending ? "Resending..." : "Resend confirmation email"}
              </button>
            )}
          </div>
        )}

        {successMessage && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-start gap-2.5">
            <Check className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
            <span>{successMessage}</span>
          </div>
        )}

        {/* Google OAuth Button */}
        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={isGoogleLoading || isLoading}
          className="w-full py-2.5 px-4 bg-zinc-900/90 hover:bg-zinc-850 hover:border-zinc-700 text-zinc-200 border border-zinc-800 rounded-xl text-xs font-semibold transition flex items-center justify-center gap-2.5 mb-5 cursor-pointer disabled:opacity-50 shadow-sm"
        >
          {isGoogleLoading ? (
            <RefreshCw className="w-4 h-4 animate-spin text-zinc-400" />
          ) : (
            <svg className="w-4 h-4" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"
              />
              <path
                fill="#34A853"
                d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.33 24 12 24z"
              />
              <path
                fill="#FBBC05"
                d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 10.03 0 12s.45 3.82 1.25 5.42l4.03-3.15z"
              />
              <path
                fill="#EA4335"
                d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
              />
            </svg>
          )}
          <span>Continue with Google</span>
        </button>

        <div className="relative flex items-center justify-center mb-5">
          <div className="border-t border-zinc-800 w-full" />
          <span className="bg-[#0e0e12] px-3 text-[11px] text-zinc-500 uppercase tracking-wider shrink-0 font-medium">
            or continue with email
          </span>
          <div className="border-t border-zinc-800 w-full" />
        </div>

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-zinc-300 mb-1.5">Email address</label>
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

          <div>
            <label className="block text-xs font-semibold text-zinc-300 mb-1.5">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3.5" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-10 pr-4 py-2.5 bg-zinc-950/80 border border-zinc-800 rounded-xl text-white placeholder-zinc-500 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="flex items-center justify-between text-xs">
            <label className="flex items-center text-zinc-400 cursor-pointer select-none">
              <input
                type="checkbox"
                id="remember-me"
                checked={rememberMe}
                onChange={(e) => handleRememberMeChange(e.target.checked)}
                className="rounded bg-zinc-900 border-zinc-800 text-emerald-500 mr-2 focus:ring-0 focus:ring-offset-0 cursor-pointer"
              />
              Remember me
            </label>
            <Link href="/auth/forgot-password" className="text-emerald-400 hover:text-emerald-300 transition">
              Forgot password?
            </Link>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-3 bg-emerald-400 hover:bg-emerald-300 text-black font-bold rounded-xl text-sm transition shadow-lg shadow-emerald-500/25 flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
          >
            {isLoading ? "Signing in..." : "Sign in to Dashboard"}
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>

        <div className="mt-6 pt-6 border-t border-zinc-800 text-center text-xs text-zinc-400">
          Don&apos;t have an account?{" "}
          <Link href="/auth/signup" className="text-emerald-400 font-semibold hover:underline">
            Create an account
          </Link>
        </div>
      </div>
    </div>
  );
}
