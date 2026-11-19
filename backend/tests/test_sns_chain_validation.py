"""
AUTHZ-TRUTH-05: SNS signing-certificate chain validation logic (remediation of review findings F1-F9).

IMPORTANT: every certificate built in this module is SYNTHETIC. It is generated during the test run to exercise the
validator's logic and is NOT Amazon evidence. The only Amazon material used is the four official Amazon Root CA
certificates embedded in sns_chain.py; they are checked here against fingerprints typed in from Amazon's official
repository page, independently of the code under test.

Genuine AWS chain and identity validation is BLOCKED until a real, non-production SigningCertURL capture exists
(see docs/remediation/AUTHZ_TRUTH_05_SNS_CHAIN_READINESS.md). No network access is performed by these tests.
"""

import datetime as dt
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.services.failover import sns_chain as chain
from app.services.failover.sns_chain import (
    ChainResult,
    ChainStatus,
    IdentityPolicy,
    TrustAnchorError,
    TrustAnchorSet,
    ValidationCache,
    load_pinned_trust_anchors,
    validate_sns_signing_chain,
    validate_sns_signing_chain_cached,
)

NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)
DAY = dt.timedelta(days=1)
SYNTH_NAME = "sns.synthetic-east.test.invalid"
SYNTH_OTHER = "sns.synthetic-west.test.invalid"

# SHA-256 of the DER certificate, typed in from Amazon's official repository page
# (https://www.amazontrust.com/repository/, "Self-signed" rows). Independent of sns_chain.py.
OFFICIAL_SELF_SIGNED_SHA256 = {
    "CN=Amazon Root CA 1,O=Amazon,C=US": "8ecde6884f3d87b1125ba31ac3fcb13d7016de7f57cc904fe1cb97c6ae98196e",
    "CN=Amazon Root CA 2,O=Amazon,C=US": "1ba5b2aa8c65401a82960118f80bec4f62304d83cec4713a19c39c011ea46db4",
    "CN=Amazon Root CA 3,O=Amazon,C=US": "18ce6cfe7bf14e60b2e347b8dfe868cb31d02ebb3ada271569f50343b46db3a4",
    "CN=Amazon Root CA 4,O=Amazon,C=US": "e35d28419ed02025cfa69038cd623962458da5c695fbdea3c22b0bfb25897092",
}


# ---------------------------------------------------------------------------
# Synthetic certificate helpers (NOT AWS evidence)
# ---------------------------------------------------------------------------

def _key(bits=2048):
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _name(cn):
    return x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Synthetic Test"),
    ])


def _cert(subject_cn, subject_key, issuer_cn, issuer_key, *, ca, not_before=NOW - 30 * DAY,
          not_after=NOW + 365 * DAY, hash_alg=hashes.SHA256(), san_dns=None, eku=None):
    b = (
        x509.CertificateBuilder()
        .subject_name(_name(subject_cn))
        .issuer_name(_name(issuer_cn))
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if ca:
        b = b.add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
        ), critical=True)
    if san_dns is not None:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in san_dns]), critical=False)
    if eku is not None:
        b = b.add_extension(x509.ExtendedKeyUsage(eku), critical=False)
    return b.sign(issuer_key, hash_alg)


@pytest.fixture()
def hierarchy():
    root_key, inter_key, leaf_key = _key(), _key(), _key()
    root = _cert("Synthetic Root", root_key, "Synthetic Root", root_key, ca=True)
    inter = _cert("Synthetic Intermediate", inter_key, "Synthetic Root", root_key, ca=True)
    leaf = _cert("Synthetic Leaf", leaf_key, "Synthetic Intermediate", inter_key, ca=False, san_dns=[SYNTH_NAME])
    return SimpleNamespace(root_key=root_key, inter_key=inter_key, leaf_key=leaf_key,
                           root=root, inter=inter, leaf=leaf)


def _anchors(*certs):
    return TrustAnchorSet.for_testing(list(certs))


def _identity(*names, eku=None):
    return IdentityPolicy(expected_dns_names=frozenset(names), required_extended_key_usage=eku)


def _fp(cert):
    return cert.fingerprint(hashes.SHA256()).hex()


