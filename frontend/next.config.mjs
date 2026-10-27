const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://images.unsplash.com https://avatars.githubusercontent.com",
  "font-src 'self' data:",
  "media-src 'self' https://cdn.sceneai.art data: blob:",
  "connect-src 'self' http://localhost:8000 https://api.inboundcheck.com https://inboundcheck-production.up.railway.app https://*.supabase.co wss://*.supabase.co",
  "frame-src 'self' https://accounts.google.com",
  "frame-ancestors 'self'",
  "form-action 'self' https://accounts.google.com",
  "base-uri 'self'",
  "object-src 'none'",
].join("; ");

const permissionsPolicy = "camera=(), microphone=(), geolocation=(), browsing-topics=()";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    unoptimized: true,
  },
  transpilePackages: ["@designcodeio/threeui", "three"],
  experimental: {
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
            key: "X-Frame-Options",
            value: "SAMEORIGIN",
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
