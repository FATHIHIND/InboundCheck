# AUTHZ-TRUTH-05 — SNS signing-certificate chain trust: readiness report

Status: local implementation only. Not committed, not deployed, **not wired into message acceptance**.
**Enforcement readiness: BLOCKED.** Genuine AWS chain and identity validation has not been performed.
`certificate_chain_verified` remains `False` everywhere. Nothing in this report claims AWS trust.

## 0. Remediation status of the independent review (F1–F9)

| Finding | Status | What changed | Remaining |
|---|---|---|---|
| F1 chain treated as identity | **Fixed** | Chain validity and identity are separate. Without an `IdentityPolicy` the result is `chain_ok_identity_unverified`, which is never trusted. `trusted` requires `OK` + identity evaluated + pinned anchors. | AWS SAN/EKU/regional constraints still need the genuine capture (see §7). |
| F2 circular anchor pins | **Fixed for the four roots** | The four roots are embedded from Amazon's official repository. Their DER SHA-256 values match the "Self-signed" hashes on the same official page. certifi is no longer read. | Verified against published hashes, not against a signed Amazon manifest. |
| F3 cache safety | **Fixed** | Key binds leaf DER fingerprint, path, anchor-set fingerprint, identity policy, pinned flag and `POLICY_VERSION`. Successes only. Expiry is the earlier of TTL and the earliest notAfter. A hit is refused before the latest notBefore of the covered certificates (review condition 2). Thread lock. | Thread interleaving is not controlled; concurrency tests assert outcome invariants only (see §9). |
| F4 missing tests | **Mostly fixed** | 69 tests (was 21 before review; 59 at the first remediation; 68 after review conditions 1, 2 and 5; 69 after the unrelated future-CA cache test and the exact `len(cache) == 2` assertion). Mutation checks confirm the new regression tests fail on reintroduced flaws (§3). | True cross-signed Amazon variants not available as fixtures (see §9). |
| F5 naive datetime | **Fixed** | Naive `now` raises `ValueError`. | — |
| F6 `issuers[0]` selection | **Fixed** | Candidates are chosen by `verify_directly_issued_by`; a currently valid candidate is preferred. | — |
| F7 unrelated expired certs | **Fixed** | Date checks run only on the leaf and the selected path. | — |
| F8 `FETCH_ERROR` / empty fingerprint | **Fixed** | `FETCH_ERROR` removed. Unexpected errors return `leaf_fingerprint=None`. | — |
| F9 imports | **Fixed** | All imports at module top in the test file. | — |

### 0a. Independent review publication conditions (second remediation)

The independent security review of this Change Set required five conditions before GitHub publication.
Status is shown as of this revision. None of this section establishes AWS trust.

| Condition | Status | Evidence |
|---|---|---|
| C1 Forged `pinned=True` cannot yield trust | **Fixed** | `TrustAnchorSet` no longer accepts a `pinned` argument (`TypeError`). `pinned` is a property that requires a module-private authority, attached only by `load_pinned_trust_anchors()` for the default source list, **and** an exact match with the four official fingerprints. A forged authority on synthetic roots reports `pinned=False` (test `test_synthetic_root_cannot_become_trusted_through_a_forged_authority`). |
| C2 Cache must not replay success before validity | **Fixed** | Cache stores the latest notBefore of the covered certificates. A hit before it is refused and revalidated. Review probe reproduced as a regression test (`test_review_probe_cached_success_is_not_served_before_not_before`). |
| C3 Root fingerprint provenance | **Fixed** | Cross-signed fingerprints were verified from the official PEM files (§2). Prefix-only attributions in the earlier revision were wrong and are corrected. |
| C4 cryptography 50.0.2 evidence | **Qualified pass** | 69/69 SNS tests passed under cryptography 50.0.2 and pytest 9.0.3, on Python 3.12.10, with `--noconftest`. The exact command without `--noconftest` did not run (conftest import failed: PyJWT unavailable). Limitations in §6a. The Python 3.11 runtime remains unverified. |
| C5 Test quality | **Fixed** | Exact status and outcome assertions replace the broad ones. Deterministic concurrency assertions added; interleaving limits documented in §9. |

