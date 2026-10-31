"""
InboundCheck - ESP Webhook Authentication & Signature Verification (Phase 4 Step 4 / Group 44 P0-01)
====================================================================================================
Enforces cryptographic authenticity, replay protection with clock skew tolerance,
and 1 MB payload limits across Postmark, SendGrid, Mailgun, SES, and Klaviyo webhooks.

Security Invariants (Group 44 P0-01):
1. Production and staging environments NEVER accept hardcoded test tokens ('test_secret_token',
   'valid_test_signature') under any circumstances.
2. Missing or invalid verification secrets in non-test environments fail closed (HTTP 500)
   before evaluating any request token or signature.
3. When a provider secret/public key IS configured, verification strictly uses that secret/key
   in all environments (test tokens are rejected even in development/test when a key is set).
4. Test-only bypasses are permitted EXCLUSIVELY when no provider secret is configured AND
   ENVIRONMENT is 'development' or 'test' AND STAGING_MODE is false.
5. SendGrid Signed Event Webhooks are verified using official ECDSA P-256 (secp256r1) with SHA-256
   over (timestamp + raw_body).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Mapping, Optional, Literal, Tuple
from fastapi import Request, HTTPException, status

from app.core.config import settings

try:
    from cryptography.exceptions import InvalidSignature as _CryptoInvalidSignature
    from cryptography.hazmat.primitives import hashes as _crypto_hashes
    from cryptography.hazmat.primitives import serialization as _crypto_serialization
    from cryptography.hazmat.primitives.asymmetric import ec as _crypto_ec
    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTOGRAPHY = False

logger = logging.getLogger("ESPWebhookService")

FORBIDDEN_TEST_TOKENS = frozenset({"test_secret_token", "valid_test_signature"})

# ==============================================================================
# NIST P-256 (secp256r1 / prime256v1) Curve Parameters (FIPS 186-4 / SEC 2)
# ==============================================================================
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFC
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5

# ASN.1 DER SubjectPublicKeyInfo prefix for secp256r1 (OID 1.2.840.10045.2.1 + 1.2.840.10045.3.1.7)
_SPKI_UNCOMPRESSED_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d03010703420004")
_SPKI_COMPRESSED_PREFIX = bytes.fromhex("3039301306072a8648ce3d020106082a8648ce3d030107032200")


def _is_test_bypass_allowed() -> bool:
    """
    Return True ONLY when:
    1. settings.ENVIRONMENT is strictly 'development' or 'test'
    2. STAGING_MODE is False (checked on both settings and os.environ)
    """
    env = (getattr(settings, "ENVIRONMENT", "") or "").strip().lower()
    if env not in ("development", "test"):
        return False

    staging_attr = getattr(settings, "STAGING_MODE", False)
    staging_env = (os.getenv("STAGING_MODE") or "").strip().lower()
    if (
        staging_attr is True
        or str(staging_attr).strip().lower() in ("true", "1", "yes")
        or staging_env in ("true", "1", "yes")
    ):
        return False

    return True


def _resolve_configured_secret(raw_secret: Optional[str], setting_name: str) -> str:
    """
    Normalize a configured secret.
    If the secret is set to a hardcoded test token in a non-test environment,
    fail closed immediately with HTTP 500.
    """
    clean = (raw_secret or "").strip()
    if not clean:
        return ""
    if clean in FORBIDDEN_TEST_TOKENS:
        if not _is_test_bypass_allowed():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{setting_name} is misconfigured with a forbidden test token in production.",
            )
        return ""
    return clean


# ==============================================================================
# ECDSA P-256 (secp256r1) + SHA-256 Verification & Key Utilities for SendGrid
# ==============================================================================

def _p256_is_on_curve(x: int, y: int) -> bool:
    if not (0 < x < _P256_P and 0 < y < _P256_P):
        return False
    return (y * y - (x * x * x + _P256_A * x + _P256_B)) % _P256_P == 0


def _p256_point_add(
    p1: Optional[Tuple[int, int]],
    p2: Optional[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P256_P == 0:
        return None
    if x1 == x2 and y1 == y2:
        lam = (3 * x1 * x1 + _P256_A) * pow(2 * y1, -1, _P256_P) % _P256_P
    else:
        lam = (y2 - y1) * pow((x2 - x1) % _P256_P, -1, _P256_P) % _P256_P
    x3 = (lam * lam - x1 - x2) % _P256_P
    y3 = (lam * (x1 - x3) - y1) % _P256_P
    return (x3, y3)


def _p256_point_mul(k: int, point: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    result: Optional[Tuple[int, int]] = None
    addend: Optional[Tuple[int, int]] = point
    scalar = k
    while scalar > 0:
        if scalar & 1:
            result = _p256_point_add(result, addend)
        addend = _p256_point_add(addend, addend)
        scalar >>= 1
    return result


def _extract_spki_der_bytes(raw_key: str) -> bytes:
    """
    Decode a SendGrid verification public key from either PEM ('-----BEGIN PUBLIC KEY-----')
    or raw Base64 SubjectPublicKeyInfo DER format.
    """
    if not raw_key or not isinstance(raw_key, str):
        raise ValueError("SendGrid verification key is empty.")
    clean = raw_key.strip()
    if not clean or clean in FORBIDDEN_TEST_TOKENS:
        raise ValueError("SendGrid verification key cannot be empty or a test token.")

    if "-----BEGIN" in clean:
        if "-----BEGIN PUBLIC KEY-----" not in clean or "-----END PUBLIC KEY-----" not in clean:
            raise ValueError("SendGrid PEM key must have PUBLIC KEY header and footer.")
        lines = [
            line.strip()
            for line in clean.splitlines()
            if line.strip() and not line.strip().startswith("-----")
        ]
        b64_body = "".join(lines)
    else:
        b64_body = "".join(clean.split())

    if not b64_body:
        raise ValueError("SendGrid verification key contains no Base64 payload.")

    try:
        return base64.b64decode(b64_body, validate=True)
    except Exception as exc:
        raise ValueError("SendGrid verification key is not valid Base64.") from exc


def load_sendgrid_ecdsa_public_key(raw_key: str) -> Tuple[int, int]:
    """
    Parse and validate a SendGrid ECDSA P-256 (secp256r1) public key.
    Returns the validated affine curve coordinates (x, y) on secp256r1.
    Raises ValueError if the key is malformed or not a valid P-256 public key.
    """
    der_bytes = _extract_spki_der_bytes(raw_key)

    if _HAS_CRYPTOGRAPHY:
        try:
            pub_obj = _crypto_serialization.load_der_public_key(der_bytes)
        except Exception as exc:
            raise ValueError("Failed to parse SubjectPublicKeyInfo DER key.") from exc
        if not isinstance(pub_obj, _crypto_ec.EllipticCurvePublicKey) or not isinstance(
            pub_obj.curve, _crypto_ec.SECP256R1
        ):
            raise ValueError("SendGrid public key must use ECDSA P-256 (secp256r1).")
        nums = pub_obj.public_numbers()
        if not _p256_is_on_curve(nums.x, nums.y):
            raise ValueError("SendGrid public key point is not on P-256 curve.")
        return (nums.x, nums.y)

    # Pure-Python ASN.1 SubjectPublicKeyInfo DER parser for secp256r1
    if len(der_bytes) == 91 and der_bytes.startswith(_SPKI_UNCOMPRESSED_PREFIX):
        x = int.from_bytes(der_bytes[27:59], "big")
        y = int.from_bytes(der_bytes[59:91], "big")
    elif len(der_bytes) == 59 and der_bytes.startswith(_SPKI_COMPRESSED_PREFIX):
        prefix_byte = der_bytes[26]
        if prefix_byte not in (0x02, 0x03):
            raise ValueError("Invalid compressed EC point prefix.")
        x = int.from_bytes(der_bytes[27:59], "big")
        if not (0 < x < _P256_P):
            raise ValueError("Compressed EC point X coordinate out of range.")
        alpha = (pow(x, 3, _P256_P) + _P256_A * x + _P256_B) % _P256_P
        beta = pow(alpha, (_P256_P + 1) // 4, _P256_P)
        if pow(beta, 2, _P256_P) != alpha:
            raise ValueError("Compressed EC point does not lie on P-256 curve.")
        y = beta if (beta & 1) == (prefix_byte & 1) else (_P256_P - beta)
    else:
        raise ValueError("Not a valid ECDSA P-256 (secp256r1) SubjectPublicKeyInfo public key.")

    if not _p256_is_on_curve(x, y):
        raise ValueError("SendGrid public key point does not lie on the P-256 curve.")

    return (x, y)


def _parse_asn1_der_ecdsa_signature(der_sig: bytes) -> Tuple[int, int]:
    """
    Strictly parse an ASN.1 DER-encoded ECDSA signature: SEQUENCE { r INTEGER, s INTEGER }.
    Enforces canonical DER length and positive integer encoding rules.
    """
    if len(der_sig) < 8 or der_sig[0] != 0x30:
        raise ValueError("Invalid DER ECDSA signature sequence header.")

    seq_len = der_sig[1]
    if seq_len & 0x80 or seq_len + 2 != len(der_sig):
        raise ValueError("Invalid DER ECDSA signature sequence length.")

    idx = 2
    if der_sig[idx] != 0x02:
        raise ValueError("Invalid DER INTEGER tag for r.")
    r_len = der_sig[idx + 1]
    if r_len <= 0 or r_len > 33 or idx + 2 + r_len > len(der_sig):
        raise ValueError("Invalid DER length for r.")
    r_bytes = der_sig[idx + 2 : idx + 2 + r_len]
    if r_bytes[0] & 0x80:
        raise ValueError("Negative r value in DER signature.")
    if len(r_bytes) > 1 and r_bytes[0] == 0x00 and not (r_bytes[1] & 0x80):
        raise ValueError("Non-canonical leading zero in r.")
    r = int.from_bytes(r_bytes, "big")

    idx += 2 + r_len
    if idx + 2 > len(der_sig) or der_sig[idx] != 0x02:
        raise ValueError("Invalid DER INTEGER tag for s.")
    s_len = der_sig[idx + 1]
    if s_len <= 0 or s_len > 33 or idx + 2 + s_len != len(der_sig):
        raise ValueError("Invalid DER length for s.")
    s_bytes = der_sig[idx + 2 : idx + 2 + s_len]
    if s_bytes[0] & 0x80:
        raise ValueError("Negative s value in DER signature.")
    if len(s_bytes) > 1 and s_bytes[0] == 0x00 and not (s_bytes[1] & 0x80):
        raise ValueError("Non-canonical leading zero in s.")
    s = int.from_bytes(s_bytes, "big")

    if not (1 <= r < _P256_N and 1 <= s < _P256_N):
        raise ValueError("ECDSA signature integers (r, s) out of P-256 curve order bounds.")

    return r, s


def verify_sendgrid_ecdsa_signature(
    verification_key: str,
    timestamp: str,
    raw_body: bytes,
    signature_b64: str,
) -> bool:
    """
    Verify a Twilio SendGrid Signed Event Webhook using ECDSA P-256 and SHA-256.
    SendGrid signs the exact byte sequence: `timestamp.encode('utf-8') + raw_body`
    and encodes the resulting ASN.1 DER ECDSA signature in Base64.
    """
    pub_point = load_sendgrid_ecdsa_public_key(verification_key)

    if not signature_b64 or not isinstance(signature_b64, str):
        return False
    clean_sig = signature_b64.strip()
    if not clean_sig or clean_sig in FORBIDDEN_TEST_TOKENS:
        return False

    try:
        der_sig = base64.b64decode(clean_sig, validate=True)
    except Exception:
        return False

    signed_payload = timestamp.encode("utf-8") + raw_body

    if _HAS_CRYPTOGRAPHY:
        try:
            # Also validate strict DER structure before passing to OpenSSL
            _parse_asn1_der_ecdsa_signature(der_sig)
            der_key = _extract_spki_der_bytes(verification_key)
            pub_obj = _crypto_serialization.load_der_public_key(der_key)
            if not isinstance(pub_obj, _crypto_ec.EllipticCurvePublicKey) or not isinstance(
                pub_obj.curve, _crypto_ec.SECP256R1
            ):
                return False
            pub_obj.verify(der_sig, signed_payload, _crypto_ec.ECDSA(_crypto_hashes.SHA256()))
            return True
        except (_CryptoInvalidSignature, ValueError, Exception):
            return False

    try:
        r, s = _parse_asn1_der_ecdsa_signature(der_sig)
    except ValueError:
        return False

    digest_int = int.from_bytes(hashlib.sha256(signed_payload).digest(), "big")
    w = pow(s, -1, _P256_N)
    u1 = (digest_int * w) % _P256_N
    u2 = (r * w) % _P256_N
    point = _p256_point_add(
        _p256_point_mul(u1, (_P256_GX, _P256_GY)),
        _p256_point_mul(u2, pub_point),
    )
    if point is None:
        return False
    return (point[0] % _P256_N) == r


def _encode_der_integer(val: int) -> bytes:
    raw = val.to_bytes((val.bit_length() + 7) // 8 or 1, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return bytes([0x02, len(raw)]) + raw


def generate_sendgrid_ecdsa_keypair() -> Tuple[int, str, str]:
    """
    Generate an ECDSA P-256 (secp256r1) keypair formatted for SendGrid Signed Event Webhook testing.
    Returns (private_scalar, base64_spki_public_key, pem_public_key).
    """
    private_scalar = secrets.randbelow(_P256_N - 1) + 1
    pub_point = _p256_point_mul(private_scalar, (_P256_GX, _P256_GY))
    if pub_point is None:  # pragma: no cover
        raise RuntimeError("Failed to generate P-256 public key point.")
    qx, qy = pub_point
    spki_der = _SPKI_UNCOMPRESSED_PREFIX + qx.to_bytes(32, "big") + qy.to_bytes(32, "big")
    b64_spki = base64.b64encode(spki_der).decode("ascii")
    pem_pub = f"-----BEGIN PUBLIC KEY-----\n{b64_spki}\n-----END PUBLIC KEY-----"
    return private_scalar, b64_spki, pem_pub


def sign_sendgrid_ecdsa_webhook(private_scalar: int, timestamp: str, raw_body: bytes) -> str:
    """
    Create a valid Base64-encoded ASN.1 DER ECDSA P-256 SHA-256 signature
    over `timestamp.encode('utf-8') + raw_body` following SendGrid's Event Webhook protocol.
    """
    if not (1 <= private_scalar < _P256_N):
        raise ValueError("Invalid P-256 private scalar.")
    payload = timestamp.encode("utf-8") + raw_body
    digest_int = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    while True:
        k = secrets.randbelow(_P256_N - 1) + 1
        pt = _p256_point_mul(k, (_P256_GX, _P256_GY))
        if pt is None:
            continue
        r = pt[0] % _P256_N
        if r == 0:
            continue
        s = (pow(k, -1, _P256_N) * (digest_int + r * private_scalar)) % _P256_N
        if s != 0:
            break
    der_body = _encode_der_integer(r) + _encode_der_integer(s)
    der_seq = bytes([0x30, len(der_body)]) + der_body
    return base64.b64encode(der_seq).decode("ascii")


async def read_body_with_limit(request: Request, max_bytes: int = 1_048_576) -> bytes:
    """
    Read HTTP request body strictly enforcing a maximum byte ceiling (default 1 MB).
    Raises HTTP 413 Request Entity Too Large if exceeded.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Payload size {content_length} bytes exceeds maximum limit of {max_bytes} bytes.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header.",
            )

    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload size {len(body)} bytes exceeds maximum limit of {max_bytes} bytes.",
        )
    return body


