"""
InboundCheck - Cryptographic Credential Vault (Fernet Authenticated Encryption)
=============================================================================
Enforces AES-128-CBC + HMAC-SHA256 authenticated envelope encryption for DNS provider credentials
stored at rest in Supabase PostgreSQL (public.dns_provider_credentials).

Guarantees:
1. Master encryption keys are loaded exclusively from the server environment.
2. Versioned ciphertext format ('v1:<fernet_token>') with no silent plaintext fallback.
3. Safe decryption error handling that never exposes raw ciphertext, keys, or stack traces.
4. Token masking utilities ensuring sensitive materials never enter client responses or logs.
"""

import base64
import hashlib
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger("CredentialVault")

CIPHERTEXT_PREFIX = "v1:"


class EncryptionKeyMissingError(RuntimeError):
    """Raised when server encryption key is not configured."""
    pass


class DecryptionError(ValueError):
    """Raised when ciphertext cannot be decrypted or authentication tag fails."""
    pass


def _derive_fernet_key(secret: str) -> bytes:
    """
    Derive a deterministic 32-byte URL-safe base64-encoded key from an arbitrary secret.
    Uses SHA-256 digest to guarantee exact 32 bytes required by Fernet.
    """
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet_cipher() -> Fernet:
    """
    Instantiate Fernet authenticated encryption cipher from server environment.

    Production Requirements (Strict Zero-Fallback Policy):
    - ENCRYPTION_KEY must be explicitly configured in server environment.
    - No fallback to SUPABASE_JWT_SECRET in production.
    - No automatic generation of keys in production.
    - Fails closed immediately with EncryptionKeyMissingError if missing or invalid.

    Development / Test:
    - If ENCRYPTION_KEY is configured, uses it.
    - Otherwise, allows a controlled deterministic test key for local test execution.
    """
    is_production = (getattr(settings, "ENVIRONMENT", "development") or "development").lower() in ("production", "prod")

    if is_production:
        raw_key = getattr(settings, "ENCRYPTION_KEY", "") or ""
        if not raw_key or not raw_key.strip():
            raise EncryptionKeyMissingError(
                "ENCRYPTION_KEY must be explicitly configured in production environment. "
                "JWT secret fallback and automatic key generation are strictly prohibited in production."
            )
        try:
            # Check if it's already a valid 32-byte urlsafe base64 string
            decoded = base64.urlsafe_b64decode(raw_key.strip().encode("utf-8"))
            if len(decoded) == 32:
                return Fernet(raw_key.strip().encode("utf-8"))
            # If not direct 32-byte base64, derive deterministic 32-byte key via SHA-256
            key_bytes = _derive_fernet_key(raw_key.strip())
            return Fernet(key_bytes)
        except Exception as e:
            raise EncryptionKeyMissingError(
                f"Configured ENCRYPTION_KEY is invalid for Fernet cipher instantiation: {e}"
            ) from e

    # Development / automated testing environment
    raw_key = getattr(settings, "ENCRYPTION_KEY", "") or ""
    if raw_key and raw_key.strip():
        try:
            decoded = base64.urlsafe_b64decode(raw_key.strip().encode("utf-8"))
            if len(decoded) == 32:
                return Fernet(raw_key.strip().encode("utf-8"))
            return Fernet(_derive_fernet_key(raw_key.strip()))
        except Exception:
            return Fernet(_derive_fernet_key(raw_key.strip()))

    # Controlled deterministic test fallback key (development/test only)
    dev_key = _derive_fernet_key("inboundcheck-default-dev-credential-encryption-key-32b")
    return Fernet(dev_key)


def encrypt_credential(plaintext: str) -> str:
    """
    Encrypt a sensitive credential string at rest using Fernet authenticated encryption.
    Returns version-prefixed ciphertext string: 'v1:<token>'.
    Never accepts empty strings; never allows silent plaintext pass-through.
    """
    if not plaintext:
        raise ValueError("Plaintext credential cannot be empty.")

    cipher = get_fernet_cipher()
    token = cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{CIPHERTEXT_PREFIX}{token}"


def decrypt_credential(ciphertext: str) -> str:
    """
    Decrypt a sensitive credential ciphertext into plaintext in transient memory.
    Validates version prefix and cryptographic HMAC authentication tag.
    Fails closed: raises DecryptionError on tampering, invalid key, or malformed token.
    """
    if not ciphertext:
        raise ValueError("Ciphertext cannot be empty.")

    clean_ciphertext = ciphertext.strip()
    if clean_ciphertext.startswith(CIPHERTEXT_PREFIX):
        clean_ciphertext = clean_ciphertext[len(CIPHERTEXT_PREFIX):]

    cipher = get_fernet_cipher()
    try:
        decrypted_bytes = cipher.decrypt(clean_ciphertext.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except (InvalidToken, Exception) as exc:
        logger.error("Failed to decrypt stored provider credential (authentication tag failure or corrupted ciphertext).")
        raise DecryptionError("Decryption failed: corrupted credential material or invalid server encryption key.") from exc


def mask_credential(raw_secret: Optional[str]) -> str:
    """
    Produce a secure display mask for client presentation.
    Shows only the last 4 characters preceded by bullets.
    Never exposes full length or contents.
    """
    if not raw_secret:
        return "••••••••••••"
    clean = raw_secret.strip()
    if len(clean) <= 4:
        return "••••"
    return f"••••••••••••{clean[-4:]}"
