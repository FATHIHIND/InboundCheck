"""
AUTHZ-TRUTH-05: SNS signing-certificate chain validation (logic only, not wired into message acceptance).

Concepts kept separate
- Chain validity: the presented certificates form a valid path to a pinned Amazon root (this module).
- Identity: the leaf certificate carries the expected SNS identity, and any required extension policy is met.
  Chain validity alone is NEVER identity. Without an IdentityPolicy the best outcome is
  CHAIN_OK_IDENTITY_UNVERIFIED, which is never trusted.
- Trust: `ChainResult.trusted` is True only when the chain is valid, the identity policy was evaluated and
  passed, and the anchors are the pinned official set.
- A successful TLS connection is never a substitute for any of the above.

Trust anchors
- The four Amazon Root CA certificates below are embedded verbatim from Amazon's official repository
  (https://www.amazontrust.com/repository/AmazonRootCA1.pem ... AmazonRootCA4.pem). Retrieved 2026-11-19.
  Their DER SHA-256 values match the "Self-signed" hashes published on the same official page.
- certifi is NOT consulted. Membership in a browser bundle is not evidence of Amazon root identity.

Deferred (requires genuine non-production AWS evidence; see docs/remediation/AUTHZ_TRUTH_05_SNS_CHAIN_READINESS.md)
- AWS-specific leaf constraints: SAN layout, Extended Key Usage, and the regional SNS hostname. No identity
  policy is applied by default, and none is invented here.
- The leaf extension policy is permit_all() in the cryptographic verifier. Leaf identity is enforced only through
  IdentityPolicy, never through that verifier policy.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, NamedTuple, Optional, Sequence, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.verification import ExtensionPolicy, PolicyBuilder, Store

# Bump on any change to validation semantics: cached results from an older policy are then never reused.
POLICY_VERSION = "authz-truth-05.2"
MIN_RSA_KEY_BITS = 2048
_ALLOWED_SIGNATURE_HASHES = frozenset({"sha256", "sha384", "sha512"})
_MAX_CHAIN_WALK = 8
EXPECTED_ANCHOR_COUNT = 4


class ChainStatus(str, Enum):
    OK = "ok"  # chain valid AND the supplied identity policy evaluated and passed
    CHAIN_OK_IDENTITY_UNVERIFIED = "chain_ok_identity_unverified"  # chain valid; no identity evaluated
    MISSING_INTERMEDIATE = "missing_intermediate"
    UNTRUSTED_ROOT = "untrusted_root"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    HOST_MISMATCH = "host_mismatch"
    POLICY_ERROR = "policy_error"


_SUCCESS_STATUSES = frozenset({ChainStatus.OK, ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED})


class TrustAnchorError(Exception):
    """Raised when the trust anchors cannot be loaded exactly as pinned."""


@dataclass(frozen=True)
class IdentityPolicy:
    """The identity an SNS leaf must present. At least one expected DNS name is required."""

    expected_dns_names: frozenset
    required_extended_key_usage: Optional[tuple] = None

    def __post_init__(self) -> None:
        names = frozenset(str(n).strip().lower() for n in self.expected_dns_names)
        if not names or any(not n for n in names):
            raise ValueError("An identity policy must name at least one expected DNS name.")
        object.__setattr__(self, "expected_dns_names", names)
        if self.required_extended_key_usage is not None:
            # Stored as dotted strings, the same form _eku_oids() returns for a certificate.
            object.__setattr__(self, "required_extended_key_usage", tuple(
                o.dotted_string if hasattr(o, "dotted_string") else str(o) for o in self.required_extended_key_usage
            ))

    def canonical(self) -> str:
        eku = ",".join(sorted(self.required_extended_key_usage or ()))
        return "names=" + ",".join(sorted(self.expected_dns_names)) + ";eku=" + eku


@dataclass(frozen=True)
class ChainResult:
    status: ChainStatus
    leaf_fingerprint: Optional[str]  # None only when the failure happened before the leaf could be read
    identity_checked: bool = False
    anchors_pinned: bool = False

    @property
    def trusted(self) -> bool:
        return self.status is ChainStatus.OK and self.identity_checked and self.anchors_pinned


class PinnedRoot(NamedTuple):
    name: str
    pem: bytes
    sha256: str  # SHA-256 of the DER certificate, lowercase hex, as published by Amazon Trust Services


AMAZON_ROOT_SOURCES: Tuple[PinnedRoot, ...] = (
    PinnedRoot("Amazon Root CA 1", b"""-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