class BaseESPVerifier:
    """Abstract base class for provider webhook verification."""

    async def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        max_clock_skew_seconds: int = 300,
    ) -> bool:
        raise NotImplementedError


class PostmarkWebhookVerifier(BaseESPVerifier):
    """
    Postmark webhook verification:
    Checks shared secret in `X-Postmark-Server-Token`, `X-Postmark-Webhook-Token`,
    or `Authorization` header using constant-time digest comparison.
    """

    async def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        max_clock_skew_seconds: int = 300,
    ) -> bool:
        secret = _resolve_configured_secret(
            settings.POSTMARK_WEBHOOK_SECRET,
            "POSTMARK_WEBHOOK_SECRET",
        )
        raw_token = (
            headers.get("x-postmark-server-token")
            or headers.get("x-postmark-webhook-token")
            or headers.get("authorization", "")
        )
        clean_token = raw_token.split(" ")[-1].strip() if raw_token else ""

        if secret:
            if not clean_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing Postmark webhook authentication token.",
                )
            if clean_token in FORBIDDEN_TEST_TOKENS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Postmark webhook token.",
                )
            if not hmac.compare_digest(clean_token.encode("utf-8"), secret.encode("utf-8")):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Postmark webhook token.",
                )
            return True

        # Secret is not configured: fail closed in production/staging
        if not _is_test_bypass_allowed():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="POSTMARK_WEBHOOK_SECRET is not configured in production.",
            )

        # Development/test-only bypass when secret is unconfigured
        if not clean_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Postmark webhook authentication token.",
            )
        if clean_token == "test_secret_token":
            return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Postmark webhook token.",
        )


