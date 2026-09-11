"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ShieldCheck, Mail, Lock, User, ArrowRight, Check } from "lucide-react";
import { supabase } from "@/lib/supabase/client";

export default function SignupPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);

  const handleGoogleSignUp = async () => {
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
      setErrorMessage(err.message || "Failed to initiate Google sign-up.");
      setIsGoogleLoading(false);
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
        throw new Error("Supabase authentication is not configured in environment.");
      }

      const cleanFullName = fullName.trim();
      const cleanEmail = email.trim().toLowerCase();

      const { data, error } = await supabase.auth.signUp({
        email: cleanEmail,
        password,
        options: {
          data: {
            full_name: cleanFullName,
            name: cleanFullName,
          },
        },
      });

      if (error) {
        throw error;
      }

      if (!data?.user) {
        throw new Error("Unable to create account. Please try again.");
      }

      // Check if user already exists (Supabase returns empty identities array when email confirmation is active)
      if (Array.isArray(data.user.identities) && data.user.identities.length === 0) {
        setErrorMessage("An account with this email address already exists. Please sign in instead.");
        return;
      }

      if (data.session) {
        router.push("/dashboard");
      } else {
        // Confirmation email sent
        setSuccessMessage("Account created successfully! Please check your email inbox to confirm your account, then sign in.");
      }
    } catch (err: any) {
      const msg = err.message || "Failed to create account";
      if (msg.includes("Database error saving new user")) {
        setErrorMessage("A database setup error occurred during registration. Please contact support or try again in a moment.");
      } else {
        setErrorMessage(msg);
      }
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
          <h1 className="text-2xl font-extrabold text-white">Get started for free</h1>
          <p className="text-xs text-zinc-400 mt-1">Audit and secure your Shopify store deliverability today</p>
        </div>

        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-start gap-2">
            <span className="font-semibold">Error:</span> {errorMessage}
          </div>
        )}

        {successMessage && (
          <div className="mb-4 p-3.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-start gap-2.5">
            <Check className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
            <div>
              <p className="font-semibold text-emerald-300">Registration initiated!</p>
              <p className="mt-0.5 text-zinc-300">{successMessage}</p>
            </div>
          </div>
        )}

        {/* Google OAuth Button */}
        <button
          type="button"
          onClick={handleGoogleSignUp}
          disabled={isGoogleLoading || isLoading}
          className="w-full py-2.5 px-4 bg-zinc-900/90 hover:bg-zinc-850 hover:border-zinc-700 text-zinc-200 border border-zinc-800 rounded-xl text-xs font-semibold transition flex items-center justify-center gap-2.5 mb-5 cursor-pointer disabled:opacity-50 shadow-sm"
        >
          {isGoogleLoading ? (
            <div className="w-4 h-4 border-2 border-zinc-400 border-t-transparent rounded-full animate-spin" />
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
            or register with email
          </span>
          <div className="border-t border-zinc-800 w-full" />
        </div>

        <form onSubmit={handleSignup} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-zinc-300 mb-1.5">Full name</label>
            <div className="relative">
              <User className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3.5" />
              <input
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Alex Morgan"
                className="w-full pl-10 pr-4 py-2.5 bg-zinc-950/80 border border-zinc-800 rounded-xl text-white placeholder-zinc-500 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-zinc-300 mb-1.5">Work email</label>
            <div className="relative">
              <Mail className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3.5" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="merchant@store.com"
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
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                className="w-full pl-10 pr-4 py-2.5 bg-zinc-950/80 border border-zinc-800 rounded-xl text-white placeholder-zinc-500 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="space-y-1.5 py-1 text-[11px] text-zinc-400">
            <div className="flex items-center gap-1.5"><Check className="w-3.5 h-3.5 text-emerald-400" /> 14-day free trial on Growth tier</div>
            <div className="flex items-center gap-1.5"><Check className="w-3.5 h-3.5 text-emerald-400" /> No credit card required</div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-3 bg-emerald-400 hover:bg-emerald-300 text-black font-bold rounded-xl text-sm transition shadow-lg shadow-emerald-500/25 flex items-center justify-center gap-2 cursor-pointer"
          >
            {isLoading ? "Creating Account..." : "Create Free Account"}
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>

        <div className="mt-6 pt-6 border-t border-zinc-800 text-center text-xs text-zinc-400">
          Already have an account?{" "}
          <Link href="/auth/login" className="text-emerald-400 font-semibold hover:underline">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
