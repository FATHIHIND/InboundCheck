---
name: glassmorphic-frontend-architecture
description: Builds enterprise-grade, dark glassmorphic Next.js 14/15 interfaces with Tailwind CSS, Lucide icons, and reactive SVG micro-visualizations. Use when designing or modifying dashboard pages, landing pages, modal paywalls, diagnostic inspectors, or UI component systems adhering to InboundCheck's Obsidian dark theme.
---

# Glassmorphic Frontend Architecture & Obsidian Design System

## Overview

Build premium, hyper-polished frontend interfaces that project institutional reliability, technical superiority, and visual distinction. InboundCheck serves high-volume Shopify DTC merchants and enterprise brands; the UI must feel like high-end mission control software, not a generic bootstrap template or toy AI prototype.

This skill establishes the engineering standards, styling tokens, component hierarchy, and accessibility rules for Next.js App Router applications styled with Tailwind CSS, custom glassmorphic layering, and obsidian palettes.

---

## When to Use

- Creating or refactoring pages inside `frontend/src/app/` (Dashboard, Landing, Inspector, Radar, Settings, Billing)
- Building reusable UI primitives in `frontend/src/components/` (Modals, Cards, Charts, Tables, Badges)
- Polishing responsive layouts across desktop, tablet, and mobile viewpoints
- Implementing dark glassmorphic effects, backdrop filters, noise textures, and micro-animations
- Resolving SSR hydration mismatches, React 18/19 Server/Client component boundary issues

---

## Core Architecture Principles

### 1. Server vs. Client Component Boundaries

- **Default to React Server Components (RSC):** Fetch data, render static structural cards, format initial payloads on the server.
- **Isolate Client Components (`'use client'`):**
  - Interactive forms, modals, tabs, dropdowns, and copy-to-clipboard buttons.
  - SVG charting with live tooltips or animations (`ReputationTrendChart`).
  - Polling hooks or WebSocket listeners.
- **Zero Hydration Mismatches:**
  - Never render dates or timestamps from `Date.now()` or `new Date().toLocaleTimeString()` directly in SSR without formatting wrappers or `suppressHydrationWarning`.
  - Always guard browser-only APIs (`window`, `localStorage`, `navigator`) with `useEffect` or `mounted` checks.

### 2. Obsidian Glassmorphic Design Palette

InboundCheck uses an authoritative dark aesthetic with Shopify-emerald and obsidian accents:

| Token | Hex / Value | Usage |
|---|---|---|
| `--background` | `#000000` | True-black canvas base |
| `--surface` | `#0A0A0C` | Primary component card background |
| `--surface-elevated` | `#0E1217` | Elevated inspection panels & hover cards |
| `--border-subtle` | `rgba(0, 128, 96, 0.2)` | Inactive card borders / dividers |
| `--border-active` | `rgba(16, 185, 129, 0.45)`| Active/focused state borders |
| `--accent-shopify` | `#008060` | Institutional Shopify brand accents |
| `--accent-emerald` | `#10B981` | Pass status, deliverability health, active badges |
| `--accent-amber` | `#F59E0B` | Warning, quarantine policy, missing CNAME |
| `--accent-red` | `#EF4444` | Critical failure, blacklist hit, SPF syntax error |
| `--text-primary` | `#FFFFFF` | Primary headings, score values |
| `--text-muted` | `#94A3B8` / `#64748B` | Secondary metrics, field descriptions |

### 3. Glassmorphism & Stipple Texture Standard

Always apply balanced backdrop blur and layered semi-transparency rather than opaque grays:

```tsx
// Glassmorphic Card Container
<div className="relative rounded-2xl border border-white/[0.08] bg-[#0A0A0C]/80 backdrop-blur-xl p-6 shadow-2xl shadow-black/50 transition-all duration-300 hover:border-emerald-500/30 hover:shadow-emerald-950/10">
  {/* Subtle radial inner glow */}
  <div className="absolute -top-24 -right-24 h-48 w-48 rounded-full bg-emerald-500/5 blur-3xl pointer-events-none" />
  {children}
</div>
```

---

## Typography & Iconography Hierarchy