## 1. Genuine capture provenance (Phase 1): BLOCKED

- No genuine non-production SNS message with a SigningCertURL exists in the repository, the workspace or
  the inbox. The occurrences of `SigningCertURL` are code, tests and documentation only.
- The 03A remediation document (`docs/remediation/AUTHZ_TRUTH_03A_ESP_WEBHOOK_GAPS.md`) records the same blocker.
- Synthetic certificates generated in tests are not AWS evidence and are not used as such.
- No SigningCertURL was fetched by this remediation.

### Owner action required (one non-production test message)

1. In a **non-production** AWS account that you control, create an SNS topic dedicated to testing
   (for example `inboundcheck-sandbox-ses-events`). Do not use the production topic.
2. Subscribe an HTTPS endpoint you control to that topic. Confirm the subscription.
3. Publish one plain test message to the topic (for example the text `inboundcheck capture test`).
4. From your endpoint's logs, copy the raw POST body and the `x-amz-sns-message-type` header of the
   **Notification** message. Do not include access keys, console session data or any other credential.
5. Send the copied body, the topic ARN and the topic's region to the repository owner, and state that the
   topic is non-production.
6. **Approve, explicitly and separately,** one read-only HTTPS GET of the message's `SigningCertURL`.
   That GET is the only network request authorised for this work. Its host must be
   `sns.<region>.amazonaws.com`; anything else will be refused without a request.

Nothing in the capture needs redaction for chain analysis: the certificate is public. The `Message` field
must stay intact because it is covered by the signature.

## 2. Trust anchors — authoritative provenance (F2)

Source: Amazon Trust Services repository, `https://www.amazontrust.com/repository/`.
Retrieved **2026-11-19** over HTTPS (`AmazonRootCA1.pem` … `AmazonRootCA4.pem`, with the repository page used to
read the published hashes). The embedded PEMs are the bytes as retrieved. The fingerprints below were computed from the
DER of those PEMs and compared with the "Self-signed" SHA-256 values printed on the same official page.

| Root | Subject | Serial (hex) | Not after | SHA-256 (DER) | On official page |
|---|---|---|---|---|---|
| Amazon Root CA 1 | CN=Amazon Root CA 1,O=Amazon,C=US | 66c9fcf99bf8c0a39e2f0788a43e696365bca | 2038-01-17 | 8ecde6884f3d87b1125ba31ac3fcb13d7016de7f57cc904fe1cb97c6ae98196e | Yes (Self-signed) |
| Amazon Root CA 2 | CN=Amazon Root CA 2,O=Amazon,C=US | 66c9fd29635869f0a0fe58678f85b26bb8a37 | 2040-05-26 | 1ba5b2aa8c65401a82960118f80bec4f62304d83cec4713a19c39c011ea46db4 | Yes (Self-signed) |
| Amazon Root CA 3 | CN=Amazon Root CA 3,O=Amazon,C=US | 66c9fd5749736663f3b0b9ad9e89e7603f24a | 2040-05-26 | 18ce6cfe7bf14e60b2e347b8dfe868cb31d02ebb3ada271569f50343b46db3a4 | Yes (Self-signed) |
| Amazon Root CA 4 | CN=Amazon Root CA 4,O=Amazon,C=US | 66c9fd7c1bb104c2943e5717b7b2cc81ac10e | 2040-05-26 | e35d28419ed02025cfa69038cd623962458da5c695fbdea3c22b0bfb25897092 | Yes (Self-signed) |

- Each root is self-signed. The official page also lists **cross-signed** certificates for these roots, signed by
  the Starfield Services Root CA G2. Those are **not** trust anchors here, and the loader rejects any
  non-self-signed certificate.

**Verified fingerprints (review condition 3).** On 2026-11-19 the eight PEM files were downloaded from
`https://www.amazontrust.com/repository/` (`AmazonRootCA1–4.pem` and `G2-RootCA1–4.pem`). The DER SHA-256 of each file was
computed with `cryptography` and compared with the values printed on the official page. Two columns are kept separate:

