---
name: fastapi-cloud-security
description: Enforces institutional backend security, cryptographic credential storage (Fernet), anti-SSRF protections, strict Pydantic v2 typing, Supabase JWT auth, and webhook integrity across the FastAPI codebase. Use when developing or reviewing backend endpoints, external API integrations (DNS, Shopify, Stripe, Twilio), and database interactions.
---

# FastAPI & Cloud Infrastructure Security

## Overview

InboundCheck interacts with critical merchant infrastructure: DNS zone records, Shopify store admin APIs, Twilio omnichannel credentials, and Stripe payment webhooks. Any vulnerability (SSRF, credential exposure, BOLA/IDOR, replay attack) could compromise merchant domain reputation, lead to unauthorized DNS changes, or cause data leakage.

This skill establishes mandatory zero-trust backend standards for Python 3.12+ / FastAPI, Pydantic v2, and Supabase PostgreSQL.

---

## When to Use

- Creating or modifying FastAPI routers in `backend/app/api/v1/`
- Interacting with external network endpoints, HTTP clients (`httpx`), or DNS resolvers (`dnspython`)
- Handling third-party API credentials (Cloudflare tokens, GoDaddy secrets, Twilio keys)
- Implementing or modifying Pydantic schemas in `backend/app/schemas/`
- Handling Stripe or Shopify webhooks and signature validations
- Writing database migration scripts with Supabase RLS policies

---

## 1. Cryptographic Credential Vault (Fernet Envelope Encryption)

Third-party API keys (Cloudflare API Tokens, GoDaddy API Keys & Secrets, Twilio Auth Tokens) **must never** be stored in plaintext in the database or logs.

### Standards:
- Use `cryptography.fernet.Fernet` with a 32-byte URL-safe base64-encoded master key (`ENCRYPTION_KEY`).
- Encrypt tokens at the boundary immediately upon receipt before saving to `dns_provider_credentials` or `failover_configs`.
- Decrypt tokens in-memory only during transient execution of provider API requests.
- Never include raw or decrypted tokens in API responses; return masked indicators only (e.g., `api_token_configured: true`, `last4: "a8f2"`).

```python
from cryptography.fernet import Fernet
from app.core.config import settings
import base64

def get_fernet_cipher() -> Fernet:
    """Instantiate Fernet cipher using configured master secret."""
    key = settings.ENCRYPTION_KEY
    if not key or len(key) < 32:
        raise RuntimeError("ENCRYPTION_KEY must be configured with a 32-byte secure key.")
    # Ensure URL-safe base64 encoding if provided as raw hex or string
    if len(key) == 32:
        key = base64.urlsafe_b64encode(key.encode())
    elif isinstance(key, str):
        key = key.encode()
    return Fernet(key)

def encrypt_secret(raw_value: str) -> str:
    cipher = get_fernet_cipher()
    return cipher.encrypt(raw_value.encode("utf-8")).decode("utf-8")

def decrypt_secret(encrypted_token: str) -> str:
    cipher = get_fernet_cipher()
    return cipher.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
```

---

## 2. Strict Anti-SSRF Defense & DNS Resolver Guardrails

Allowing users to probe arbitrary hostnames exposes internal infrastructure, Docker networking, localhost services, and cloud instance metadata (`169.254.169.254`).

### Guardrail Requirements:
1. **Domain Sanitization:** Strip scheme (`https://`), paths (`/`), ports (`:8080`), and credentials (`user:pass@`).
2. **Regex Validation:** Enforce strict FQDN syntax `^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$`.
3. **CIDR Blocklist Resolution:** Resolve the hostname's A/AAAA records before querying or connecting. Reject immediately if any resolved IP falls inside restricted subnets:
   - `127.0.0.0/8` & `::1/128` (Loopback)
   - `169.254.0.0/16` & `fe80::/10` (Cloud Metadata / Link-Local)
   - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (Private RFC 1918)
   - `100.64.0.0/10` (Carrier NAT RFC 6598)
   - `0.0.0.0/8`, `224.0.0.0/4`, `240.0.0.0/4` (Broadcast / Multicast / Reserved)
4. **DNS Rebinding Mitigation:** Pin the validated IP address for subsequent outbound connections rather than re-resolving.

```python
import ipaddress
import socket
from fastapi import HTTPException, status

RESTRICTED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
]

def assert_domain_ssrf_safe(domain: str) -> None:
    """Assert domain does not resolve to private or cloud-internal addresses."""
    try:
        addr_info = socket.getaddrinfo(domain, None)
        for _, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            for restricted in RESTRICTED_NETWORKS:
                if ip in restricted:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Security violation: Domain resolves to prohibited internal address ({ip})."
                    )
    except socket.gaierror:
        # Let diagnostic engine handle unresolvable domains gracefully
        pass
```

---

## 3. Strict Pydantic v2 Typing & Input Validation

- Use `BaseModel` with `model_config = ConfigDict(strict=True, extra="forbid")` for sensitive input payloads.
- Use `@field_validator` with mode `'before'` or `'after'` to sanitize input and normalize casing (e.g. lowercasing domains and emails).
- Disallow raw dictionary parameters (`Dict[str, Any]`) in route signatures. Explicitly define request DTOs.

```python
from pydantic import BaseModel, ConfigDict, field_validator, Field
import re

class DomainRegistrationRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    domain_name: str = Field(..., min_length=3, max_length=253, description="Fully qualified domain name")
    auto_monitor: bool = Field(default=True)

    @field_validator("domain_name")
    @classmethod
    def sanitize_domain(cls, v: str) -> str:
        clean = v.strip().lower()
        clean = re.sub(r"^https?://", "", clean).split("/")[0].split(":")[0]
        if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", clean):
            raise ValueError("Invalid domain name format.")
        return clean
```

---

## 4. Multi-Tenant Authorization & BOLA / IDOR Prevention

- **Never trust a client-supplied `user_id` query parameter or body field.**
- Always extract user identity using the `get_current_user_id` dependency from `app.core.security`.
- All database queries must bind the tenant ID either in the query filter or via Supabase RLS JWT bearer headers.

```python
@router.post("/domains", response_model=MonitoredDomainResponse)
async def register_domain(
    payload: DomainRegistrationRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    # current_user_id is cryptographically guaranteed by Supabase JWT verification
    domain = await domain_service.create_monitored_domain(
        user_id=current_user_id,
        domain_name=payload.domain_name
    )
    return domain
```

---

## 5. Webhook Security & Idempotency

### Stripe & Shopify Webhooks:
1. **Always Verify HMAC Signatures:**
   - Stripe: `stripe.Webhook.construct_event(payload_bytes, sig_header, settings.STRIPE_WEBHOOK_SECRET)`
   - Shopify: Compute `hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()` and compare using `hmac.compare_digest(base64_hmac, header_hmac)`.
2. **Fail-Closed in Production:** Never bypass signature checks when running in `ENVIRONMENT=production`.
3. **Idempotent Execution:** Store processed event IDs (`stripe_event_id` or `shopify_webhook_id`) in Supabase. Check before processing to prevent double-crediting or duplicate dispatch.

---

## Verification & Quality Bar

1. Run `py -m pytest tests/test_billing_and_security.py` to ensure JWT validation and SSRF guards are fully intact.
2. Verify all API routes return explicit status codes (400 for validation, 401 for unauthenticated, 403 for unauthorized, 429 for rate limit).
3. Ensure no raw exceptions or stack traces leak to the client (`debug=False` in production).
