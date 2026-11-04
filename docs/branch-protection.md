# Release checks and branch protection

The workflow in `.github/workflows/release-gates.yml` verifies source changes. It does not deploy, run migration SQL, connect to Supabase, or require repository secrets. This document proposes GitHub settings; no branch rule has been changed.

## Required checks

After the workflow has run on the intended default branch, a repository administrator should require these exact job names in the branch protection rule or ruleset:

- `source-safety`
- `backend-safe`
- `backend-linux-runtime`
- `frontend-checks`
- `dependency-security`

Require pull requests, at least one independent review, resolution of review conversations, and up-to-date checks before merge. Disable force pushes and branch deletion. Apply the rule to administrators where repository policy permits. Do not add an automatic bypass for this workflow. A red dependency audit is a release blocker to investigate, not a reason to add `continue-on-error` or ignore advisories globally.

All jobs run on pull requests and pushes without path filters, so a required check is not silently skipped. Tokens have only `contents: read` and checkout does not persist credentials. There is no privileged pull-request event, deployment job, environment approval, OIDC permission, or use of production settings.

## What each check proves

`source-safety` checks Git-tracked paths and content for dotenv/credential files and selected recognizable credential formats, checks that backend requirements match the hash lock, and parses each canonical migration with `pglast==8.7`. The manifest is read with Python AST and literal evaluation; the reconciliation module is never imported. The physical file inventory must match the ordered, unique manifest exactly. The count is derived from the current manifest, not a fixed number.

SQL parsing is SOURCE validation only. It does not prove migration applicability, ledger parity, permissions, rollback safety, or PL/pgSQL body semantics. It never executes the generated reconciliation documents or SQL. Those require a separately authorized environment-specific review.

`backend-safe` installs the complete backend hash lock, runs `pip check`, then invokes `python scripts/safe_backend_tests.py -q`. The existing runner clears application settings, denies project dotenv reads and external network/DNS, runs from an empty directory, and excludes the live staging lifecycle suite. Its explicit reviewed-subprocess allowlist remains part of the safety boundary. These are local tests, not live database integration tests.

`backend-linux-runtime` targets Linux/Python 3.11, matching the Docker runtime, and uses the same mandatory-hash install with both lock and direct requirements. This checks direct and transitive dependency extras and fails closed when a platform-specific dependency is missing. The transitive FastAPI extra gap described below remains unresolved offline; this check must not be bypassed.

`frontend-checks` uses Node 24, a root-workspace `npm ci --ignore-scripts`, and the frontend workspace's lint, typecheck, test and build scripts. No production credentials or environment files should be supplied to make these pass. Installation lifecycle scripts are disabled; if a dependency later needs a native build, review and allow that narrow step rather than enabling every dependency's lifecycle scripts.

`dependency-security` runs pip-audit on the complete backend lock, Bandit on backend application source (medium/high severity), and npm audit on the complete root workspace lock (high/critical severity). These CI tools use advisory/package services on a future CI run. Advisory service errors fail the check. They were not queried during the offline local implementation. The audit tools are pinned separately from application runtime dependencies.

## Backend lock scope and updates

`backend/requirements.txt` is the direct dependency source. Its Uvicorn requirement now uses `uvicorn==0.30.1` rather than the standard extra; the version is unchanged. `backend/requirements.lock` was generated with uv 0.13.1 from cached registry metadata and real SHA256 hashes:

~~~powershell
uv pip compile backend/requirements.txt --offline --generate-hashes --output-file backend/requirements.lock
~~~

This resolution was generated and regenerated offline for CPython 3.12 on Windows, with real cached SHA256 hashes and no dependency version changes. A Windows hash-required dry run with both requirement files succeeds without modifying the environment. The default dependency version/Python constraints are compatible with Linux 3.11 and 3.12, but that alone is not a complete closure proof: the metadata walk must propagate extras requested by dependencies, not just extras named by direct requirements.

### Portable server choice and remaining packaging constraint

The backend source has no imports of uvloop or httptools. Docker now explicitly selects Uvicorn's supported `--loop asyncio --http h11` runtime while retaining Python 3.11 and Uvicorn 0.30.1. This uses the standard-library event loop and h11 HTTP implementation consistently across platforms, rather than auto-selecting uvloop/httptools when installed. It may reduce peak throughput compared with native extensions; no performance benchmark was run. CLI and isolated Config regression tests verify that the installed Uvicorn accepts these choices without importing the application or starting a server.

Removing the direct standard extra does NOT remove every packaging request for it. Cached METADATA shows that FastAPI 0.111.0 requires `uvicorn[standard]>=0.12.0`, and its locked fastapi-cli dependency also requires `uvicorn[standard]>=0.15.0`. Those transitive extras still activate uvloop on Linux. The corrected metadata walker propagates dependency extras and identifies this missing Linux lock entry under both Python 3.11 and 3.12. There is no cached uvloop registry metadata or distribution from which to obtain reviewed hashes. Changing the FastAPI distribution/version, bypassing dependency resolution with --no-deps, or fabricating hashes was not authorized and was not done.

Docker and both backend CI jobs continue to install BOTH requirements.lock and requirements.txt with --require-hashes. This deliberately retains fail-closed validation of the complete declared closure; the portable runtime correction alone does not make the Linux package install ready. Resolving the remaining gap requires either authorized uvloop metadata/artifacts and a reviewed cross-platform lock refresh, or an explicitly approved change to the FastAPI packaging dependency after verifying its compatibility. Do not remove the Linux job or weaken hashes to get a green result.

Linux artifact/hash installation remains unverified independently of that known closure gap. Earlier offline cross-target dry runs for Python 3.11 and 3.12 stopped because cffi==2.1.1 Linux artifacts/metadata required a registry download; universal/Linux compile attempts also lacked cryptography/pydantic-core cache coverage. These were cache availability failures, not proof of incompatible locked versions. No Docker build or Linux runtime execution was performed, and no artifact fetch was repeated during the final source correction.

The local environment and package cache do not contain pip-audit 2.9.0, so its CLI flag combination could not be independently exercised offline. A cache-only dry run confirmed this access limit; no scanner or advisory request was run. The future CI invocation retains strict, no-deps, require-hashes and disable-pip options; verify the pinned tool on its first CI run rather than claiming a locally verified audit.

For an approved dependency update, edit the direct requirements, regenerate the full hash lock, inspect the transitive diff, and run the safe suite and audit checks. A generated lock freezes versions; it does not make old dependencies secure. Existing pinned packages may fail a future advisory check and need a separately reviewed upgrade.

## Local commands

Use the existing reviewed Python environment. Do not source a dotenv file.

~~~text
python scripts/check_release_safety.py
python scripts/validate_migration_sources.py
python scripts/safe_backend_tests.py tests/test_release_gate_regression.py -q
python scripts/safe_backend_tests.py -q
npm run lint --workspace frontend
npm run typecheck --workspace frontend
npm run test --workspace frontend
npm run build --workspace frontend
~~~

The migration verifier requires pglast 8.7 in the verifier environment, not in application requirements. Source safety reports filenames and rule identifiers, never matched credential values. It checks the current Git-tracked tree, not historical commits or every possible secret format. If a real credential was ever committed, rotate it and review history separately.

A successful local source check is not evidence that hosted GitHub CI ran or that branch protection is active. Confirm both in GitHub after the user authorizes publishing the patch.