# ---------------------------------------------------------------------------
# A. Chain validity without identity: a valid chain is NOT identity (F1)
# ---------------------------------------------------------------------------

def test_complete_chain_without_identity_is_chain_ok_identity_unverified(hierarchy):
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED
    assert r.identity_checked is False
    assert r.trusted is False
    assert r.leaf_fingerprint == _fp(hierarchy.leaf)


def test_arbitrary_leaf_with_valid_chain_and_no_identity_is_never_trusted(hierarchy):
    arbitrary = _cert("attacker.test.invalid", hierarchy.leaf_key, "Synthetic Intermediate",
                      hierarchy.inter_key, ca=False, san_dns=["attacker.test.invalid"])
    r = validate_sns_signing_chain(arbitrary, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED
    assert r.trusted is False


def test_chain_only_state_is_not_the_identity_verified_state(hierarchy):
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is not ChainStatus.OK
    assert r.trusted is False


def test_anchor_with_the_same_name_but_another_key_is_rejected(hierarchy):
    other_key = _key()
    other_root = _cert("Synthetic Root", other_key, "Synthetic Root", other_key, ca=True)
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(other_root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR
    assert r.trusted is False


# ---------------------------------------------------------------------------
# B. Identity (F1): explicit, required, never implied
# ---------------------------------------------------------------------------

def test_matching_identity_gives_ok_but_is_not_trusted_without_pinned_anchors(hierarchy):
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW,
                                   identity=_identity(SYNTH_NAME))
    assert r.status is ChainStatus.OK
    assert r.identity_checked is True
    assert r.trusted is False


def test_wrong_regional_hostname_is_rejected_as_host_mismatch(hierarchy):
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW,
                                   identity=_identity(SYNTH_OTHER))
    assert r.status is ChainStatus.HOST_MISMATCH
    assert r.trusted is False


def test_leaf_without_san_is_rejected_when_identity_is_required(hierarchy):
    no_san = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False)
    r = validate_sns_signing_chain(no_san, [hierarchy.inter], _anchors(hierarchy.root), now=NOW,
                                   identity=_identity(SYNTH_NAME))
    assert r.status is ChainStatus.HOST_MISMATCH
    assert r.trusted is False


def test_required_extended_key_usage_missing_is_rejected(hierarchy):
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW,
                                   identity=_identity(SYNTH_NAME, eku=(ExtendedKeyUsageOID.CLIENT_AUTH,)))
    assert r.status is ChainStatus.POLICY_ERROR
    assert r.trusted is False


def test_required_extended_key_usage_present_is_accepted(hierarchy):
    leaf = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                 san_dns=[SYNTH_NAME], eku=[ExtendedKeyUsageOID.CLIENT_AUTH])
    r = validate_sns_signing_chain(leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW,
                                   identity=_identity(SYNTH_NAME, eku=(ExtendedKeyUsageOID.CLIENT_AUTH,)))
    assert r.status is ChainStatus.OK


def test_identity_policy_without_names_is_refused_at_construction():
    with pytest.raises(ValueError):
        IdentityPolicy(expected_dns_names=frozenset())


def test_ok_status_without_an_evaluated_identity_is_never_trusted_even_with_pinned_anchors():
    assert ChainResult(ChainStatus.OK, "f", identity_checked=False, anchors_pinned=True).trusted is False


def test_a_chain_only_result_cannot_be_consumed_as_identity_verification():
    chain_only = ChainResult(ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED, "f", identity_checked=False)
    assert chain_only.trusted is False
    assert chain_only.identity_checked is False


def test_trusted_requires_pinned_anchors_and_ok_status():
    assert ChainResult(ChainStatus.OK, "f", identity_checked=True, anchors_pinned=False).trusted is False
    assert ChainResult(ChainStatus.OK, "f", identity_checked=True, anchors_pinned=True).trusted is True
    assert ChainResult(ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED, "f", identity_checked=False,
                       anchors_pinned=True).trusted is False


# ---------------------------------------------------------------------------
# C. Path validation: each negative case has its own status
# ---------------------------------------------------------------------------