1. **Heading Fonts:** Use `Plus Jakarta Sans` or `Inter` (`font-sans font-bold tracking-tight`).
2. **Technical Data & Records:** Use `JetBrains Mono` (`font-mono text-xs text-emerald-400 bg-emerald-950/20 border border-emerald-900/40 rounded px-2 py-1`) for DNS TXT strings, IPs, selectors, and cryptographic hashes.
3. **Editorial / Impact Accents:** Use `Playfair Display` italic (`font-serif italic text-emerald-300`) selectively on landing page heroes and ROI figures.
4. **Icons:** Exclusively use `lucide-react`. Maintain uniform sizing (`w-4 h-4` for inline badges, `w-5 h-5` for section titles, `w-6 h-6` for stat card headers). Always pair icons with accessible labels (`aria-label` or adjacent text).

---

## High-Precision UI Patterns

### Interactive DNS Record Inspection Card

```tsx
interface RecordInspectorProps {
  type: 'SPF' | 'DKIM' | 'DMARC' | 'BIMI' | 'MX';
  status: 'valid' | 'warning' | 'critical';
  title: string;
  recordValue: string;
  remediationSnippet?: string;
  onApplyFix?: () => void;
}

export function RecordInspectorCard({
  type,
  status,
  title,
  recordValue,
  remediationSnippet,
  onApplyFix
}: RecordInspectorProps) {
  const statusStyles = {
    valid: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400',
    warning: 'border-amber-500/30 bg-amber-500/5 text-amber-400',
    critical: 'border-red-500/30 bg-red-500/5 text-red-400',
  }[status];

  return (
    <div className="group relative overflow-hidden rounded-xl border border-white/[0.07] bg-[#0E1217] p-5 transition-all duration-200 hover:border-white/[0.15]">
      <div className="flex items-center justify-between gap-4 mb-3">
        <div className="flex items-center gap-2.5">
          <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold tracking-wide uppercase border ${statusStyles}`}>
            {type}
          </span>
          <h4 className="text-sm font-semibold text-white/90">{title}</h4>
        </div>
        <span className={`h-2 w-2 rounded-full ${status === 'valid' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]' : status === 'warning' ? 'bg-amber-400' : 'bg-red-500 animate-pulse'}`} />
      </div>

      <div className="rounded-lg bg-black/60 border border-white/[0.04] p-3 font-mono text-xs text-slate-300 break-all select-all">
        {recordValue}
      </div>

      {remediationSnippet && (
        <div className="mt-3 pt-3 border-t border-white/[0.06] flex items-center justify-between">
          <p className="text-xs text-slate-400">Suggested Action Available</p>
          {onApplyFix && (
            <button
              onClick={onApplyFix}
              className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 rounded-md transition-colors"
            >
              1-Click Fix
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

---

## Enterprise UI Directives & Neutral Naming Rules

> [!IMPORTANT]
> **Strict Neutral Enterprise Terminology Rule:**  
> Never display raw LLM vendor or model names (e.g. "Kimi", "ChatGPT", "DeepSeek", "GPT-4", "OpenAI") in end-user facing frontend UI strings, buttons, tooltips, or toast notifications.  
> Always use institutional enterprise phrasing:
> - `AI Content Lab & Cryptographic Content Optimizer`
> - `Deliverability Intelligence Engine`
> - `Polymorphic Copy Generator`
> - `Liquid-Preserving Content Scanner`

---

## Anti-Patterns to Avoid

- ❌ **Pure CSS `#808080` Grays:** Looks washed out and amateur. Use zinc/slate dark hues (`#0A0A0C`, `#0E1217`, `#181E27`).
- ❌ **Over-blurring with heavy DOM nesting:** Stacking more than 3 nested `backdrop-blur` elements degrades 60fps GPU rendering on lower-end mobile devices.
- ❌ **Opaque Modals:** Modals should feel part of the environment with `backdrop-blur-md bg-black/75 border border-white/[0.1]`.
- ❌ **Raw Unstyled Scrollbars:** Always use sleek custom webkit scrollbar styles defined in `globals.css`.
- ❌ **Non-Responsive Data Tables:** Every tabular view must wrap in `overflow-x-auto` or stack cards gracefully on screens `< 768px`.

---

## Verification & Quality Bar

Before marking any UI task complete:
1. Run `npm run build` inside `frontend/` to confirm zero TypeScript compilation errors.
2. Inspect dark mode contrast ratios (minimum 4.5:1 for standard body text, 3:1 for large headers).
3. Test keyboard navigability (`Tab`, `Escape` to close modals, `Enter` to trigger actions).
4. Verify responsive reflow at 375px (mobile), 768px (tablet), and 1440px (desktop).
