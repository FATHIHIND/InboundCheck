# Release checks and branch protection

The workflow in `.github/workflows/release-gates.yml` checks source changes. It doesn't deploy anything, run migration SQL, connect to Supabase, or need repository secrets. This document proposes GitHub settings; no branch rule has been changed.

## Required checks

Once the workflow has run on `main`, a repository administrator should require these exact job names in the branch protection rule or ruleset:

- `source-safety`
- `backend-safe`
- `backend-linux-runtime`
- `dependency-security`

The frontend job (`frontend-checks`) and the npm lock audit are added later, with the frontend slice. Add `frontend-checks` to the required list only after that job exists and has run on `main`. Requiring a check that never reports blocks every merge.

Also:
- Require pull requests and at least one independent review.
- Require review conversations to be resolved and checks to be up to date before merge.
- Disable force pushes and branch deletion.
- Apply the rule to administrators where repository policy permits.
- Don't add an automatic bypass for this workflow.

A red dependency audit is a release blocker to investigate. It's not a reason to add `continue-on-error` or to ignore advisories globally.

Every job runs on pull requests and pushes with no path filters, so a required check is never silently skipped. Tokens have only `contents: read`, and checkout doesn't persist credentials. There is no privileged pull-request event, deployment job, environment approval, OIDC permission, or use of production settings.

## What each check proves

**`source-safety`**
- Checks Git-tracked paths and content for dotenv or credential files and for some recognisable credential formats. It reports file names and rule names, never the matched values.
- Checks that every direct requirement in `backend/requirements.txt` is pinned at the same version in the hash lock, and that every lock entry is hashed.
- Parses each canonical migration with `pglast==8.7`. The manifest (`CANONICAL_MIGRATIONS` in `scripts/reconcile_migration_ledger.py`) is read with the Python AST and literal evaluation; the module is never imported. The physical files in `supabase/migrations/` must match the ordered, unique manifest exactly, so a migration ID and its SQL file must be added together.
- This is source validation only. It doesn't prove a migration applies, that the database ledger matches, that permissions or rollback are safe, or what PL/pgSQL function bodies mean. Those need a separately authorised review of each environment.
- The manifest tracks the local migration inventory, not any remote ledger, and the two currently differ. As of this change, production's ledger has 30 rows: the first 28 local migrations plus `20261107000001` and `20261107000002`, whose SQL files aren't in the repository yet. Three local migrations (`20261029000001`, `20261031000001`, `20261031000002`) have no production ledger row. Don't run `scripts/reconcile_migration_ledger.py` against any environment until the migration slices resolve this.

**`backend-safe`** (Windows, Python 3.12)
- Installs the complete backend hash lock with `--require-hashes` and runs `pip check`.
- Then runs `python scripts/safe_backend_tests.py -q`. The runner clears application settings, refuses to read project dotenv files, and blocks external network and DNS through audit hooks. It runs from an empty working directory, allows only reviewed subprocesses, and always excludes the live staging lifecycle suite.
- These are local tests, not live database integration tests.

**`backend-linux-runtime`** (Ubuntu, Python 3.11)
- Matches `backend/Dockerfile` (`python:3.11-slim`) and uses the same hash-required install of the lock plus the direct requirements.
- Fails closed if a Linux-only dependency, such as `uvloop` (pulled in through `uvicorn[standard]`), lacks a reviewed pin or hash.

**`dependency-security`** (Ubuntu, Python 3.11)
- Runs `pip-audit` on the backend lock as it resolves for the Linux/Python 3.11 runtime, including Linux-only packages such as `uvloop`. Windows-only entries such as `colorama` aren't audited, because the lock's markers exclude them on Linux.
- Runs Bandit on the backend application source (medium and high severity).
- `pip-audit` queries an advisory service from CI, and a service error fails the check. Bandit runs offline.
- The audit tools are installed separately from the application's runtime dependencies.

## Backend lock

`backend/requirements.txt` is the source of direct dependencies. `backend/requirements.lock` is a universal lock: every package is pinned and SHA-256-hashed, with environment markers for Windows, Linux and macOS on CPython 3.11 and 3.12. The Linux/Python 3.11 hash-required install is proven by the Docker build. The Windows/Python 3.12 install is proven by the `backend-safe` job on its first run. Both Docker and CI install with:

~~~text
pip install --require-hashes -r requirements.lock -r requirements.txt
~~~

The Railway worker image is built this way, so a hash mismatch fails the build. The API service is currently built separately, by Railpack from `requirements.txt`, and doesn't use the lock. Treat that as a known gap until the API build is moved to the Dockerfile.

To update a dependency, with approval:
1. Edit the direct requirements.
2. Regenerate the full hash lock for every target platform.
3. Review the transitive diff.
4. Run the safe suite and the audit checks.

A lock freezes versions; it doesn't make old dependencies secure.

## Local commands

Use an existing reviewed Python environment that has the backend lock installed. Don't source a dotenv file.

~~~text
python scripts/check_release_safety.py
python scripts/validate_migration_sources.py      # requires pglast==8.7 in the verifier environment
python scripts/safe_backend_tests.py tests/test_release_gate_regression.py -q
python scripts/safe_backend_tests.py -q
~~~

The source-safety check covers the current Git-tracked tree, not past commits or every possible secret format. If a real credential was ever committed, rotate it and review the history separately.

A passing local check is not evidence that hosted GitHub CI ran or that branch protection is active. Confirm both in GitHub.
