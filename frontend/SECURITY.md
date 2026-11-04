# Frontend build and CSP constraints

The repository root is the npm workspace and owns the only package-lock.json.
Use Node 24 LTS and npm 11; packageManager records npm 11.12.1.
Install with npm ci --offline --ignore-scripts when the complete npm cache is available.
Run npm run lint/typecheck/test/build --workspace frontend (each separately).
Build the container from the repository root: docker build -f frontend/Dockerfile .
Both Docker ignore files exclude all real dotenv files, including nested ones.
Only public NEXT_PUBLIC_* configuration belongs in Docker build arguments; these
values are embedded in browser bundles. Never pass backend/service-role secrets.

## CSP: partial remediation, not a strict nonce policy

Production scripts no longer allow unsafe-eval. Development retains it because
Next's development tooling uses eval. Script unsafe-inline remains intentionally:
Next 14 App Router statically prerenders pages with inline bootstrap/Flight
hydration scripts, and the landing page emits JSON-LD. A random nonce created
only in middleware would not match these build-time static scripts. Removing
unsafe-inline without changing the rendering architecture breaks hydration.

A supported nonce migration requires per-request CSP and nonce request headers,
forcing affected layouts/routes to dynamic rendering, propagating the nonce to
all authored inline scripts, and checking cached HTML, auth redirects, and
hydration in a real browser. This has not been performed in this bounded change.
The current policy therefore still permits injected inline JavaScript; it is
NOT full XSS protection or a completed strict-CSP remediation. Inline styles also
remain allowed because React style attributes/animation components use them.
No deployment/header/hydration verification against a real provider was done.

## Offline font builds

The root layout no longer calls next/font/google, which downloads CSS and font
binaries during builds. CSS prefers locally installed Plus Jakarta Sans and
JetBrains Mono, then system fonts. Users without those fonts see system fallback
typography; no unlicensed/cached build artifacts were copied into source.

## Lockfile validation boundary

Cross-platform Next SWC and resolver binaries were recovered from locally cached
registry metadata, retaining recorded integrity values. The optional Darwin-only
fsevents metadata/tarball is absent from every located local npm cache. No
exact version or integrity is invented: its entry remains absent. Consequently
this lockfile is an incomplete offline draft, NOT a validated npm-ci-ready lock.
A prior ci dry-run used a manually pinned fsevents entry; that unsupported entry
was removed. A fresh Windows ci --offline --ignore-scripts --dry-run still passes
(exit 0), but it does not validate macOS or prove tarball availability.
Windows sandbox policy also denies npm workspace symlink creation (EPERM), so
root npm ci cannot complete here even when the dependency cache is present.
Do not mistake a dry-run or the separate non-workspace dependency installation
for a successful clean root workspace installation.

Public NEXT_PUBLIC_API_URL and NEXT_PUBLIC_SUPABASE_URL additionally contribute
exact origins to CSP connect-src at build time. HTTPS is required except for
loopback HTTP development; credentials, invalid hosts and non-HTTP schemes are
rejected. Supabase also contributes its matching WebSocket origin. Changes to
public build configuration require a rebuild; no dotenv values were inspected.

## Short-path Windows verification

Earlier attempts under .phase5-verification/f failed with EPERM mkdir, including
.next/server/app/robots.txt at a 102-character absolute path. A neighboring path
probe succeeded, so ordinary MAX_PATH and a blanket write prohibition did not
explain that failure. A later instrumented run completed successfully on
2026-11-05 at 00:14:07 Europe/Paris, compiling and generating all 27 static pages.
The diagnostic preload preserved filesystem behavior: no retries or suppressed
errors were added. The cause of the earlier intermittent EPERM remains unknown.

The final credential-free staged source passed all 114 frontend tests, TypeScript
checking, ESLint and the production build. Root workspace standalone output was
verified at .next/standalone/frontend/server.js. CPU workers are limited to one;
webpackBuildWorker is disabled to compile in-process in restricted environments.
Dependencies were copied and verified from an existing local installation, not
installed from scratch. A clean offline npm ci did not complete; one short-path
attempt was terminated after 120 seconds. Missing cache artifacts and workspace
link permissions remain separate from the successful application compilation.

Production connect-src no longer includes wildcard Supabase project domains or an
unconfigured localhost API fallback. Explicit public API/Supabase origins still
contribute validated origins, including deliberate loopback development builds.
