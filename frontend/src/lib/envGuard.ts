/**
 * InboundCheck - Frontend Runtime Environment Integrity Guard
 * ============================================================
 * Validates that essential client environment variables are loaded and
 * not holding unconfigured placeholders, preventing silent network and auth breakages.
 */

export interface EnvValidationResult {
  isValid: boolean;
  issues: string[];
}

const PLACEHOLDER_PATTERNS = [
  "your_",
  "your-project",
  "placeholder",
  "dummy",
  "change_me",
];

function isPlaceholder(value?: string): boolean {
  if (!value) return true;
  const lower = value.trim().toLowerCase();
  return PLACEHOLDER_PATTERNS.some((p) => lower.includes(p));
}

export function validateClientEnv(): EnvValidationResult {
  const issues: string[] = [];

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!supabaseUrl || isPlaceholder(supabaseUrl)) {
    issues.push("NEXT_PUBLIC_SUPABASE_URL is missing or contains placeholder values.");
  }

  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!supabaseKey || isPlaceholder(supabaseKey)) {
    issues.push("NEXT_PUBLIC_SUPABASE_ANON_KEY is unconfigured or placeholder.");
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl || isPlaceholder(apiUrl)) {
    issues.push("NEXT_PUBLIC_API_URL is missing or contains placeholder values.");
  }

  return {
    isValid: issues.length === 0,
    issues,
  };
}
