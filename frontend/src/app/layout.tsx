import type { Metadata } from "next";
import "./globals.css";

import EnvConfigAlert from "@/components/ui/EnvConfigAlert";

export const metadata: Metadata = {
  metadataBase: new URL("https://inboundcheck.com"),
  title: {
    default: "InboundCheck — Shopify Email Deliverability & DNS Governance Platform",
    template: "%s | InboundCheck",
  },
  description:
    "Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts.",
  keywords: [
    "Shopify email deliverability",
    "Shopify DNS diagnostic",
    "transactional email spam prevention",
    "Google Yahoo 2024 email compliance",
    "DMARC enforcement Shopify",
    "DKIM selector verification",
    "SPF record generator",
    "blacklist monitoring",
  ],
  authors: [{ name: "InboundCheck Engineering" }],
  creator: "InboundCheck",
  publisher: "InboundCheck",
  alternates: {
    canonical: "https://inboundcheck.com",
  },
  openGraph: {
    title: "InboundCheck — High-Precision Transactional Deliverability for Shopify",
    description:
      "Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts.",
    url: "https://inboundcheck.com",
    siteName: "InboundCheck",
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "InboundCheck — Shopify Email Deliverability & DNS Governance",
    description:
      "Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts.",
    creator: "@inboundcheck",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark scroll-smooth">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-[#09090b] text-zinc-100 antialiased selection:bg-emerald-500/20 selection:text-emerald-300 font-['Plus_Jakarta_Sans',sans-serif]">
        <EnvConfigAlert />
        {children}
      </body>
    </html>
  );
}
