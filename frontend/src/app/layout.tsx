import type { Metadata } from "next";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import EnvConfigAlert from "@/components/ui/EnvConfigAlert";

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  weight: ["400", "500", "600", "700", "800"],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://inboundcheck.com"),
  title: {
    default: "InboundCheck — Shopify Email Deliverability & DNS Governance Platform",
    template: "%s | InboundCheck",
  },
  description:
    "Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts.",
  keywords: [
    "shopify order confirmation email going to spam",
    "shopify order emails not received",
    "shopify dkim dmarc 2024 compliance",
    "fix spf 10 lookup limit shopify",
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
    title: "InboundCheck — Shopify Order Email Guardian & Deliverability Engine",
    description:
      "Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts.",
    url: "https://inboundcheck.com",
    siteName: "InboundCheck",
    locale: "en_US",
    type: "website",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "InboundCheck — Shopify Order Email Guardian & DNS Deliverability Platform",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "InboundCheck — Shopify Order Email Guardian & Deliverability Engine",
    description:
      "Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts.",
    creator: "@inboundcheck",
    images: ["/og-image.png"],
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
    <html lang="en" className={`dark scroll-smooth ${plusJakartaSans.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-black text-zinc-100 antialiased selection:bg-emerald-500/20 selection:text-emerald-300 font-sans">
        <EnvConfigAlert />
        {children}
      </body>
    </html>
  );
}
