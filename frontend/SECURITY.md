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
registry metadata, retaining recorded integrity values. On 2026-11-05 the missing
Darwin-only fsevents 2.3.3 metadata was retrieved from the official npm registry;
the downloaded tarball's SHA-512 matched its published integrity. Its optional,
macOS-only entry is now locked, without changing any existing package version.
Regression tests require that entry and check that every named optional dependency
resolves within the workspace lock. This repairs the known optional-entry gap;
it is NOT proof of a complete clean installation on Windows, Linux or macOS.

A fresh online root npm ci --ignore-scripts in an isolated, credential-free source
copy still failed on EPERM when creating the npm workspace symlink. No permission
bypass or non-workspace installation is counted as success. Clean installation
must still be verified in an environment that permits normal workspace links.
The prior offline dry-run was not sufficient evidence of install reproducibility.

The current npm audit result also reports affected dependency versions, including
high/critical advisories in the Next.js 14.2.35 tree. Applicability to a particular
route or deployment is not established by a version audit. Do not use audit fix
--force to migrate frameworks without compatibility, authentication and build
validation; no such upgrade or advisory suppression was performed here.

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
attempt was terminated after 120 seconds. That historical cache limitation is not
proof of a current missing artifact after subsequent registry access. The fresh
online attempt still fails on workspace-link permissions, independently of the
successful application compilation.

Production connect-src no longer includes wildcard Supabase project domains or an
unconfigured localhost API fallback. Explicit public API/Supabase origins still
contribute validated origins, including deliberate loopback development builds.


## Local dependency remediation (2026-11-05; not release approval)

The frontend now pins Next 16.4.5, React/React DOM 19.3.1, eslint-config-next 16.4.5 and ESLint 10.14.0. The Next 16 migration awaits request cookies, uses ESLint flat configuration instead of removed next lint, moves outputFileTracingRoot to its supported top-level location and explicitly retains the webpack production builder. Static hydration CSP concessions documented above remain unchanged.

The regenerated npm lock retains the verified optional fsevents 2.3.3 entry and its exact registry integrity. A new audit reports zero critical/high findings but is NOT clean: GHSA-g3hv-75wg-m249 remains in minimatch 10.2.6 required by current tooling (10 propagated moderate records). The published fix is 11.0.1, outside those parent ranges. No override, force fix, downgrade to EOL tools, or advisory suppression was applied. Plugin peer declarations also cause npm to retain ESLint 9.39.5 transitively; this EOL tool copy is a compatibility limitation, not production runtime code.

An isolated clean-install/test/build investigation is recorded in the agent frontend-security-report.md; do not treat dependency version changes alone as proof of install/build success or live authorization behavior. No deployment, hosted setting, SQL or production operation is authorized by these changes.


### Scope repair (2026-11-05)

The incidental threeui/framer-motion/Supabase direct upgrades were rolled back using temporary exact manifest constraints and two successful npm --package-lock-only generations. The final manifest retains its original ranges; the lock resolves @designcodeio/threeui 1.1.0, framer-motion 13.1.1, @supabase/ssr 0.12.4 and @supabase/supabase-js 2.112.3. Registry metadata confirms their resolved URLs and integrity. The refreshed audit remains 0 critical / 0 high / 10 moderate; 11 cheap lock/config regressions pass. Full runtime/compiler validation is still not established.
