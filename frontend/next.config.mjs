import { fileURLToPath } from "node:url";
// Public build configuration can add exact connection origins, never CSP syntax.
export function getConfiguredConnectSources(env = process.env) {
  const sources = [];
  for (const key of ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_SUPABASE_URL"]) {
    if (!env[key]) continue;
    try {
      const url = new URL(env[key]);
      const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
      if (url.username || url.password) continue;
      if (!/^[a-z0-9.\[\]:-]+$/i.test(url.hostname)) continue;
      if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) continue;
      sources.push(url.origin);
      if (key === "NEXT_PUBLIC_SUPABASE_URL") {
        sources.push((url.protocol === "https:" ? "wss://" : "ws://") + url.host);
      }
    } catch {
      // Invalid public configuration must never weaken the policy.
    }
  }
  return [...new Set(sources)];
}

// Static App Router pages require inline hydration scripts. See SECURITY.md.
const isDevelopment = process.env.NODE_ENV === "development";
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://images.unsplash.com https://avatars.githubusercontent.com",
  "font-src 'self' data:",
  "media-src 'self' https://cdn.sceneai.art data: blob:",
  ["connect-src 'self' https://api.inboundcheck.com https://inboundcheck-production.up.railway.app", ...(isDevelopment ? ["http://localhost:8000"] : []), ...getConfiguredConnectSources()].join(" "),
  "frame-src 'self' https://accounts.google.com",
  "form-action 'self' https://accounts.google.com",
  "base-uri 'self'",
  "object-src 'none'",
  // FE-2: forbid any origin from framing the app (clickjacking defence).
  "frame-ancestors 'none'",
].join("; ");

const permissionsPolicy = "camera=(), microphone=(), geolocation=(), browsing-topics=()";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  images: {
    unoptimized: true,
  },
  transpilePackages: ["@designcodeio/threeui", "three"],
  outputFileTracingRoot: fileURLToPath(new URL("..", import.meta.url)),
  experimental: {
    cpus: 1, // Bound build workers on local machines and CI.
    webpackBuildWorker: false, // Compile in-process in restricted local/CI environments.
    optimizePackageImports: ["lucide-react"],
  },
  async redirects() {
    return [
      {
        source: "/login",
        destination: "/auth/login",
        permanent: true,
      },
      {
        source: "/signup",
        destination: "/auth/signup",
        permanent: true,
      },
      {
        source: "/dashboard/domains",
        destination: "/dashboard/shopify",
        permanent: true,
      },
      {
        source: "/dashboard/stores",
        destination: "/dashboard/shopify",
        permanent: true,
      },
      {
        source: "/dashboard/action-center",
        destination: "/dashboard/inspector",
        permanent: true,
      },
      {
        source: "/dashboard/template-optimizer",
        destination: "/dashboard/content-lab",
        permanent: true,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            // Legacy fallback for browsers that ignore CSP frame-ancestors.
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: permissionsPolicy,
          },
          {
            key: "Content-Security-Policy",
            value: contentSecurityPolicy,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
