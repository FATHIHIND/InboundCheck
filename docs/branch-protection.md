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

**Supply chain:**
- Every third-party action is pinned to a full, immutable commit SHA, with its release in a trailing comment: `actions/checkout` v4.4.0 and `actions/setup-python` v5.6.0. A moved or hijacked tag therefore can't change what CI runs.
- To update an action, resolve the new release tag to its commit SHA and review the upstream diff. Then update the SHA and the comment together.
- `test_release_gate_regression.py` fails if any `uses:` line isn't pinned to a 40-character SHA.

## What each check proves

**`source-safety`** (Ubuntu, Python 3.11)
- Installs the verification tools only from the CI-tools hash lock (see "CI-tools lock" below).
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
- `pip-audit` and Bandit install only from the CI-tools hash lock, separately from the application's runtime dependencies.

## CI-tools lock

The verification tools (`pglast==8.7`, `pip-audit==2.9.0`, `bandit==1.8.6`) are listed in `ci/requirements-ci-tools.in`. Their full transitive closure is pinned with SHA-256 hashes in `ci/requirements-ci-tools.lock`: 31 packages, including `pip` itself, which `pip-api` needs. None of these tools is in `backend/requirements.txt` or `backend/requirements.lock`, and a regression test enforces that separation.

Both tool-using jobs install with:

~~~text
python -m pip install --require-hashes --only-binary=:all: -r ci/requirements-ci-tools.lock
~~~

So every downloaded file must match a reviewed hash, and nothing is built from source.

The lock was resolved for CPython 3.11 on Linux, which is why both tool jobs use Python 3.11. Each pinned version carries the hashes of every file PyPI publishes for it, across platforms and source distributions. On Linux/CPython 3.11, though, pip selects only `cp311` manylinux or pure-Python wheels, and `--only-binary=:all:` enforces that.

To update the tools, with approval:
1. Edit the `.in` file.
2. Regenerate the lock in an isolated `python:3.11-slim` container, working from the `ci/` directory so the `# via` comments stay stable:

   ~~~text
   pip install pip-tools==7.4.1
   cd ci
   pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url \
       --output-file=requirements-ci-tools.lock requirements-ci-tools.in
   ~~~

   Then restore the hand-written header comment.
3. Review the diff.
4. In a fresh container, confirm that `pip install --require-hashes --only-binary=:all:` and `pip check` succeed.

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

Use an existing reviewed Python environment that has the backend lock installed. Don't source a dotenv file. The migration validator, `pip-audit` and Bandit need the CI-tools lock, installed in a separate verifier environment such as a disposable `python:3.11-slim` container.

~~~text
python scripts/check_release_safety.py
python scripts/safe_backend_tests.py tests/test_release_gate_regression.py -q
python scripts/safe_backend_tests.py -q
# verifier environment (CI-tools lock installed):
python scripts/validate_migration_sources.py
python -m pip_audit --strict --disable-pip --no-deps --require-hashes -r backend/requirements.lock
python -m bandit -r backend/app -ll
~~~

The source-safety check covers the current Git-tracked tree, not past commits or every possible secret format. If a real credential was ever committed, rotate it and review the history separately.

A passing local check is not evidence that hosted GitHub CI ran or that branch protection is active. Confirm both in GitHub.
