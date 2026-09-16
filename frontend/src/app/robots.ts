import { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: [
          "/",
          "/auth/login",
          "/auth/signup",
          "/auth/forgot-password",
          "/auth/reset-password",
        ],
        disallow: [
          "/dashboard/",
          "/dashboard/*",
          "/api/",
          "/api/*",
          "/auth/callback",
        ],
      },
    ],
    sitemap: "https://inboundcheck.com/sitemap.xml",
  };
}
