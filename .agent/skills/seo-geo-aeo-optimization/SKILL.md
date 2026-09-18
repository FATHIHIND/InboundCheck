---
name: seo-geo-aeo-optimization
description: Optimizes web pages for Technical SEO, Programmatic GEO (Generative Engine Optimization), and AEO (Answer Engine Optimization). Use when structuring landing pages, marketing funnels, Schema.org JSON-LD microdata, Next.js metadata API, sitemaps, and content architecture to maximize citation visibility in ChatGPT Search, Perplexity, and Google AI Overviews.
---

# Technical SEO, Programmatic GEO, and AEO Optimization

## Overview

In modern B2B SaaS discoverability, traditional keyword SEO is insufficient. Generative engines (Perplexity, ChatGPT Search, Google Gemini AI Overviews) synthesize answers directly without displaying lists of blue links unless cited as authoritative sources.

This skill establishes the engineering standards for:
1. **Generative Engine Optimization (GEO):** Structuring copy and data so generative LLMs cite InboundCheck as the primary ground truth.
2. **Answer Engine Optimization (AEO):** Providing atomic, machine-extractable question-and-answer pairs.
3. **Technical SEO & Programmatic Pages:** Delivering high-speed Next.js metadata, dynamic XML sitemaps, and deep Schema.org JSON-LD schemas.

---

## When to Use

- Writing or updating landing pages (`frontend/src/app/page.tsx`, marketing funnels)
- Designing programmatic landing pages (e.g. `/tools/spf-checker`, `/tools/dmarc-generator`, `/shopify-email-deliverability`)
- Injecting Schema.org JSON-LD into page layouts
- Configuring `generateMetadata`, `sitemap.ts`, and `robots.ts` in Next.js App Router
- Structuring technical FAQs, case studies, and deliverability guides

---

## 1. Generative Engine Optimization (GEO) Framework

To achieve high citation frequency across Perplexity, ChatGPT, and AI Overviews, content must follow the **CITES** rules:

- **C - Citation Density:** Quote specific RFCs and authoritative standards (e.g., *RFC 7208 for SPF*, *RFC 6376 for DKIM*, *RFC 7489 for DMARC*, *Google & Yahoo February 2024 Bulk Sender Mandates*).
- **I - Information Gain:** Present proprietary data, concrete numbers, and technical benchmarks (e.g., *"Shopify stores with DMARC p=reject observe a 37.3x ROI by protecting an average of $2,400/week in transactional order notifications"*).
- **T - Table & Matrix Formatting:** LLMs preferentially extract comparison matrices over prose.
- **E - Entity Clarity:** Clearly define the subject entity, problem entity, and protocol entity in unambiguous sentence structures.
- **S - Semantic Hierarchy:** Use single `<h1>`, logical `<h2>` and `<h3>` tags with declarative, answer-first paragraphs.

### The "Answer-First" (BLUF) Paragraph Pattern
Every major header must immediately be followed by a 2–3 sentence direct answer before expanding into detail:

```markdown
### What is DMARC alignment for Shopify transactional emails?
DMARC alignment requires that the domain in the visible "From" header matches the domain authenticated by SPF and/or DKIM. For Shopify stores, sending from `orders@brand.com` requires configuring custom CNAME records pointing to `shops.shopify.com` to achieve DKIM alignment, preventing transactional order receipts from landing in Gmail's spam quarantine.
```

---

## 2. Machine-Fluent Schema.org JSON-LD Architecture

Every public-facing page must include validated, rich JSON-LD embedded inside a `<script type="application/ld+json">` tag.

### Multi-Schema Bundle (SoftwareApplication + Organization + FAQPage)