class SendGridWebhookVerifier(BaseESPVerifier):
    """
    SendGrid Signed Event Webhook verification:
    Validates ECDSA P-256 (secp256r1) + SHA-256 signature and timestamp replay window.
    Headers:
      - X-Twilio-Email-Event-Webhook-Signature (Base64 ASN.1 DER ECDSA signature)
      - X-Twilio-Email-Event-Webhook-Timestamp (Unix epoch seconds)
    """

    async def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        max_clock_skew_seconds: int = 300,
    ) -> bool:
        verification_key = _resolve_configured_secret(
            settings.SENDGRID_WEBHOOK_VERIFICATION_KEY,
            "SENDGRID_WEBHOOK_VERIFICATION_KEY",
        )
        signature = (headers.get("x-twilio-email-event-webhook-signature") or "").strip()
        timestamp = (headers.get("x-twilio-email-event-webhook-timestamp") or "").strip()

        if verification_key:
            # 1. Validate server-configured public key first (fail closed with 500 if invalid key)
            try:
                load_sendgrid_ecdsa_public_key(verification_key)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"SENDGRID_WEBHOOK_VERIFICATION_KEY is invalid: {exc}",
                )

            # 2. Require both signature and timestamp headers
            if not signature or not timestamp:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing required SendGrid signature or timestamp headers.",
                )

            # 3. Explicitly reject test signatures even when public key is configured
            if signature in FORBIDDEN_TEST_TOKENS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid SendGrid webhook signature.",
                )

            # 4. Clock skew verification
            try:
                ts_int = int(timestamp)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid SendGrid timestamp format.",
                )

            now = int(time.time())
            if abs(now - ts_int) > max_clock_skew_seconds:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"SendGrid timestamp expired or clock skew exceeded "
                        f"({abs(now - ts_int)}s > {max_clock_skew_seconds}s)."
                    ),
                )

            # 5. Official ECDSA P-256 + SHA-256 cryptographic signature check
            if not verify_sendgrid_ecdsa_signature(
                verification_key=verification_key,
                timestamp=timestamp,
                raw_body=raw_body,
                signature_b64=signature,
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid SendGrid webhook signature.",
                )
            return True

        # Verification key is not configured: fail closed in production/staging
        if not _is_test_bypass_allowed():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SENDGRID_WEBHOOK_VERIFICATION_KEY is not configured in production.",
            )

        # Development/test-only bypass when verification key is unconfigured
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing required SendGrid signature or timestamp headers.",
            )
        if timestamp:
            try:
                ts_int = int(timestamp)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid SendGrid timestamp format.",
                )
            now = int(time.time())
            if abs(now - ts_int) > max_clock_skew_seconds:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"SendGrid timestamp expired or clock skew exceeded "
                        f"({abs(now - ts_int)}s > {max_clock_skew_seconds}s)."
                    ),
                )

        if signature == "valid_test_signature":
            return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid SendGrid webhook signature.",
        )


