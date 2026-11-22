"""
CS-API-02A regression tests: get_trusted_client_ip must never trust forwarding headers
when the direct peer is missing or invalid, and must never fall back to 127.0.0.1.

Requests are simple stubs: `client` is None or an object with `host`, and `headers`
is a plain mapping. Only the header names the resolver reads are provided.
"""

from app.core.rate_limiter import get_trusted_client_ip


class _Client:
    def __init__(self, host):
        self.host = host


class _Request:
    def __init__(self, host=None, headers=None, has_client=True):
        self.client = _Client(host) if has_client else None
        self.headers = dict(headers or {})


FORGED_CF = {"CF-Connecting-IP": "198.51.100.200"}
FORGED_XFF = {"X-Forwarded-For": "198.51.100.201, 203.0.113.9"}


# --- Missing direct peer -------------------------------------------------------

def test_missing_client_returns_unknown():
    assert get_trusted_client_ip(_Request(has_client=False)) == "unknown"


def test_missing_client_ignores_forged_cf_connecting_ip():
    req = _Request(has_client=False, headers=FORGED_CF)
    assert get_trusted_client_ip(req) == "unknown"


def test_missing_client_ignores_forged_x_forwarded_for():
    req = _Request(has_client=False, headers=FORGED_XFF)
    assert get_trusted_client_ip(req) == "unknown"


# --- Invalid direct peer -------------------------------------------------------

def test_invalid_peer_returns_unknown():
    assert get_trusted_client_ip(_Request(host="not-an-ip")) == "unknown"


def test_invalid_peer_ignores_forwarded_headers():
    req = _Request(host="not-an-ip", headers={**FORGED_CF, **FORGED_XFF})
    assert get_trusted_client_ip(req) == "unknown"


def test_empty_peer_returns_unknown():
    assert get_trusted_client_ip(_Request(host="")) == "unknown"


# --- Preserved behaviour -------------------------------------------------------

def test_untrusted_valid_peer_returns_its_direct_ip():
    assert get_trusted_client_ip(_Request(host="198.51.100.7")) == "198.51.100.7"


def test_untrusted_valid_peer_ignores_forged_cf_connecting_ip():
    req = _Request(host="198.51.100.7", headers=FORGED_CF)
    assert get_trusted_client_ip(req) == "198.51.100.7"


def test_untrusted_valid_peer_ignores_forged_x_forwarded_for():
    req = _Request(host="198.51.100.7", headers=FORGED_XFF)
    assert get_trusted_client_ip(req) == "198.51.100.7"


def test_trusted_loopback_peer_uses_valid_cf_connecting_ip():
    req = _Request(host="127.0.0.1", headers={"CF-Connecting-IP": "198.51.100.42"})
    assert get_trusted_client_ip(req) == "198.51.100.42"


def test_trusted_loopback_peer_uses_rightmost_untrusted_x_forwarded_for_hop():
    req = _Request(host="127.0.0.1", headers={"X-Forwarded-For": "203.0.113.10, 198.51.100.22, 127.0.0.1"})
    assert get_trusted_client_ip(req) == "198.51.100.22"


def test_trusted_loopback_peer_with_malformed_headers_falls_back_safely():
    req = _Request(
        host="127.0.0.1",
        headers={"CF-Connecting-IP": "not-an-ip; DROP TABLE", "X-Forwarded-For": "invalid-ip, also-bad"},
    )
    assert get_trusted_client_ip(req) == "127.0.0.1"