def test_missing_intermediate_is_reported(hierarchy):
    r = validate_sns_signing_chain(hierarchy.leaf, [], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.MISSING_INTERMEDIATE


def test_fully_supplied_chain_to_an_unpinned_root_is_untrusted_root(hierarchy):
    unrelated_key = _key()
    unrelated = _cert("Unrelated Root", unrelated_key, "Unrelated Root", unrelated_key, ca=True)
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter, hierarchy.root], _anchors(unrelated), now=NOW)
    assert r.status is ChainStatus.UNTRUSTED_ROOT


def test_self_signed_leaf_is_untrusted_root(hierarchy):
    self_key = _key()
    self_signed = _cert("Self Signed", self_key, "Self Signed", self_key, ca=False)
    r = validate_sns_signing_chain(self_signed, [], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.UNTRUSTED_ROOT


def test_expired_leaf_is_expired(hierarchy):
    expired = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                    not_before=NOW - 400 * DAY, not_after=NOW - 1 * DAY, san_dns=[SYNTH_NAME])
    r = validate_sns_signing_chain(expired, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.EXPIRED


def test_expired_intermediate_on_the_path_is_expired(hierarchy):
    expired_inter = _cert("Synthetic Intermediate", hierarchy.inter_key, "Synthetic Root", hierarchy.root_key, ca=True,
                          not_before=NOW - 400 * DAY, not_after=NOW - 1 * DAY)
    r = validate_sns_signing_chain(hierarchy.leaf, [expired_inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.EXPIRED


def test_not_yet_valid_leaf_is_not_yet_valid(hierarchy):
    future = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                   not_before=NOW + 2 * DAY, not_after=NOW + 400 * DAY, san_dns=[SYNTH_NAME])
    r = validate_sns_signing_chain(future, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.NOT_YET_VALID


def test_not_yet_valid_intermediate_on_the_path_is_not_yet_valid(hierarchy):
    future_inter = _cert("Synthetic Intermediate", hierarchy.inter_key, "Synthetic Root", hierarchy.root_key, ca=True,
                         not_before=NOW + 2 * DAY, not_after=NOW + 400 * DAY)
    r = validate_sns_signing_chain(hierarchy.leaf, [future_inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.NOT_YET_VALID


def test_forged_leaf_with_the_intermediate_name_is_policy_error(hierarchy):
    forger_key = _key()
    forged = _cert("Synthetic Leaf", forger_key, "Synthetic Intermediate", forger_key, ca=False, san_dns=[SYNTH_NAME])
    r = validate_sns_signing_chain(forged, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


def test_forged_intermediate_signed_with_the_wrong_key_is_policy_error(hierarchy):
    forger_key = _key()
    forged_inter = _cert("Synthetic Intermediate", forger_key, "Synthetic Root", forger_key, ca=True)
    r = validate_sns_signing_chain(hierarchy.leaf, [forged_inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


def test_ec_intermediate_is_rejected_as_unsupported(hierarchy):
    ec_inter = _cert("Synthetic Intermediate", ec.generate_private_key(ec.SECP256R1()),
                     "Synthetic Root", hierarchy.root_key, ca=True)
    r = validate_sns_signing_chain(hierarchy.leaf, [ec_inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


def test_weak_rsa_intermediate_is_rejected(hierarchy):
    weak_inter = _cert("Synthetic Intermediate", _key(bits=1024), "Synthetic Root", hierarchy.root_key, ca=True)
    r = validate_sns_signing_chain(hierarchy.leaf, [weak_inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


def test_ec_leaf_key_is_rejected_as_unsupported(hierarchy):
    ec_leaf = _cert("Synthetic Leaf", ec.generate_private_key(ec.SECP256R1()), "Synthetic Intermediate",
                    hierarchy.inter_key, ca=False)
    r = validate_sns_signing_chain(ec_leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


def test_weak_rsa_leaf_key_is_rejected(hierarchy):
    weak_leaf = _cert("Synthetic Leaf", _key(bits=1024), "Synthetic Intermediate", hierarchy.inter_key, ca=False)
    r = validate_sns_signing_chain(weak_leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


def test_sha1_signature_algorithm_is_rejected_by_the_policy_predicate(hierarchy):
    # cryptography 50 refuses to sign with SHA-1, so the predicate is tested with a stub that reports sha1.
    class _Sha1Cert:
        public_key = staticmethod(lambda: hierarchy.leaf_key.public_key())
        signature_hash_algorithm = hashes.SHA1()
    assert chain._check_key_and_signature(_Sha1Cert()) is False
    assert chain._check_key_and_signature(hierarchy.leaf) is True


def test_non_ca_intermediate_cannot_issue_the_leaf(hierarchy):
    not_ca = _cert("Synthetic Intermediate", hierarchy.inter_key, "Synthetic Root", hierarchy.root_key, ca=False)
    r = validate_sns_signing_chain(hierarchy.leaf, [not_ca], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR


# ---------------------------------------------------------------------------
# D. Path building (F6, F7) and multi-candidate paths (F4)
# ---------------------------------------------------------------------------

def test_genuine_intermediate_is_selected_over_a_same_name_forgery(hierarchy):
    forger_key = _key()
    forged_inter = _cert("Synthetic Intermediate", forger_key, "Synthetic Root", hierarchy.root_key, ca=True)
    # The forgery is listed first: selection must rest on signature verification, not on list position.
    r = validate_sns_signing_chain(hierarchy.leaf, [forged_inter, hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED


def test_unrelated_expired_certificate_in_the_bundle_does_not_break_a_valid_path(hierarchy):
    unrelated_key = _key()
    stale = _cert("Stale Unrelated", unrelated_key, "Stale Unrelated", unrelated_key, ca=True,
                  not_before=NOW - 400 * DAY, not_after=NOW - 1 * DAY)
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter, stale], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED


def test_currently_valid_candidate_is_preferred_over_an_expired_duplicate_with_the_same_key(hierarchy):
    # Path building prefers a candidate valid at `now`. The expired duplicate is therefore not on the selected path.
    expired_inter = _cert("Synthetic Intermediate", hierarchy.inter_key, "Synthetic Root", hierarchy.root_key, ca=True,
                          not_before=NOW - 400 * DAY, not_after=NOW - 1 * DAY)
    r = validate_sns_signing_chain(hierarchy.leaf, [expired_inter, hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED


def test_expired_only_candidate_on_the_path_is_expired_not_silently_skipped(hierarchy):
    expired_inter = _cert("Synthetic Intermediate", hierarchy.inter_key, "Synthetic Root", hierarchy.root_key, ca=True,
                          not_before=NOW - 400 * DAY, not_after=NOW - 1 * DAY)
    r = validate_sns_signing_chain(hierarchy.leaf, [expired_inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.EXPIRED


def test_forged_root_presented_with_the_genuine_chain_does_not_change_the_anchor_decision(hierarchy):
    forger_key = _key()
    forged_root = _cert("Synthetic Root", forger_key, "Synthetic Root", forger_key, ca=True)
    # Genuine anchor available: the path is selected by signature, the forged root is ignored.
    ok = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter, forged_root], _anchors(hierarchy.root), now=NOW)
    assert ok.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED
    # Only the forged root as anchor: the genuine intermediate is not chained to it and must be refused.
    bad = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter, forged_root], _anchors(forged_root), now=NOW)
    assert bad.status is ChainStatus.POLICY_ERROR


# ---------------------------------------------------------------------------
# E. Inputs and fail-closed behaviour (F5, F8)
# ---------------------------------------------------------------------------

def test_naive_validation_time_is_refused(hierarchy):
    with pytest.raises(ValueError):
        validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root),
                                   now=NOW.replace(tzinfo=None))


def test_raw_certificate_list_is_refused_as_trust_anchors(hierarchy):
    with pytest.raises(TypeError):
        validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], [hierarchy.root], now=NOW)


def test_unexpected_errors_fail_closed_without_a_fake_fingerprint(hierarchy, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(chain, "_build_path", boom)
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR
    assert r.trusted is False
    assert r.leaf_fingerprint is None


def test_verifier_exception_is_policy_error_with_the_leaf_fingerprint(hierarchy, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("verifier unavailable")
    monkeypatch.setattr(chain, "_build_verifier", boom)
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR
    assert r.leaf_fingerprint == _fp(hierarchy.leaf)


def test_fetch_error_status_is_not_part_of_the_validator_contract():
    assert not hasattr(ChainStatus, "FETCH_ERROR")


# ---------------------------------------------------------------------------
# F. Trust anchors: authoritative provenance (F2)
# ---------------------------------------------------------------------------

def test_pinned_anchors_are_exactly_the_four_official_self_signed_roots():
    anchors = load_pinned_trust_anchors()
    assert isinstance(anchors, TrustAnchorSet)
    assert anchors.pinned is True
    subjects = sorted(c.subject.rfc4514_string() for c in anchors.certificates)
    assert subjects == sorted(OFFICIAL_SELF_SIGNED_SHA256)
    for cert in anchors.certificates:
        assert cert.issuer == cert.subject  # self-signed; cross-signed variants are not trust anchors
        assert _fp(cert) == OFFICIAL_SELF_SIGNED_SHA256[cert.subject.rfc4514_string()]


def test_pinned_anchor_loader_does_not_read_certifi():
    assert not hasattr(chain, "certifi")


def test_a_tampered_embedded_root_fails_closed():
    sources = list(chain.AMAZON_ROOT_SOURCES)
    swapped = sources[0]._replace(pem=sources[1].pem)  # root 1 entry now carries root 2 material
    with pytest.raises(TrustAnchorError):
        load_pinned_trust_anchors(sources=[swapped] + sources[1:])


def test_a_missing_root_fails_closed():
    sources = list(chain.AMAZON_ROOT_SOURCES)
    with pytest.raises(TrustAnchorError):
        load_pinned_trust_anchors(sources=sources[:3])


def test_a_duplicate_root_fails_closed():
    sources = list(chain.AMAZON_ROOT_SOURCES)
    with pytest.raises(TrustAnchorError):
        load_pinned_trust_anchors(sources=sources + [sources[0]])


def test_a_non_self_signed_substitute_is_rejected(hierarchy):
    # A certificate carrying a pinned subject name but issued by another key must not enter the anchor set.
    other_key = _key()
    substitute = _cert("Amazon Root CA 1", hierarchy.root_key, "Other Issuer", other_key, ca=True)
    pem = substitute.public_bytes(serialization.Encoding.PEM)
    sources = list(chain.AMAZON_ROOT_SOURCES)
    forged = sources[0]._replace(pem=pem)
    with pytest.raises(TrustAnchorError):
        load_pinned_trust_anchors(sources=[forged] + sources[1:])


def test_a_synthetic_chain_is_rejected_by_the_real_pinned_amazon_anchors(hierarchy):
    # The embedded production anchors must not accept a chain issued under a synthetic root.
    pinned = load_pinned_trust_anchors()
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], pinned, now=NOW, identity=_identity(SYNTH_NAME))
    # The synthetic root is neither presented nor a pinned anchor. Path building finds no candidate for the
    # intermediate's issuer name, so the exact reason is MISSING_INTERMEDIATE (no path to a pinned anchor).
    assert r.status is ChainStatus.MISSING_INTERMEDIATE
    assert r.anchors_pinned is True
    assert r.identity_checked is False
    assert r.trusted is False


def test_test_anchor_sets_are_never_pinned(hierarchy):
    assert _anchors(hierarchy.root).pinned is False


# Condition 1 (review F1/F2): pinned state is not constructible by callers.

def test_direct_construction_cannot_request_pinned_state(hierarchy):
    with pytest.raises(TypeError):
        TrustAnchorSet(certificates=(hierarchy.root,), pinned=True)


def test_direct_construction_is_never_pinned_even_with_the_official_roots():
    official = load_pinned_trust_anchors().certificates
    direct = TrustAnchorSet(certificates=official)
    assert direct.fingerprints() == chain._OFFICIAL_ANCHOR_FINGERPRINTS
    assert direct.pinned is False


def test_synthetic_root_cannot_become_trusted_through_a_forged_authority(hierarchy):
    forged = TrustAnchorSet(certificates=(hierarchy.root,))
    object.__setattr__(forged, "_authority", chain._PIN_AUTHORITY)  # simulates tampering with the private slot
    assert forged.pinned is False  # fingerprint check refuses synthetic roots even with the authority
    r = validate_sns_signing_chain(hierarchy.leaf, [hierarchy.inter], forged, now=NOW, identity=_identity(SYNTH_NAME))
    assert r.status is ChainStatus.OK  # the chain and identity are genuinely valid under the synthetic root
    assert r.identity_checked is True
    assert r.anchors_pinned is False
    assert r.trusted is False


def test_official_roots_plus_a_synthetic_root_cannot_be_pinned_by_copying_the_authority(hierarchy):
    pinned = load_pinned_trust_anchors()
    widened = TrustAnchorSet(certificates=pinned.certificates + (hierarchy.root,))
    object.__setattr__(widened, "_authority", chain._PIN_AUTHORITY)
    assert widened.pinned is False


def test_legitimate_loader_remains_pinned():
    assert load_pinned_trust_anchors().pinned is True


def test_loader_with_a_copied_source_list_is_not_pinned_even_with_official_pins():
    # Only the default AMAZON_ROOT_SOURCES object is treated as the official pinned set. Any other sequence is
    # validated like before but is never trusted as pinned, which is the stricter reading.
    anchors = load_pinned_trust_anchors(sources=list(chain.AMAZON_ROOT_SOURCES))
    assert anchors.fingerprints() == chain._OFFICIAL_ANCHOR_FINGERPRINTS
    assert anchors.pinned is False


def test_a_test_anchor_set_must_contain_self_signed_roots(hierarchy):
    with pytest.raises(ValueError):
        TrustAnchorSet.for_testing([hierarchy.leaf])


# ---------------------------------------------------------------------------
# G. Cache (F3): bound to certificate, anchors, identity, policy and time; successes only
# ---------------------------------------------------------------------------

def _counting_verifier(monkeypatch):
    calls = {"n": 0}
    original = chain._build_verifier

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(chain, "_build_verifier", counted)
    return calls


def test_success_is_served_from_cache_without_revalidation(hierarchy, monkeypatch):
    calls = _counting_verifier(monkeypatch)
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    r1 = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    r2 = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a,
                                           now=NOW + dt.timedelta(minutes=5))
    assert r1.status is r2.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED
    assert calls["n"] == 1


def test_anchor_change_invalidates_a_cached_success(hierarchy):
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    original = _anchors(hierarchy.root)
    first = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], original, now=NOW)
    assert first.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED
    assert len(cache) == 1
    other_key = _key()
    other_root = _cert("Synthetic Root", other_key, "Synthetic Root", other_key, ca=True)
    other = _anchors(other_root)
    # The anchor set is part of the key, so the earlier success is not stored under the new key.
    assert chain.cache_key(hierarchy.leaf, [hierarchy.inter], other) != \
        chain.cache_key(hierarchy.leaf, [hierarchy.inter], original)
    assert cache.get(chain.cache_key(hierarchy.leaf, [hierarchy.inter], other), now=NOW) is None
    r = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], other, now=NOW)
    # Exact outcome: the intermediate's issuer name exists but nothing verifies it under the new anchor.
    assert r.status is ChainStatus.POLICY_ERROR
    assert r.trusted is False
    assert len(cache) == 1  # the failure was not cached; the original success entry is untouched


def test_review_probe_cached_success_is_not_served_before_not_before(hierarchy):
    # Condition 2 reproduction: validate at NOW (success, cached), then ask for the same result at NOW-2d.
    late_leaf = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                      not_before=NOW - DAY, not_after=NOW + 30 * DAY, san_dns=[SYNTH_NAME])
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    ident = _identity(SYNTH_NAME)
    first = validate_sns_signing_chain_cached(cache, late_leaf, [hierarchy.inter], a, now=NOW, identity=ident)
    assert first.status is ChainStatus.OK
    earlier = NOW - 2 * DAY
    via_cache = validate_sns_signing_chain_cached(cache, late_leaf, [hierarchy.inter], a, now=earlier, identity=ident)
    uncached = validate_sns_signing_chain(late_leaf, [hierarchy.inter], a, now=earlier, identity=ident)
    assert uncached.status is ChainStatus.NOT_YET_VALID
    assert via_cache.status is not ChainStatus.OK  # the cached success is not returned
    assert via_cache == uncached  # same result as validation without the cache


def test_cache_hit_requires_every_covered_certificate_to_be_valid(hierarchy):
    # The intermediate starts later than the leaf. The path is valid only from the later notBefore, so a request
    # between the two starts must not be served from the cache (the earliest notBefore would wrongly allow it).
    late_inter = _cert("Synthetic Intermediate", hierarchy.inter_key, "Synthetic Root", hierarchy.root_key, ca=True,
                       not_before=NOW - DAY)
    leaf = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                 not_before=NOW - 30 * DAY, san_dns=[SYNTH_NAME])
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    first = validate_sns_signing_chain_cached(cache, leaf, [late_inter], a, now=NOW)
    assert first.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED
    between = NOW - 2 * DAY
    via_cache = validate_sns_signing_chain_cached(cache, leaf, [late_inter], a, now=between)
    uncached = validate_sns_signing_chain(leaf, [late_inter], a, now=between)
    assert uncached.status is ChainStatus.NOT_YET_VALID
    assert via_cache == uncached


def test_policy_version_change_invalidates_a_cached_success(hierarchy, monkeypatch):
    calls = _counting_verifier(monkeypatch)
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    with patch.object(chain, "POLICY_VERSION", "authz-truth-05.test-next"):
        validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    assert calls["n"] == 2


def test_identity_change_invalidates_a_cached_success(hierarchy, monkeypatch):
    calls = _counting_verifier(monkeypatch)
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW,
                                      identity=_identity(SYNTH_NAME))
    r = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW,
                                          identity=_identity(SYNTH_OTHER))
    assert calls["n"] == 2
    assert r.status is ChainStatus.HOST_MISMATCH


def test_failed_validation_is_never_cached(hierarchy):
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    forger = _key()
    forged = _cert("Synthetic Leaf", forger, "Synthetic Intermediate", forger, ca=False, san_dns=[SYNTH_NAME])
    r = validate_sns_signing_chain_cached(cache, forged, [hierarchy.inter], _anchors(hierarchy.root), now=NOW)
    assert r.status is ChainStatus.POLICY_ERROR
    assert len(cache) == 0


def test_the_cache_refuses_to_store_a_failure_directly(hierarchy):
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    failed = ChainResult(ChainStatus.POLICY_ERROR, "f", identity_checked=False, anchors_pinned=True)
    with pytest.raises(ValueError):
        cache.put("some-key", failed, now=NOW, not_after=NOW + DAY)
    assert len(cache) == 0


def test_recovery_after_a_transient_failure_is_served_fresh(hierarchy, monkeypatch):
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    original = chain._build_verifier
    state = {"fail": True}

    def flaky(*args, **kwargs):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("transient")
        return original(*args, **kwargs)

    monkeypatch.setattr(chain, "_build_verifier", flaky)
    first = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    second = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    assert first.status is ChainStatus.POLICY_ERROR
    assert second.status is ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED


def test_certificate_rotation_does_not_reuse_the_old_result(hierarchy, monkeypatch):
    calls = _counting_verifier(monkeypatch)
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    rotated = _cert("Synthetic Leaf", _key(), "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                    san_dns=[SYNTH_NAME])
    r = validate_sns_signing_chain_cached(cache, rotated, [hierarchy.inter], a, now=NOW)
    assert calls["n"] == 2
    assert r.leaf_fingerprint == _fp(rotated)


def test_cached_entries_expire_at_the_certificate_not_after(hierarchy):
    short_leaf = _cert("Synthetic Leaf", hierarchy.leaf_key, "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                       not_before=NOW - DAY, not_after=NOW + dt.timedelta(hours=1), san_dns=[SYNTH_NAME])
    cache = ValidationCache(max_entries=8, ttl_seconds=86400)
    a = _anchors(hierarchy.root)
    validate_sns_signing_chain_cached(cache, short_leaf, [hierarchy.inter], a, now=NOW)
    key = chain.cache_key(short_leaf, [hierarchy.inter], a)
    assert cache.get(key, now=NOW + dt.timedelta(minutes=30)) is not None
    assert cache.get(key, now=NOW + dt.timedelta(hours=2)) is None


def test_cached_entries_expire_at_the_ttl_even_when_the_certificate_is_valid_longer(hierarchy):
    cache = ValidationCache(max_entries=8, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
    key = chain.cache_key(hierarchy.leaf, [hierarchy.inter], a)
    assert cache.get(key, now=NOW + dt.timedelta(seconds=3601)) is None


def test_cache_is_bounded_in_entries(hierarchy):
    cache = ValidationCache(max_entries=2, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    for i in range(5):
        leaf = _cert(f"Synthetic Leaf {i}", _key(), "Synthetic Intermediate", hierarchy.inter_key, ca=False,
                     san_dns=[SYNTH_NAME])
        validate_sns_signing_chain_cached(cache, leaf, [hierarchy.inter], a, now=NOW)
    assert len(cache) == 2  # five distinct successes into a bound of two: exactly two entries remain


def test_cache_entry_with_unrelated_future_ca_is_not_served_before_that_ca_not_before(hierarchy, monkeypatch):
    # The bundle carries an unrelated CA that starts in five days. It is not on the selected path, so the chain is
    # valid now, but the cache entry's not-before is the latest notBefore of everything presented (the future CA).
    # Before that instant the cache must not serve the entry; the result must equal uncached validation.
    future_key = _key()
    future_ca = _cert("Unrelated Future CA", future_key, "Unrelated Future CA", future_key, ca=True,
                      not_before=NOW + 5 * DAY)
    calls = _counting_verifier(monkeypatch)
    cache = ValidationCache(max_entries=8, ttl_seconds=10 * 86400)
    a = _anchors(hierarchy.root)
    bundle = [hierarchy.inter, future_ca]
    ident = _identity(SYNTH_NAME)

    primed = validate_sns_signing_chain_cached(cache, hierarchy.leaf, bundle, a, now=NOW, identity=ident)
    assert primed.status is ChainStatus.OK
    assert calls["n"] == 1

    # Before the future CA's notBefore: the entry must not be served, so the verifier runs again.
    before = NOW + 1 * DAY
    via_cache = validate_sns_signing_chain_cached(cache, hierarchy.leaf, bundle, a, now=before, identity=ident)
    assert calls["n"] == 2  # refused and revalidated, not served
    uncached = validate_sns_signing_chain(hierarchy.leaf, bundle, a, now=before, identity=ident)
    assert via_cache == uncached
    assert via_cache.status is ChainStatus.OK

    # After that instant the same entry is served from the cache: no verifier call during the cached request.
    after = NOW + 6 * DAY
    calls_before_served = calls["n"]
    served = validate_sns_signing_chain_cached(cache, hierarchy.leaf, bundle, a, now=after, identity=ident)
    assert calls["n"] == calls_before_served
    assert served == validate_sns_signing_chain(hierarchy.leaf, bundle, a, now=after, identity=ident)


def test_cache_is_safe_under_concurrent_access(hierarchy):
    # Interleaving is not controlled. The assertions hold for every interleaving: each call returns the same success
    # (hit or miss), no call raises, and the cache ends with exactly one entry for the single key.
    cache = ValidationCache(max_entries=16, ttl_seconds=3600)
    a = _anchors(hierarchy.root)
    start = threading.Barrier(8)
    lock = threading.Lock()
    statuses, errors = [], []

    def worker():
        try:
            start.wait(timeout=10)
            for _ in range(20):
                r = validate_sns_signing_chain_cached(cache, hierarchy.leaf, [hierarchy.inter], a, now=NOW)
                with lock:
                    statuses.append(r.status)
        except Exception as exc:  # recorded and asserted below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    assert len(statuses) == 8 * 20
    assert set(statuses) == {ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED}
    assert len(cache) == 1


def test_cache_bound_is_exact_under_concurrent_inserts(hierarchy):
    # 64 distinct keys into a bound of 16: the final size is exactly 16 for every interleaving.
    cache = ValidationCache(max_entries=16, ttl_seconds=3600)
    ok = ChainResult(ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED, "f", identity_checked=False, anchors_pinned=False)
    start = threading.Barrier(8)
    errors = []

    def worker(tid):
        try:
            start.wait(timeout=10)
            for i in range(8):
                cache.put(f"t{tid}-{i}", ok, now=NOW, not_after=NOW + DAY)
                cache.get(f"t{tid}-{i}", now=NOW)  # may already be evicted by another thread; not asserted
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    assert len(cache) == 16
