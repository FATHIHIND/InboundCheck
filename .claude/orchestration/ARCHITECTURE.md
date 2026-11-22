# InboundCheck Engineering OS package

This is the existing project ledger, guards and governance skills, packaged for
portable checkout. Application code, dependencies and deployment settings are outside
this package. Runtime state and machine configuration remain ignored.

## Components and activation

- Four governance skills run in the main session and route to tracked project skills.
- Guard scripts enforce scope, secrets, human approval and one-writer ownership.
- Ledger CLI maintains atomic task state and verifies gate evidence and reviews.
- Gate registry and boundary registry remain authoritative for mechanical completion.
- The Definition of Done is a reviewed project reference.

Checkout does not register executable hooks. No settings.json, settings.local.json,
Git hook installer or global configuration is included. Existing installations keep
their own activation configuration; this package never disables or replaces it.
Before autonomous edits, verify the host actually invokes the existing PreToolUse,
PostToolUse and reviewer lifecycle guards with fail-closed failure handling. Without
verified activation, report enforcement as unavailable and stop autonomous application
edits. Never treat the presence of scripts or a worktree as a security sandbox.
Hook registration or host-specific adaptation requires a separately approved exact
configuration change. No automatic installer is provided.

Specialist agent definitions are not bundled. Verify that the required named reviewers
exist in the executing host with the intended read-only scope before delegation.
A missing reviewer blocks the affected task; do not silently grant tools or fabricate
review events. Codex must not claim Claude lifecycle evidence without an equivalent
verified adapter.

## Approval, state and resume

The human approves a Change Set through the existing ledger approval command.
Agents must never invoke approval or write approval markers or ledger state directly.
The manifest hash pins the approval; edits invalidate it. Commit, push, merge and
deployment permissions remain separate from implementation approval.

Generated state lives only in orchestration/runs/, orchestration/approvals/,
orchestration/ACTIVE_RUN and runtime lock/debug files. None is part of Git packaging.
Resume through ledger status, verify the worktree and active approval, and continue
the first unfinished task. Never overwrite a live run after interruption.

## Verification and evidence limits

Read the project policy at .agent/references/engineering-os.md for development versus
release gates. Mandatory registry gates still apply; a policy description cannot
override a guard denial or manufacture DONE.
Evidence requires successful explicit exit codes and matching before/after artifact
identities. Later failures supersede earlier passes. Unsupported interpreter selections
remain UNKNOWN. npm installation metadata does not attest to manual package-content
tampering; use a clean deterministic install when integrity is uncertain.
Local results are not current remote CI, and prior development results cannot satisfy
a newly required release execution.

The guards inspect command text. They cannot see arbitrary behavior inside scripts,
variables or encoded payloads. Secret scans are pattern based. True isolation requires
a separately configured host sandbox. Live database/RLS behavior is not established
by this package's synthetic tests. Never contact production for local verification.
Do not assume historical Python versions, dependency availability or runtime parity.

## Focused local checks

Run from the verified checkout root:

    node --test .claude/hooks/tests/packaging.test.mjs .claude/hooks/tests/evidence.test.mjs
    node .claude/hooks/tests/selftest.mjs

The self-test uses disposable synthetic repositories and does not execute the commands
it feeds to guards. CLI initialization creates only ignored local runtime state; it
does not approve a run, activate hooks or connect to external services.
