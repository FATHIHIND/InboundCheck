"use client";

import { useState, useSyncExternalStore } from "react";
import { AlertTriangle, X } from "lucide-react";
import { validateClientEnv } from "@/lib/envGuard";

const NO_ISSUES: string[] = [];
let cachedClientIssues: string[] | null = null;

// Client env is inlined at build time and never changes, so there is nothing to subscribe to.
const subscribeNoop = () => () => {};

// Cached so useSyncExternalStore always receives a referentially stable snapshot.
function getClientIssues(): string[] {
  if (cachedClientIssues === null) {
    const result = validateClientEnv();
    cachedClientIssues = result.isValid ? NO_ISSUES : result.issues;
  }
  return cachedClientIssues;
}

// The server render (and hydration pass) shows no banner, matching the previous
// post-mount behaviour and avoiding any hydration mismatch.
const getServerIssues = () => NO_ISSUES;

export default function EnvConfigAlert() {
  const issues = useSyncExternalStore(subscribeNoop, getClientIssues, getServerIssues);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || issues.length === 0) return null;

  return (
    <div className="bg-amber-500/10 border-b border-amber-500/20 px-4 py-2 text-xs font-mono text-amber-300 flex items-center justify-between animate-fadeIn z-50">
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
        <div>
          <span className="font-bold">Configuration Notice:</span> Client environment variable placeholders detected:{" "}
          <span className="text-amber-200 underline">{issues.join(" | ")}</span>
        </div>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="text-amber-400 hover:text-white p-1 rounded transition cursor-pointer"
        aria-label="Dismiss banner"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
