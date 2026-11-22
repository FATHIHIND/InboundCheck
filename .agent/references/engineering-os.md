# Engineering OS execution policy

## Authority and enforcement
Honor the current owner's explicit scope and permissions, project safety requirements,
and approved Change Set. Generic skill examples do not grant permissions. Runtime
guards remain fail-closed: a denial is a blocker, never permission to disable a hook.
Conversation approval must never be converted by an agent into a human approval marker.
Claude hook evidence is not automatically available in Codex. Without verified equivalent
enforcement, report completion as unverified rather than inventing ledger evidence.

## Route and resume
Confirm the exact worktree root, branch, HEAD and initial status before editing.
Preserve every pre-existing change, including ignored local governance state.
Use one primary builder and only skills relevant to the request. LOW means bounded
documentation/tests; MEDIUM means ordinary application behavior; HIGH includes auth,
billing, tenant permissions, secrets, webhooks, security controls and production.
One independent reviewer is mandatory for HIGH; retain any additional reviewers required
by the existing gate registry. One writer owns a file at a time; serialize overlapping tasks.
Resume from actual run status and approvals, not conversation summaries. An interruption
does not approve, complete, close, or restart an existing run. Check changed inputs before
reusing evidence. Stop the affected task for scope drift, hook denial, missing approval,
unresolved security findings or unavailable mandatory gates; continue independent authorized work.

## Evidence
Use the existing ledger; store no duplicate logs. Each result needs exact command,
exit code, execution directory, artifact HEAD and content hashes, affected files,
dependency hashes and interpreter/OS identity. Missing fields make evidence UNKNOWN.
The current conservative implementation hashes repository inputs, including untracked
nonignored files, plus the gate registry. Any changed hash or environment invalidates it.
It may rerun more than strictly necessary; never infer an unrecorded dependency is unchanged.
Record failures and limitations; a scan without findings is not proof of security.
Custom Python paths/version selectors and execution wrappers remain UNKNOWN until their
actual interpreter can be fingerprinted; default environment proof cannot qualify them.
Installed npm lock metadata is fingerprinted, not every installed package byte. Manual
node_modules tampering is not attested: perform a clean deterministic install when integrity
is uncertain. Never reuse results across an unverified environment.
Never represent local evidence as current remote CI. Release checks must execute for
the exact release artifact and release attempt, even when development evidence is reusable.

## Verification levels
Development: focused tests matching behavior and affected trust boundaries, plus scope
and secret checks. Governance-only work uses the synthetic Node harness; no unrelated
backend/frontend suite is required for this instruction-only scope.
The existing ledger gate registry still controls mechanical DONE. If it requires extra
gates, satisfy them or report BLOCKED; this policy does not bypass or reconfigure it.
Release: all mandatory project/release gates, independent security review where required,
current CI, approval, runtime parity and rollback readiness. No release gate is waived by
task size, token budget, or a previous pass. Implementation, publication, merge and
deployment permissions are distinct.

## Context and decisions
Load skill metadata first, then only selected instructions and needed references.
Reuse settled decisions and verified checkpoints. Return commands/counts and concise
findings instead of full logs. Avoid duplicate investigations, agents and automatic hooks.
Use existing Grill Me for one unresolved material decision with a recommended default.
Skip interviews for clear approved changes. Never infer deployment or security approval.

## Definition of Done
Use the existing project reference at `.claude/references/definition-of-done.md`.
If absent in a checkout, STOP the affected completion claim; do not fabricate its contents.
Do not modify user-level Codex files to repair a project reference without exact-file approval.