class MailgunWebhookVerifier(BaseESPVerifier):
    """
    Mailgun webhook verification:
    Validates HMAC-SHA256 of (timestamp + token) against MAILGUN_WEBHOOK_SIGNING_KEY.
    Payload contains `signature`: {"timestamp": "...", "token": "...", "signature": "..."}
    """

    async def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        max_clock_skew_seconds: int = 300,
    ) -> bool:
        signing_key = _resolve_configured_secret(
            settings.MAILGUN_WEBHOOK_SIGNING_KEY,
            "MAILGUN_WEBHOOK_SIGNING_KEY",
        )

        if not signing_key and not _is_test_bypass_allowed():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="MAILGUN_WEBHOOK_SIGNING_KEY is not configured in production.",
            )

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload in Mailgun webhook.",
            )

        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON structure in Mailgun webhook.",
            )

        sig_data = data.get("signature")
        if not isinstance(sig_data, dict):
            sig_data = {}

        timestamp = str(sig_data.get("timestamp") or "").strip()
        token = str(sig_data.get("token") or "").strip()
        sig = str(sig_data.get("signature") or "").strip()

        if signing_key:
            if not timestamp or not token or not sig:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing required Mailgun signature object in payload.",
                )

            if sig in FORBIDDEN_TEST_TOKENS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Mailgun webhook HMAC signature.",
                )

            # Clock skew check
            try:
                ts_int = int(timestamp)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Mailgun timestamp format.",
                )

            now = int(time.time())
            if abs(now - ts_int) > max_clock_skew_seconds:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Mailgun timestamp expired or clock skew exceeded "
                        f"({abs(now - ts_int)}s > {max_clock_skew_seconds}s)."
                    ),
                )

            # HMAC verification: HMAC-SHA256(key, timestamp + token)
            expected = hmac.new(
                signing_key.encode("utf-8"),
                f"{timestamp}{token}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(sig.lower(), expected.lower()):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Mailgun webhook HMAC signature.",
                )
            return True

        # Development/test-only bypass when signing_key is unconfigured
        if not sig:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing required Mailgun signature object in payload.",
            )
        if sig == "valid_test_signature":
            return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Mailgun webhook HMAC signature.",
        )


