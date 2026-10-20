import { NextResponse } from "next/server";
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import { resolveCallbackOrigin, sanitizeInternalRedirect } from "@/lib/auth-origin";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next");
  const publicOrigin = resolveCallbackOrigin(request);
  const safeNext = sanitizeInternalRedirect(next, "/dashboard");

  if (code) {
    const cookieStore = cookies();
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL || "",
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "",
      {
        cookies: {
          get(name: string) {
            return cookieStore.get(name)?.value;
          },
          set(name: string, value: string, options: CookieOptions) {
            try {
              cookieStore.set({ name, value, ...options });
            } catch {
              // Server Component / route handler
            }
          },
          remove(name: string, options: CookieOptions) {
            try {
              // Next.js 14 cookies().delete(name) or set with maxAge: 0
              cookieStore.set({ name, value: "", ...options, maxAge: 0 });
            } catch {
              // Server Component / route handler
            }
          },
        },
      }
    );

    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${publicOrigin}${safeNext}`);
    }
  }

  // Return the user to login with notification on canonical origin
  return NextResponse.redirect(`${publicOrigin}/auth/login?error=auth_callback_failed`);
}
