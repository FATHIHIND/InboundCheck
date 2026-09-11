"""
InboundCheck - URL Security Policy & Strict Validation
======================================================
Deep validation for outbound remote asset fetching (BIMI logos, VMC certificates).
Blocks SSRF vectors, userinfo spoofing, fragments, non-HTTPS schemes, internal TLDs,
and IP literals.
"""

import ipaddress
import urllib.parse
from typing import Tuple, Optional


BLOCKED_SUFFIXES = [
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".corp",
    ".onion",
    ".arpa",
    ".localhost",
    ".test",
    ".example",
    ".invalid",
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
    "loopback",
}


class UrlPolicyViolation(Exception):
    """Raised when an outbound URL fails security requirements."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UrlPolicy:
    """
    Validates and normalizes target URLs before performing outbound HTTP asset queries.
    """

    @classmethod
    def validate_and_normalize(cls, raw_url: str) -> Tuple[str, str, int]:
        """
        Validate URL scheme, host, port, credentials, and structure.
        Returns:
            Tuple[normalized_url: str, normalized_hostname: str, port: int]
        Raises:
            UrlPolicyViolation if URL violates policy.
        """
        if not raw_url or not isinstance(raw_url, str):
            raise UrlPolicyViolation("EMPTY_URL", "URL string cannot be empty.")

        stripped = raw_url.strip()

        # Reject userinfo before standard parsing
        if "@" in stripped.split("/", 3)[2] if "/" in stripped else "@" in stripped:
            raise UrlPolicyViolation("USERINFO_PROHIBITED", "URL credentials (userinfo) are strictly prohibited.")

        # Reject fragments
        if "#" in stripped:
            raise UrlPolicyViolation("FRAGMENT_PROHIBITED", "URL fragments are prohibited in remote asset fetches.")

        try:
            parsed = urllib.parse.urlsplit(stripped)
        except Exception as e:
            raise UrlPolicyViolation("MALFORMED_URL", f"Failed to parse URL: {str(e)}")

        # 1. Scheme must be HTTPS strictly
        if parsed.scheme.lower() != "https":
            raise UrlPolicyViolation(
                "SCHEME_NOT_ALLOWED",
                f"Only HTTPS scheme is permitted for remote asset fetching. Received: '{parsed.scheme}'",
            )

        # 2. Port must be 443 (or default 443 if omitted)
        port = parsed.port or 443
        if port != 443:
            raise UrlPolicyViolation(
                "PORT_NOT_ALLOWED",
                f"Outbound asset fetching is restricted to port 443. Received: {port}",
            )

        # 3. Hostname checks
        hostname = parsed.hostname
        if not hostname:
            raise UrlPolicyViolation("MISSING_HOSTNAME", "URL must contain a valid hostname.")

        # Disallow IP literals in URL host (e.g. https://127.0.0.1/ or https://[::1]/)
        try:
            ipaddress.ip_address(hostname)
            raise UrlPolicyViolation(
                "IP_LITERAL_PROHIBITED",
                f"Direct IP-literal host '{hostname}' is prohibited. Must use an authoritative domain name.",
            )
        except ValueError:
            pass  # Expected: hostname is not an IP literal

        # Normalize via IDNA encoding/decoding
        try:
            ascii_host = hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except Exception as e:
            raise UrlPolicyViolation("IDNA_NORMALIZATION_FAILED", f"Hostname cannot be IDNA normalized: {str(e)}")

        # Check internal/local names
        if ascii_host in BLOCKED_HOSTNAMES:
            raise UrlPolicyViolation("INTERNAL_HOSTNAME_BLOCKED", f"Hostname '{ascii_host}' is blocked.")

        if any(ascii_host.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
            raise UrlPolicyViolation("INTERNAL_TLD_BLOCKED", f"Domain suffix of '{ascii_host}' is prohibited.")

        if "." not in ascii_host:
            raise UrlPolicyViolation("LOCAL_HOSTNAME_BLOCKED", f"Single-label local hostnames like '{ascii_host}' are prohibited.")

        # Reconstruct normalized URL
        path = parsed.path or "/"
        query = f"?{parsed.query}" if parsed.query else ""
        normalized_url = f"https://{ascii_host}{path}{query}"

        return normalized_url, ascii_host, port