class SESWebhookVerifier(BaseESPVerifier):
    """
    Amazon SES / SNS webhook verification:
    Validates SNS notification envelope and shared signing token.
    Headers: `x-amz-sns-message-type`, `x-ses-webhook-secret` (or `x-webhook-token`)
    """

    _ALLOWED_SNS_TYPES = frozenset({
        "Notification",
        "SubscriptionConfirmation",
        "UnsubscribeConfirmation",
    })

    async def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        max_clock_skew_seconds: int = 300,
    ) -> bool:
        secret = _resolve_configured_secret(
            settings.SES_WEBHOOK_SECRET,
            "SES_WEBHOOK_SECRET",
        )
        received_secret = (
            headers.get("x-ses-webhook-secret")
            or headers.get("x-webhook-token")
            or ""
        ).strip()

        sns_msg_type = (headers.get("x-amz-sns-message-type") or "").strip()
        if sns_msg_type and sns_msg_type not in self._ALLOWED_SNS_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported Amazon SNS message type: '{sns_msg_type}'.",
            )

        if secret:
            if not received_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing Amazon SES webhook secret token.",
                )
            if received_secret in FORBIDDEN_TEST_TOKENS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Amazon SES webhook secret token.",
                )
            if not hmac.compare_digest(received_secret.encode("utf-8"), secret.encode("utf-8")):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Amazon SES webhook secret token.",
                )
            return True

        if not _is_test_bypass_allowed():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SES_WEBHOOK_SECRET is not configured in production.",
            )

        # Development/test-only bypass when secret is unconfigured
        if not received_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Amazon SES webhook secret token.",
            )
        if received_secret in ("valid_test_signature", "test_secret_token"):
            return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Amazon SES webhook secret token.",
        )