| Root | Self-signed root certificate (trust anchor, pinned) | Cross-signed certificate (issuer: Starfield G2, **not** an anchor) |
|---|---|---|
| Amazon Root CA 1 | `8ecde6884f3d87b1125ba31ac3fcb13d7016de7f57cc904fe1cb97c6ae98196e` | `87dcd4dc74640a322cd205552506d1be64f12596258096544986b4850bc72706` |
| Amazon Root CA 2 | `1ba5b2aa8c65401a82960118f80bec4f62304d83cec4713a19c39c011ea46db4` | `8b358466d66126312120645a5875a6a57e3c81d98476a967604244254eac00f0` |
| Amazon Root CA 3 | `18ce6cfe7bf14e60b2e347b8dfe868cb31d02ebb3ada271569f50343b46db3a4` | `40c826fdb22ba32a2f9db4f94770f72b8b1da9c8ffda7b11e6f27af245c89b5e` |
| Amazon Root CA 4 | `e35d28419ed02025cfa69038cd623962458da5c695fbdea3c22b0bfb25897092` | `543d9b7fc2a6471cd84fca52c2cf6159df83ebfcd88d8b08b5af3f88737f52e6` |

The embedded PEMs in `sns_chain.py` match the downloaded self-signed files (same DER SHA-256). Earlier revisions of
this report attributed `8b3584…` to Root 3 and `40c826…` to Root 4; that was wrong. `8b3584…` is Root 2's cross-signed
certificate, `40c826…` is Root 3's, and Root 4's is `543d9b7f…`. The cross-signed values are documentation only; the
code does not use them.
- The loader fails closed unless there are exactly four distinct, self-signed roots whose DER SHA-256 matches the
  pinned value. Tests cover tampering, a missing root, a duplicate root and a same-name non-self-signed substitute.
- Test anchor sets (`TrustAnchorSet.for_testing`) are never pinned and therefore never `trusted`.
- Limit: the hashes were checked against Amazon's HTTPS-served repository page, not against a separately signed
  manifest. That is the strongest provenance this task could obtain.

**Not yet established:** whether the SNS signing chain ends at one of these roots. That depends on the capture (§1).

## 3. Implementation (logic only; not wired)

`backend/app/services/failover/sns_chain.py`

- **Statuses:** `ok` (chain valid and identity policy evaluated and passed), `chain_ok_identity_unverified`
  (chain valid, no identity evaluated), `missing_intermediate`, `untrusted_root`, `expired`, `not_yet_valid`,
  `host_mismatch`, `policy_error`. `fetch_error` is not part of the contract.
- **Trust:** `ChainResult.trusted` is true only for `ok` with identity evaluated and pinned anchors.
- **Pinned state (C1):** `TrustAnchorSet` takes certificates only. `pinned` is True only for a set produced by
  `load_pinned_trust_anchors()` with the default source list **and** whose fingerprints equal the four official
  values. A set built directly, including one with `pinned=True` (now a `TypeError`), is never pinned.
- **Identity:** `IdentityPolicy` requires at least one expected DNS name. It may also require Extended Key Usage OIDs.
  No AWS-specific SAN or EKU requirement is invented. An unchecked identity is never treated as verified.
- **Path building:** candidates are chosen by signature verification, preferring one valid at `now`. A same-name
  certificate that does not verify is `policy_error`, not a silent skip.
- **Verifier:** `cryptography` `PolicyBuilder` client verifier with `webpki_defaults_ca` for intermediates. The lock
  file pins cryptography 50.0.2; the version actually exercised locally is recorded in §6.
  The leaf extension policy is `permit_all()`; leaf identity is enforced only through `IdentityPolicy`.