""", "8ecde6884f3d87b1125ba31ac3fcb13d7016de7f57cc904fe1cb97c6ae98196e"),
    PinnedRoot("Amazon Root CA 2", b"""-----BEGIN CERTIFICATE-----
MIIFQTCCAymgAwIBAgITBmyf0pY1hp8KD+WGePhbJruKNzANBgkqhkiG9w0BAQwF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAyMB4XDTE1MDUyNjAwMDAwMFoXDTQwMDUyNjAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMjCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK2Wny2cSkxK
gXlRmeyKy2tgURO8TW0G/LAIjd0ZEGrHJgw12MBvIITplLGbhQPDW9tK6Mj4kHbZ
W0/jTOgGNk3Mmqw9DJArktQGGWCsN0R5hYGCrVo34A3MnaZMUnbqQ523BNFQ9lXg
1dKmSYXpN+nKfq5clU1Imj+uIFptiJXZNLhSGkOQsL9sBbm2eLfq0OQ6PBJTYv9K
8nu+NQWpEjTj82R0Yiw9AElaKP4yRLuH3WUnAnE72kr3H9rN9yFVkE8P7K6C4Z9r
2UXTu/Bfh+08LDmG2j/e7HJV63mjrdvdfLC6HM783k81ds8P+HgfajZRRidhW+me
z/CiVX18JYpvL7TFz4QuK/0NURBs+18bvBt+xa47mAExkv8LV/SasrlX6avvDXbR
8O70zoan4G7ptGmh32n2M8ZpLpcTnqWHsFcQgTfJU7O7f/aS0ZzQGPSSbtqDT6Zj
mUyl+17vIWR6IF9sZIUVyzfpYgwLKhbcAS4y2j5L9Z469hdAlO+ekQiG+r5jqFoz
7Mt0Q5X5bGlSNscpb/xVA1wf+5+9R+vnSUeVC06JIglJ4PVhHvG/LopyboBZ/1c6
+XUyo05f7O0oYtlNc/LMgRdg7c3r3NunysV+Ar3yVAhU/bQtCSwXVEqY0VThUWcI
0u1ufm8/0i2BWSlmy5A5lREedCf+3euvAgMBAAGjQjBAMA8GA1UdEwEB/wQFMAMB
Af8wDgYDVR0PAQH/BAQDAgGGMB0GA1UdDgQWBBSwDPBMMPQFWAJI/TPlUq9LhONm
UjANBgkqhkiG9w0BAQwFAAOCAgEAqqiAjw54o+Ci1M3m9Zh6O+oAA7CXDpO8Wqj2
LIxyh6mx/H9z/WNxeKWHWc8w4Q0QshNabYL1auaAn6AFC2jkR2vHat+2/XcycuUY
+gn0oJMsXdKMdYV2ZZAMA3m3MSNjrXiDCYZohMr/+c8mmpJ5581LxedhpxfL86kS
k5Nrp+gvU5LEYFiwzAJRGFuFjWJZY7attN6a+yb3ACfAXVU3dJnJUH/jWS5E4ywl
7uxMMne0nxrpS10gxdr9HIcWxkPo1LsmmkVwXqkLN1PiRnsn/eBG8om3zEK2yygm
btmlyTrIQRNg91CMFa6ybRoVGld45pIq2WWQgj9sAq+uEjonljYE1x2igGOpm/Hl
urR8FLBOybEfdF849lHqm/osohHUqS0nGkWxr7JOcQ3AWEbWaQbLU8uz/mtBzUF+
fUwPfHJ5elnNXkoOrJupmHN5fLT0zLm4BwyydFy4x2+IoZCn9Kr5v2c69BoVYh63
n749sSmvZ6ES8lgQGVMDMBu4Gon2nL2XA46jCfMdiyHxtN/kHNGfZQIG6lzWE7OE
76KlXIx3KadowGuuQNKotOrN8I1LOJwZmhsoVLiJkO/KdYE+HvJkJMcYr07/R54H
9jVlpNMKVv/1F2Rs76giJUmTtt8AF9pYfl3uxRuw0dFfIRDH+fO6AgonB8Xx1sfT
4PsJYGw=
-----END CERTIFICATE-----
""", "1ba5b2aa8c65401a82960118f80bec4f62304d83cec4713a19c39c011ea46db4"),
    PinnedRoot("Amazon Root CA 3", b"""-----BEGIN CERTIFICATE-----