class KlaviyoWebhookVerifier(BaseESPVerifier):
    """
    Klaviyo webhook verification:
    Validates HMAC-SHA256 signature in `X-Klaviyo-Signature` and timestamp in `X-Klaviyo-Timestamp`.
    """

    async def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        max_clock_skew_seconds: int = 300,
    ) -> bool:
        secret = _resolve_configured_secret(
            settings.KLAVIYO_WEBHOOK_SECRET,
            "KLAVIYO_WEBHOOK_SECRET",
        )
        sig = (headers.get("x-klaviyo-signature") or "").strip()
        ts = (headers.get("x-klaviyo-timestamp") or "").strip()

        if secret:
            if not sig:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing Klaviyo webhook signature header.",
                )

            if sig in FORBIDDEN_TEST_TOKENS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Klaviyo webhook signature.",
                )

            if ts:
                try:
                    ts_int = int(ts)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid Klaviyo timestamp format.",
                    )
                now = int(time.time())
                if abs(now - ts_int) > max_clock_skew_seconds:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Klaviyo timestamp clock skew exceeded "
                            f"({abs(now - ts_int)}s > {max_clock_skew_seconds}s)."
                        ),
                    )

            expected = hmac.new(
                secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(sig.lower(), expected.lower()):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Klaviyo webhook signature.",
                )
            return True

        if not _is_test_bypass_allowed():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="KLAVIYO_WEBHOOK_SECRET is not configured in production.",
            )

        # Development/test-only bypass when secret is unconfigured
        if not sig:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Klaviyo webhook signature header.",
            )
        if sig == "valid_test_signature":
            return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Klaviyo webhook signature.",
        )


class ESPWebhookVerifierRegistry:
    """Registry mapping ESP provider keys to their respective verifier implementations."""

    _verifiers = {
        "postmark": PostmarkWebhookVerifier(),
        "sendgrid": SendGridWebhookVerifier(),
        "mailgun": MailgunWebhookVerifier(),
        "ses": SESWebhookVerifier(),
        "klaviyo": KlaviyoWebhookVerifier(),
    }

    @classmethod
    def for_provider(
        cls,
        provider: Literal["postmark", "sendgrid", "mailgun", "ses", "klaviyo"],
    ) -> BaseESPVerifier:
        clean = provider.strip().lower()
        verifier = cls._verifiers.get(clean)
        if not verifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported webhook provider: '{provider}'.",
            )
        return verifier


esp_webhook_verifier = ESPWebhookVerifierRegistry