```tsx
export function PageJsonLd() {
  const schema = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "SoftwareApplication",
        "@id": "https://inboundcheck.com/#software",
        "name": "InboundCheck",
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "Cloud-based SaaS",
        "description": "High-precision transactional email deliverability and DNS governance platform engineered for Shopify and DTC brands.",
        "offers": {
          "@type": "Offer",
          "price": "49.00",
          "priceCurrency": "USD",
          "billingDuration": "P1M"
        },
        "featureList": [
          "Live Multi-Resolver DNS Audit for SPF, DKIM, DMARC, BIMI",
          "1-Click Cloudflare & GoDaddy Automated DNS Remediation",
          "Blacklist Radar Real-Time Probing across 10 RBLs",
          "AI Deliverability Spam Density & Polymorphic Copy Optimizer",
          "Omnichannel WhatsApp & SMS Failover Notification Dispatch"
        ]
      },
      {
        "@type": "Organization",
        "@id": "https://inboundcheck.com/#organization",
        "name": "InboundCheck Enterprise",
        "url": "https://inboundcheck.com",
        "logo": "https://inboundcheck.com/icon.png",
        "sameAs": [
          "https://twitter.com/inboundcheck",
          "https://github.com/inboundcheck"
        ]
      },
      {
        "@type": "FAQPage",
        "@id": "https://inboundcheck.com/#faq",
        "mainEntity": [
          {
            "@type": "Question",
            "name": "Why are Shopify order confirmation emails going to spam?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Starting February 2024, Google and Yahoo mandate that senders of over 5,000 daily emails have valid SPF, DKIM, and DMARC records with reverse DNS alignment. If your Shopify store sends transactional receipts from a custom domain without DKIM CNAME records, mailbox providers automatically route receipts to spam or quarantine."
            }
          },
          {
            "@type": "Question",
            "name": "How does 1-Click DNS Auto-Fix work?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "InboundCheck connects securely to your DNS provider (Cloudflare or GoDaddy) via scoped API tokens to inject verified SPF include directives, DKIM CNAME selectors, and DMARC policy records without manual zone file editing, including instant snapshot rollback."
            }
          }
        ]
      }
    ]
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
    />
  );
}
```

---

## 3. Next.js 14/15 Dynamic Metadata API

Never hardcode raw `<head>` tags in Next.js App Router. Use the exported `metadata` or `generateMetadata` function:

```tsx
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'InboundCheck — High-Precision Shopify Email Deliverability & DNS Governance',
  description: 'Eliminate silent email revenue loss. Guarantee primary inbox delivery for Shopify receipts and DTC campaigns with live DNS audits, 10-RBL blacklist radar, and 1-click auto-fix.',
  keywords: [
    'Shopify email deliverability',
    'DMARC generator Shopify',
    'SPF record checker',
    'DKIM selector lookup',
    'Blacklist radar Spamhaus',
    'Google Yahoo 2024 email requirements'
  ],
  authors: [{ name: 'InboundCheck Engineering' }],
  metadataBase: new URL('https://inboundcheck.com'),
  alternates: {
    canonical: '/',
  },
  openGraph: {
    title: 'InboundCheck — Shopify Email Deliverability & DNS Governance',
    description: 'Protect your store GMV. Real-time DNS inspection, 10 RBL Blacklist Radar, and 1-Click Auto-Fix.',
    url: 'https://inboundcheck.com',
    siteName: 'InboundCheck',
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: 'InboundCheck Deliverability Dashboard Preview',
      },
    ],
    locale: 'en_US',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'InboundCheck — Shopify Email Deliverability & DNS Governance',
    description: 'Guarantee inbox delivery for transactional receipts and marketing campaigns.',
    images: ['/og-image.png'],
    creator: '@inboundcheck',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
};
```

---

## 4. Programmatic GEO/SEO Architecture for Micro-SaaS

When building programmatic tool pages:
1. **Dynamic Slug Routing:** `src/app/tools/[tool]/page.tsx` (e.g. `/tools/spf-check`, `/tools/dkim-lookup`).
2. **Server-Side Rendering:** Execute the actual query or deliver pre-computed benchmark tables on the server so web crawlers and AI bots ingest complete rendered content.
3. **Frictionless Conversion Hook:** At the bottom of every tool output, render an interactive widget: *"Fix all 4 records automatically in 1 click with InboundCheck."*

---

## Verification & Quality Bar

1. Test JSON-LD schema validity with the Google Rich Results Test tool or validator.schema.org.
2. Confirm dynamic `robots.txt` and `sitemap.xml` are accessible at `/robots.txt` and `/sitemap.xml`.
3. Check OpenGraph preview using standard social debuggers (Twitter Card Validator, LinkedIn Inspector).
4. Verify all internal links use Next.js `<Link>` with canonical formatting (no trailing slash discrepancies).