MIIBtjCCAVugAwIBAgITBmyf1XSXNmY/Owua2eiedgPySjAKBggqhkjOPQQDAjA5
MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6b24g
Um9vdCBDQSAzMB4XDTE1MDUyNjAwMDAwMFoXDTQwMDUyNjAwMDAwMFowOTELMAkG
A1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJvb3Qg
Q0EgMzBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABCmXp8ZBf8ANm+gBG1bG8lKl
ui2yEujSLtf6ycXYqm0fc4E7O5hrOXwzpcVOho6AF2hiRVd9RFgdszflZwjrZt6j
QjBAMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMB0GA1UdDgQWBBSr
ttvXBp43rDCGB5Fwx5zEGbF4wDAKBggqhkjOPQQDAgNJADBGAiEA4IWSoxe3jfkr
BqWTrBqYaGFy+uGh0PsceGCmQ5nFuMQCIQCcAu/xlJyzlvnrxir4tiz+OpAUFteM
YyRIHN8wfdVoOw==
-----END CERTIFICATE-----
""", "18ce6cfe7bf14e60b2e347b8dfe868cb31d02ebb3ada271569f50343b46db3a4"),
    PinnedRoot("Amazon Root CA 4", b"""-----BEGIN CERTIFICATE-----
MIIB8jCCAXigAwIBAgITBmyf18G7EEwpQ+Vxe3ssyBrBDjAKBggqhkjOPQQDAzA5
MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6b24g
Um9vdCBDQSA0MB4XDTE1MDUyNjAwMDAwMFoXDTQwMDUyNjAwMDAwMFowOTELMAkG
A1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJvb3Qg
Q0EgNDB2MBAGByqGSM49AgEGBSuBBAAiA2IABNKrijdPo1MN/sGKe0uoe0ZLY7Bi
9i0b2whxIdIA6GO9mif78DluXeo9pcmBqqNbIJhFXRbb/egQbeOc4OO9X4Ri83Bk
M6DLJC9wuoihKqB1+IGuYgbEgds5bimwHvouXKNCMEAwDwYDVR0TAQH/BAUwAwEB
/zAOBgNVHQ8BAf8EBAMCAYYwHQYDVR0OBBYEFNPsxzplbszh2naaVvuc84ZtV+WB
MAoGCCqGSM49BAMDA2gAMGUCMDqLIfG9fhGt0O9Yli/W651+kI0rz2ZVwyzjKKlw
CkcO8DdZEv8tmZQoTipPNU0zWgIxAOp1AE47xDqUEpHJWEadIRNyp4iciuRMStuW
1KyLa2tJElMzrdfkviT8tQp21KW8EA==
-----END CERTIFICATE-----
""", "e35d28419ed02025cfa69038cd623962458da5c695fbdea3c22b0bfb25897092"),
)


# Module-private authority for the pinned state. Only load_pinned_trust_anchors() attaches it to a set, and it is
# not accepted by any constructor argument. It is necessary but not sufficient: TrustAnchorSet.pinned also requires
# the exact official fingerprint set, so a forged authority attached to synthetic roots still reports pinned=False.
_PIN_AUTHORITY = object()
_OFFICIAL_ANCHOR_FINGERPRINTS: frozenset = frozenset(s.sha256 for s in AMAZON_ROOT_SOURCES)


@dataclass(frozen=True)
class TrustAnchorSet:
    """
    A set of trust-anchor certificates. There is no public way to request pinned status: the constructor accepts
    certificates only. `pinned` is True only when the set was produced by load_pinned_trust_anchors() AND its
    certificates are exactly the official Amazon root fingerprints.
    """

    certificates: Tuple[x509.Certificate, ...]
    _authority: object = field(default=None, init=False, repr=False, compare=False)

    @property
    def pinned(self) -> bool:
        return self._authority is _PIN_AUTHORITY and self.fingerprints() == _OFFICIAL_ANCHOR_FINGERPRINTS

    @classmethod
    def for_testing(cls, certs: Iterable[x509.Certificate]) -> "TrustAnchorSet":
        certs = tuple(certs)
        for cert in certs:
            if not _is_self_signed(cert):
                raise ValueError("Test trust anchors must be self-signed roots.")
        return cls(certificates=certs)

    def fingerprints(self) -> frozenset:
        return frozenset(fingerprint(c) for c in self.certificates)


def fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def _is_self_signed(cert: x509.Certificate) -> bool:
    if cert.issuer != cert.subject:
        return False
    try:
        cert.verify_directly_issued_by(cert)
        return True
    except ValueError:
        return False


def load_pinned_trust_anchors(sources: Sequence[PinnedRoot] = AMAZON_ROOT_SOURCES) -> TrustAnchorSet:
    """
    Load the embedded Amazon roots. Fails closed unless there are exactly the expected number of distinct,
    self-signed certificates whose DER SHA-256 matches the pinned value.
    """
    is_default_sources = sources is AMAZON_ROOT_SOURCES
    sources = tuple(sources)
    if len(sources) != EXPECTED_ANCHOR_COUNT:
        raise TrustAnchorError("The trust anchor source list does not contain exactly the expected roots.")
    if len({s.sha256 for s in sources}) != len(sources):
        raise TrustAnchorError("Duplicate trust anchor entries.")
    certs: List[x509.Certificate] = []
    for source in sources:
        try:
            loaded = x509.load_pem_x509_certificates(source.pem)
        except ValueError as exc:
            raise TrustAnchorError(f"{source.name} could not be parsed.") from exc
        if len(loaded) != 1:
            raise TrustAnchorError(f"{source.name} must contain exactly one certificate.")
        cert = loaded[0]
        if fingerprint(cert) != source.sha256:
            raise TrustAnchorError(f"{source.name} does not match its pinned SHA-256.")
        if not _is_self_signed(cert):
            raise TrustAnchorError(f"{source.name} is not a self-signed root.")
        certs.append(cert)
    if len({c.subject for c in certs}) != len(certs):
        raise TrustAnchorError("Duplicate trust anchor subjects.")
    anchors = TrustAnchorSet(certificates=tuple(certs))
    if is_default_sources:
        object.__setattr__(anchors, "_authority", _PIN_AUTHORITY)
    return anchors


def _build_verifier(anchors: Sequence[x509.Certificate], now: dt.datetime):
    return (
        PolicyBuilder()
        .store(Store(list(anchors)))
        .time(now)
        .extension_policies(
            ca_policy=ExtensionPolicy.webpki_defaults_ca(),
            # Leaf identity is enforced only through IdentityPolicy (see module docstring).
            ee_policy=ExtensionPolicy.permit_all(),
        )
        .build_client_verifier()
    )


def _check_key_and_signature(cert: x509.Certificate) -> bool:
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < MIN_RSA_KEY_BITS:
        return False
    algorithm = cert.signature_hash_algorithm
    return algorithm is not None and algorithm.name in _ALLOWED_SIGNATURE_HASHES


def _issued_by(child: x509.Certificate, issuer: x509.Certificate) -> bool:
    """True only when the issuer's key verifies the child's signature and the names match."""
    try:
        child.verify_directly_issued_by(issuer)
        return True
    except Exception:  # cryptography raises InvalidSignature (not ValueError) for a wrong key
        return False


def _valid_at(cert: x509.Certificate, now: dt.datetime) -> bool:
    return cert.not_valid_before_utc <= now <= cert.not_valid_after_utc


def _dns_names(cert: x509.Certificate) -> List[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return [n.lower() for n in san.get_values_for_type(x509.DNSName)]


def _eku_oids(cert: x509.Certificate) -> frozenset:
    try:
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound:
        return frozenset()
    return frozenset(oid.dotted_string for oid in eku)


def _build_path(
    leaf: x509.Certificate,
    intermediates: Sequence[x509.Certificate],
    anchors: Sequence[x509.Certificate],
    now: dt.datetime,
) -> Tuple[Optional[ChainStatus], List[x509.Certificate]]:
    """
    Walk from the leaf toward a pinned anchor. Candidates are chosen by signature verification, never by list
    position; a currently valid candidate is preferred. Returns (failure_status, path_intermediates); the failure
    status is None when the walk reaches an anchor whose key verifies the last link.
    """
    path: List[x509.Certificate] = []
    seen = {fingerprint(leaf)}
    current = leaf
    for _ in range(_MAX_CHAIN_WALK):
        if current.issuer == current.subject:
            if any(fingerprint(a) == fingerprint(current) for a in anchors):
                return None, path
            return ChainStatus.UNTRUSTED_ROOT, path
        if any(a.subject == current.issuer and _issued_by(current, a) for a in anchors):
            return None, path
        candidates = [i for i in intermediates if i.subject == current.issuer and _issued_by(current, i)]
        if candidates:
            candidates.sort(key=lambda c: 0 if _valid_at(c, now) else 1)
            nxt = candidates[0]
            fp = fingerprint(nxt)
            if fp in seen:
                return ChainStatus.POLICY_ERROR, path
            seen.add(fp)
            path.append(nxt)
            current = nxt
            continue
        same_name_exists = any(i.subject == current.issuer for i in intermediates) or \
            any(a.subject == current.issuer for a in anchors)
        if same_name_exists:
            # A certificate with the issuer name exists but none verifies the signature: forgery or corruption.
            return ChainStatus.POLICY_ERROR, path
        return ChainStatus.MISSING_INTERMEDIATE, path
    return ChainStatus.POLICY_ERROR, path


def _identity_status(leaf: x509.Certificate, identity: IdentityPolicy) -> Optional[ChainStatus]:
    names = set(_dns_names(leaf))
    if not names or not (identity.expected_dns_names & names):
        return ChainStatus.HOST_MISMATCH
    if identity.required_extended_key_usage:
        if not set(identity.required_extended_key_usage) <= _eku_oids(leaf):
            return ChainStatus.POLICY_ERROR
    return None


def validate_sns_signing_chain(
    leaf: x509.Certificate,
    intermediates: Iterable[x509.Certificate],
    trust_anchors: TrustAnchorSet,
    *,
    now: dt.datetime,
    identity: Optional[IdentityPolicy] = None,
) -> ChainResult:
    """
    Validate a presented signing chain. Every failure returns an explicit status. Unexpected exceptions fail closed
    as POLICY_ERROR. No network access is performed. Raw certificate lists are refused: only a TrustAnchorSet
    is accepted, so an arbitrary anchor cannot enter by accident.
    """
    if not isinstance(trust_anchors, TrustAnchorSet):
        raise TypeError("trust_anchors must be a TrustAnchorSet.")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")
    pinned = trust_anchors.pinned
    leaf_fp: Optional[str] = None
    try:
        leaf_fp = fingerprint(leaf)
        inter = list(intermediates)
        failure, path = _build_path(leaf, inter, trust_anchors.certificates, now)
        if failure is not None:
            return ChainResult(failure, leaf_fp, False, pinned)
        presented = [leaf] + path
        for cert in presented:
            if not _check_key_and_signature(cert):
                return ChainResult(ChainStatus.POLICY_ERROR, leaf_fp, False, pinned)
        for cert in presented:
            if now > cert.not_valid_after_utc:
                return ChainResult(ChainStatus.EXPIRED, leaf_fp, False, pinned)
            if now < cert.not_valid_before_utc:
                return ChainResult(ChainStatus.NOT_YET_VALID, leaf_fp, False, pinned)
        try:
            _build_verifier(trust_anchors.certificates, now).verify(leaf, path)
        except Exception:
            return ChainResult(ChainStatus.POLICY_ERROR, leaf_fp, False, pinned)
        if identity is None:
            return ChainResult(ChainStatus.CHAIN_OK_IDENTITY_UNVERIFIED, leaf_fp, False, pinned)
        identity_failure = _identity_status(leaf, identity)
        if identity_failure is not None:
            return ChainResult(identity_failure, leaf_fp, True, pinned)
        return ChainResult(ChainStatus.OK, leaf_fp, True, pinned)
    except Exception:
        return ChainResult(ChainStatus.POLICY_ERROR, None, False, pinned)


def cache_key(
    leaf: x509.Certificate,
    intermediates: Iterable[x509.Certificate],
    trust_anchors: TrustAnchorSet,
    identity: Optional[IdentityPolicy] = None,
) -> str:
    """Binds a result to the exact leaf, path inputs, anchor set, identity policy and policy version."""
    parts = [
        POLICY_VERSION,
        "leaf=" + fingerprint(leaf),
        "path=" + ",".join(sorted(fingerprint(c) for c in intermediates)),
        "anchors=" + ",".join(sorted(trust_anchors.fingerprints())),
        "pinned=" + ("1" if trust_anchors.pinned else "0"),
        "identity=" + (identity.canonical() if identity is not None else "none"),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class ValidationCache:
    """
    Bounded, thread-safe cache of successful validations only. Each entry expires at the earlier of the TTL and the
    earliest notAfter among the certificates it covers. Failures are refused, never stored.
    """

    def __init__(self, max_entries: int = 32, ttl_seconds: int = 3600) -> None:
        if max_entries < 1 or ttl_seconds < 1:
            raise ValueError("max_entries and ttl_seconds must be positive.")
        self._max = max_entries
        self._ttl = dt.timedelta(seconds=ttl_seconds)
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, Tuple[ChainResult, dt.datetime, Optional[dt.datetime]]]" = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def put(
        self,
        key: str,
        result: ChainResult,
        *,
        now: dt.datetime,
        not_after: dt.datetime,
        not_before: Optional[dt.datetime] = None,
    ) -> None:
        """
        not_before is the instant from which every covered certificate is valid (the latest notBefore on the path).
        A hit is refused for any earlier time, so a later clock regression cannot replay a success.
        """
        if result.status not in _SUCCESS_STATUSES:
            raise ValueError("Only successful validations may be cached.")
        expires = min(now + self._ttl, not_after)
        if expires <= now:
            return
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = (result, expires, not_before)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def get(self, key: str, *, now: dt.datetime) -> Optional[ChainResult]:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            result, expires, not_before = item
            if now >= expires:
                self._items.pop(key, None)
                return None
            if not_before is not None and now < not_before:
                # Not evicted: a later request at a valid time may still use the entry.
                return None
            return result


def validate_sns_signing_chain_cached(
    cache: ValidationCache,
    leaf: x509.Certificate,
    intermediates: Iterable[x509.Certificate],
    trust_anchors: TrustAnchorSet,
    *,
    now: dt.datetime,
    identity: Optional[IdentityPolicy] = None,
) -> ChainResult:
    inter = list(intermediates)
    key = cache_key(leaf, inter, trust_anchors, identity)
    hit = cache.get(key, now=now)
    if hit is not None:
        return hit
    result = validate_sns_signing_chain(leaf, inter, trust_anchors, now=now, identity=identity)
    if result.status in _SUCCESS_STATUSES:
        covered = [leaf] + inter
        not_after = min(c.not_valid_after_utc for c in covered)
        # Latest notBefore: the whole presented set is valid only from this instant onward.
        not_before = max(c.not_valid_before_utc for c in covered)
        cache.put(key, result, now=now, not_after=not_after, not_before=not_before)
    return result
