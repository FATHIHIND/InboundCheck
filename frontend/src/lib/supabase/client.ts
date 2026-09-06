import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  const supabaseUrl =
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder-project.supabase.co";
  const supabaseAnonKey =
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.placeholder";

  const isRememberMe =
    typeof window !== "undefined"
      ? localStorage.getItem("inboundcheck_remember_me") !== "false"
      : true;

  return createBrowserClient(supabaseUrl, supabaseAnonKey, {
    cookieOptions: {
      maxAge: isRememberMe ? 60 * 60 * 24 * 30 : undefined, // 30-day persistence vs browser-session
      sameSite: "lax",
      path: "/",
    },
  });
}

export const supabase = createClient();