- **Key policy:** RSA ≥ 2048 bits and SHA-2 signatures, applied to the leaf and selected path.
- **Cache:** `ValidationCache` (bounded, thread-locked, successes only). Key = policy version, leaf DER fingerprint,
  path fingerprints, anchor-set fingerprints, pinned flag, identity policy. Expiry = min(TTL, earliest notAfter on
  the presented chain). **Not-before (C2):** the entry also records the latest notBefore among the presented
  certificates, because the whole set is valid only from that instant. A hit at any earlier time is refused and
  revalidated. The earliest notBefore would be insufficient: a request between the two start dates would wrongly
  hit. Failures are refused by `put()`.
- **Inputs:** naive `now` → `ValueError`; a raw certificate list → `TypeError` (only a `TrustAnchorSet` is accepted).

`backend/tests/test_sns_chain_validation.py`: **69 tests**, all using synthetic certificates (labelled as non-evidence)
except the anchor tests, which use the four official roots. Ten tests were added for review conditions 1, 2 and 5:
six for the pinned state (`TypeError` on `pinned=`, official roots constructed directly are not pinned, forged
authority on a synthetic root, copied authority on a widened set, the legitimate loader remains pinned, a copied
source list is not pinned), three for the cache not-before boundary (the review probe
`test_review_probe_cached_success_is_not_served_before_not_before`; the case where the intermediate starts later than
the leaf, `test_cache_hit_requires_every_covered_certificate_to_be_valid`; and an unrelated future-dated CA in the
bundle, `test_cache_entry_with_unrelated_future_ca_is_not_served_before_that_ca_not_before`, which checks that the
entry is refused before that CA's notBefore and served after it, with results compared to uncached validation), and
one exact-bound concurrency test. The existing `test_cache_is_bounded_in_entries` now asserts `len(cache) == 2`
exactly (previously `<= 2`).

**Mutation checks for the review conditions** (scratch copy outside the repository; repository untouched):

| Reintroduced flaw | Tests that fail |
|---|---|
| `pinned` without the fingerprint check | `test_synthetic_root_cannot_become_trusted_through_a_forged_authority`, `test_official_roots_plus_a_synthetic_root_cannot_be_pinned_by_copying_the_authority` |
| Cache ignores not-before | `test_review_probe_cached_success_is_not_served_before_not_before`, `test_cache_hit_requires_every_covered_certificate_to_be_valid`, `test_cache_entry_with_unrelated_future_ca_is_not_served_before_that_ca_not_before` (3 failures in the final mutation run) |
| Earliest notBefore instead of latest | the same two cache tests |

**Test evidence (this remediation)**
- Red phase: the first run failed at import, because the new API did not exist.
- Two test-side bugs were found and fixed during green: a "forged" leaf was signed with the intermediate key, and an
  integer was added to a datetime.
- Two production bugs were found by debugging and fixed: `verify_directly_issued_by` raises `InvalidSignature` (not
  `ValueError`) for a wrong-key candidate, and the identity EKU check compared OID objects with dotted strings.
- Mutation testing (scratch copy, repository untouched): reintroducing each unsafe behaviour makes the regression
  tests fail. Two survivors were found (`trusted` ignoring `identity_checked`; the cache failure guard) and new tests
  were added, after which both are caught.

**Not implemented:** `SESWebhookVerifier` is unchanged and does not import this module. No shadow mode. No enforcement.
`certificate_chain_verified` remains `False`.

## 4. Separation of concepts

| Concept | Where it is enforced | Status |
|---|---|---|
| SigningCertURL origin (HTTPS, `sns.<region>.amazonaws.com`, no userinfo, port, query or fragment, region matches topic) | `esp_webhook_service.py` (existing, 03A) | Enforced |
| HTTPS server certificate of the fetch | Client TLS validation of httpx | Not a substitute for signing-chain validation |
| SNS signing-certificate chain | `sns_chain.py` | Logic implemented; not applied to real AWS certificates |
| Leaf identity (SAN, EKU, regional host) | `sns_chain.py` `IdentityPolicy` | Mechanism implemented; **AWS constraints deferred** |
| SNS message signature | `esp_webhook_service.py` (existing) | Enforced |

## 5. Shadow mode (Phase 4): NOT IMPLEMENTED (gated)

Shadow mode is not wired into the production path because the genuine chain is not yet validated locally.
When unblocked it must:

- compute the chain status for each accepted SNS message without changing the acceptance decision;
- keep `certificate_chain_verified` at `False`;
- emit only `chain_status`, `leaf_fingerprint`, `aws_region` and `validation_timestamp`;
- never log message bodies, SubscribeURL tokens, recipient data, secrets or certificate contents.

## 6. Runtime compatibility (Phase 6): PARTIAL

| Component | Required (lock file) | Local verification |
|---|---|---|
| Python | 3.11 | **Not verified at 3.11.** The pinned-version run used Python 3.12.10 (§6a). Local 3.14.3 was used for the cryptography 46.0.7 runs. The `Python311` folder has no interpreter. Grammar only: `ast.parse(feature_version=(3, 11))` passes for both files. |
| cryptography | 50.0.2 | **Verified at 50.0.2 on Python 3.12.10 only**, with `--noconftest` (§6a). Not verified on 3.11. |
| fastapi | 0.162.0 | 0.162.0 |
| starlette | 1.3.1 | 1.3.1 |
| httpx | 0.27.0 | 0.27.0 |
| certifi | 2026.10.23 | 2026.10.23 (no longer used by `sns_chain.py`) |

Code-level check only: `ast.parse(..., feature_version=(3, 11))` on the module and test file. This is not a runtime test.
No dependency was installed or changed. Production compatibility is **not** claimed.

### 6a. Condition 4: qualified pinned-version evidence

**Result: the SNS test file passed 69/69 under the pinned cryptography and pytest versions, with one qualification:
the run used `--noconftest`.** The exact command without that flag did not run. This record does not claim that
the original command passed.

**Pinned-version run**

| Item | Value |
|---|---|
| Authorization | Human-approved run `authz05-dep-verify-crypto50` (`ledger.mjs approve`, `allow_dependency_changes: true`, `allowed_paths: backend/tests/test_sns_chain_validation.py`) |
| Environment | Throwaway venv outside the repository and the worktree: `InboundCheck\venvs\authz05-crypto50-py312` |
| Python | 3.12.10 |
| cryptography | 50.0.2 (verified with `importlib` inside the venv) |
| pytest | 9.0.3 (verified inside the venv) |
| Installed | `pip install cryptography==50.0.2 pytest==9.0.3`, plus transitive packages resolved by pip: `cffi 2.1.1`, `pycparser 3.12`, `pluggy 1.7.0`, `packaging 26.3`, `iniconfig 2.3.1`, `colorama 0.4.6`, `pygments 2.21.0` |
| Command | from `backend/` in the worktree: `python -m pytest tests/test_sns_chain_validation.py -p no:cacheprovider -q --no-header --noconftest` with `PYTHONDONTWRITEBYTECODE=1` |
| Result | **69 passed**, 69 collected, 1 warning |

**Exact command that did not run.** Without `--noconftest`, the run failed during collection:
`ImportError while loading conftest …\tests\conftest.py` → `ModuleNotFoundError: No module named 'jwt'`. The
conftest imports PyJWT and `app.core.config`, which need the application's full pinned dependency set, and that set was
not installed. This failure is recorded as-is.

**Why `--noconftest` does not change the tested behaviour (independent review):**
- `tests/conftest.py` defines no fixtures and no autouse hooks. Its only effect is to set
  `settings.SUPABASE_JWT_SECRET`.
- The SNS test file's imports are the standard library, `pytest`, `cryptography`, and
  `app.services.failover.sns_chain`. Its only fixtures are the local `hierarchy` fixture and pytest's built-in
  `monkeypatch`. It does not reference `settings`, environment variables, JWT, Supabase or asyncio.
- `sns_chain.py` imports only the standard library and `cryptography`.
- The same 69 tests also passed earlier under Python 3.14.3 with the conftest loaded, using cryptography 46.0.7.

**Limitations that remain (must stay documented)**
1. The exact command was not run. The result above is for the `--noconftest` variant only.
2. Python 3.12.10 was used. The lock file targets Python 3.11, and the 3.11 runtime is **not verified**.
3. `pytest-asyncio` is not installed in the venv. `pytest.ini` sets `asyncio_mode = auto`, so pytest printed
   `PytestConfigWarning: Unknown config option: asyncio_mode`. The SNS suite has no async tests, so the result is not
   affected. The lock pins `pytest-asyncio==1.3.0`; the venv does not match it.
4. Transitive dependencies were resolved by pip, not from the project lock file.
5. The ESP and failover regression suites were **not** run under cryptography 50.0.2. The 192-test regression result in
   this section comes from the earlier cryptography 46.0.7 environment.

**Earlier attempts, for the record.** A first attempt to install the pinned versions into a venv was blocked by the
repository guard (`allow_dependency_changes is not granted`). The guard was not bypassed. The human approval run above
was then created and approved by a human, and the install was performed under that approval.

**Earlier regression evidence (cryptography 46.0.7, Python 3.14.3, conftest loaded).** `tests/test_esp_contract_klaviyo_ses.py`,
`tests/test_esp_webhook_integrity.py`, `tests/test_esp_authz_truth_03a.py`, `tests/test_failover_webhooks.py` and
`tests/test_sns_chain_validation.py` together: **192 passed**, 24 warnings from unrelated deprecations.

## 7. Enforcement readiness (Phase 5): BLOCKED

Enforcement must not be enabled until **all** of the following are true:

1. The owner supplies a genuine non-production capture (§1) and approves the single SigningCertURL GET.
2. The chain in that capture validates under `validate_sns_signing_chain` to a pinned Amazon root.
3. The AWS leaf constraints (SAN layout, Extended Key Usage, regional host) are derived from that capture and supplied
   as an `IdentityPolicy`, with tests that reject a variant of each.
4. Negative tests pass against the genuine chain: missing intermediate, untrusted root, expired, not yet valid,
   wrong region, invalid signature.
5. Shadow mode runs against non-production traffic and reports zero `ok` results on forged messages, with no change
   to acceptance.
6. The Python 3.11 runtime is verified against the lock file.
7. The owner gives explicit written approval in a separate task.

**Rollback plan (for when enforcement is later enabled):** enforcement is controlled by a single configuration
switch. Turning it off restores the current behaviour (signature and origin checks only). No data migration is
involved. A failing enforcement change must be reverted by disabling the switch, not by editing the verifier under
pressure.

## 8. Owner approval required

- **Approve or decline** the single non-production SNS test message (§1) and the single read-only GET of its
  SigningCertURL.
- **Confirm** that the production SES webhook configuration sets `SES_SNS_TOPIC_ARN` (03A compatibility note: without
  it, SES webhooks fail closed).
- **Decide** when the enforcement task should start. It is not started by this report.

## 9. Remaining limitations

- Genuine AWS chain and identity validation: **unverified** (BLOCKED on §1).
- AWS leaf SAN, EKU and regional-host constraints: **deferred**; the mechanism exists but no AWS policy is set.
- Real Amazon cross-signed variants are not available as fixtures; multi-candidate selection is tested with
  synthetic same-name certificates only.
- Thread safety of the cache relies on a lock. Thread interleaving is **not** controlled. The concurrency tests use a
  barrier to start threads together and assert outcome invariants that hold under every interleaving: no exception,
  every call returns the same success, one cache entry for one key, and an exact final size of 16 for 64 inserts into a
  16-entry bound. They do not prove the absence of a race that only a specific schedule would expose.
- Cache hits are checked against certificate validity only at `now`. A request with a clock earlier than the
  notBefore boundary is refused. A clock that moves forward past notAfter is handled by the expiry check.
- SHA-1 SignatureVersion 1 messages remain accepted by the existing message-signature code.
- Python 3.11 runtime not verified (no interpreter installed).
- Shadow mode not implemented; not wired into acceptance.
