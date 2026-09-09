"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { validateClientEnv } from "@/lib/envGuard";

export default function EnvConfigAlert() {
  const [issues, setIssues] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const result = validateClientEnv();
    if (!result.isValid) {
      setIssues(result.issues);
    }
  }, []);

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
