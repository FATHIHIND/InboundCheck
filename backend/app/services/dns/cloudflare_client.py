"""
InboundCheck - Cloudflare REST v4 API Provider Adapter
======================================================
Robust, audited async client for interacting with Cloudflare DNS Zones:
- Token verification (user/tokens/verify)
- Dynamic Zone discovery by domain name (zones?name={domain})
- Exact record discovery (zones/{zone_id}/dns_records)
- Explicit narrow record mutation (POST / PUT)
- Record deletion for rollback (DELETE)
- Zero secret logging with regex token masking
"""

import re
import logging
from typing import Dict, Any, Optional, List
import httpx

logger = logging.getLogger("CloudflareClient")

CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
DEFAULT_TIMEOUT_SECONDS = 10.0


class CloudflareAPIError(Exception):
    """Raised when Cloudflare API returns non-200 or errors."""
    def __init__(self, message: str, status_code: int = 502, error_details: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_details = error_details or []


def _sanitize_error_text(text: str) -> str:
    """Strip any token, key, secret, or bearer value from error text."""
    if not text:
        return ""
    return re.sub(
        r"(token|key|secret|password|bearer)[=:\s]+[A-Za-z0-9_\-\.]+",
        r"\1=[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )


def extract_apex_domain(domain: str) -> str:
    """Extract apex domain from FQDN or hostname (e.g. '_dmarc.brandshop.com' -> 'brandshop.com')."""
    clean = domain.strip().lower().rstrip(".")
    clean = re.sub(r"^https?://", "", clean).split("/")[0].split(":")[0]
    parts = clean.split(".")
    if len(parts) <= 2:
        return clean
    # Common 2-part TLD handling (e.g., .co.uk, .com.au)
    two_part_tlds = {"co.uk", "org.uk", "gov.uk", "com.au", "net.au", "co.nz", "com.br"}
    if len(parts) >= 3 and f"{parts[-2]}.{parts[-1]}" in two_part_tlds:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class CloudflareClient:
    """Async API Client for Cloudflare DNS zone management."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.timeout = timeout

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify Cloudflare API token permissions with Cloudflare API.
        Endpoint: GET /client/v4/user/tokens/verify
        """
        url = f"{CLOUDFLARE_BASE_URL}/user/tokens/verify"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(url, headers=self._headers(token))
                data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}

                if res.status_code == 200 and data.get("success"):
                    return {
                        "is_valid": True,
                        "status": data.get("result", {}).get("status", "active"),
                        "message": "Cloudflare API token verified successfully.",
                    }
                err_msg = _sanitize_error_text(res.text)
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "message": f"Cloudflare token verification failed (HTTP {res.status_code}): {err_msg[:180]}",
                }
        except Exception as e:
            safe_err = _sanitize_error_text(str(e))
            logger.warning(f"Cloudflare token verification exception: {safe_err}")
            return {
                "is_valid": False,
                "status": "error",
                "message": f"Network error during Cloudflare verification: {safe_err[:150]}",
            }

    async def get_zone_by_domain(self, token: str, domain_name: str) -> Optional[Dict[str, Any]]:
        """
        Dynamically discover Cloudflare Zone by apex domain name.
        Endpoint: GET /client/v4/zones?name={apex_domain}&status=active
        """
        apex = extract_apex_domain(domain_name)
        url = f"{CLOUDFLARE_BASE_URL}/zones"
        params = {"name": apex, "status": "active"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(url, headers=self._headers(token), params=params)
                if res.status_code != 200:
                    safe_err = _sanitize_error_text(res.text)
                    logger.error(f"Failed to lookup Cloudflare zone for {apex}: HTTP {res.status_code} - {safe_err}")
                    raise CloudflareAPIError(f"Cloudflare zone lookup failed (HTTP {res.status_code}): {safe_err[:200]}")

                data = res.json()
                results = data.get("result", [])
                if results and len(results) > 0:
                    zone = results[0]
                    return {
                        "zone_id": zone.get("id"),
                        "name": zone.get("name"),
                        "status": zone.get("status"),
                        "account": zone.get("account", {}),
                    }
                return None
        except httpx.TimeoutException as te:
            raise CloudflareAPIError("Cloudflare zone discovery timed out. Please check network connectivity.") from te
        except CloudflareAPIError:
            raise
        except Exception as e:
            safe_err = _sanitize_error_text(str(e))
            raise CloudflareAPIError(f"Cloudflare zone query exception: {safe_err[:200]}") from e

    async def get_dns_record(
        self,
        token: str,
        zone_id: str,
        record_type: str,
        host: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find existing DNS record matching exact host and record_type.
        Endpoint: GET /client/v4/zones/{zone_id}/dns_records?type={type}&name={host}
        """
        url = f"{CLOUDFLARE_BASE_URL}/zones/{zone_id}/dns_records"
        params = {"type": record_type.upper(), "name": host.strip().lower()}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(url, headers=self._headers(token), params=params)
                if res.status_code != 200:
                    safe_err = _sanitize_error_text(res.text)
                    raise CloudflareAPIError(f"Failed to inspect Cloudflare DNS records (HTTP {res.status_code}): {safe_err[:200]}")

                data = res.json()
                records = data.get("result", [])
                if records and len(records) > 0:
                    rec = records[0]
                    return {
                        "id": rec.get("id"),
                        "type": rec.get("type"),
                        "name": rec.get("name"),
                        "content": rec.get("content"),
                        "ttl": rec.get("ttl", 3600),
                        "proxied": rec.get("proxied", False),
                        "priority": rec.get("priority"),
                        "zone_id": zone_id,
                    }
                return None
        except httpx.TimeoutException as te:
            raise CloudflareAPIError("Cloudflare record lookup timed out.") from te
        except CloudflareAPIError:
            raise
        except Exception as e:
            safe_err = _sanitize_error_text(str(e))
            raise CloudflareAPIError(f"Cloudflare record query exception: {safe_err[:200]}") from e

    async def create_dns_record(
        self,
        token: str,
        zone_id: str,
        record_type: str,
        host: str,
        content: str,
        ttl: int = 3600,
        proxied: bool = False,
        priority: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Insert a new DNS record into Cloudflare zone.
        Endpoint: POST /client/v4/zones/{zone_id}/dns_records
        """
        url = f"{CLOUDFLARE_BASE_URL}/zones/{zone_id}/dns_records"
        payload: Dict[str, Any] = {
            "type": record_type.upper(),
            "name": host.strip().lower(),
            "content": content.strip(),
            "ttl": ttl or 3600,
            "proxied": False if record_type.upper() in ("TXT", "MX", "NS", "SRV") else proxied,
        }
        if priority is not None and record_type.upper() == "MX":
            payload["priority"] = priority

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, headers=self._headers(token), json=payload)
                data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}

                if res.status_code in (200, 201) and data.get("success"):
                    rec = data.get("result", {})
                    return {
                        "id": rec.get("id"),
                        "type": rec.get("type"),
                        "name": rec.get("name"),
                        "content": rec.get("content"),
                        "ttl": rec.get("ttl", 3600),
                        "proxied": rec.get("proxied", False),
                        "zone_id": zone_id,
                    }

                safe_err = _sanitize_error_text(res.text)
                errors = data.get("errors", [])
                raise CloudflareAPIError(
                    f"Cloudflare rejected record insertion (HTTP {res.status_code}): {safe_err[:200]}",
                    status_code=res.status_code,
                    error_details=errors,
                )
        except httpx.TimeoutException as te:
            raise CloudflareAPIError("Cloudflare record creation timed out.") from te
        except CloudflareAPIError:
            raise
        except Exception as e:
            safe_err = _sanitize_error_text(str(e))
            raise CloudflareAPIError(f"Cloudflare creation communication error: {safe_err[:200]}") from e

    async def update_dns_record(
        self,
        token: str,
        zone_id: str,
        record_id: str,
        record_type: str,
        host: str,
        content: str,
        ttl: int = 3600,
        proxied: bool = False,
        priority: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update an existing DNS record in Cloudflare zone.
        Endpoint: PUT /client/v4/zones/{zone_id}/dns_records/{record_id}
        """
        url = f"{CLOUDFLARE_BASE_URL}/zones/{zone_id}/dns_records/{record_id}"
        payload: Dict[str, Any] = {
            "type": record_type.upper(),
            "name": host.strip().lower(),
            "content": content.strip(),
            "ttl": ttl or 3600,
            "proxied": False if record_type.upper() in ("TXT", "MX", "NS", "SRV") else proxied,
        }
        if priority is not None and record_type.upper() == "MX":
            payload["priority"] = priority

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.put(url, headers=self._headers(token), json=payload)
                data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}

                if res.status_code in (200, 201) and data.get("success"):
                    rec = data.get("result", {})
                    return {
                        "id": rec.get("id"),
                        "type": rec.get("type"),
                        "name": rec.get("name"),
                        "content": rec.get("content"),
                        "ttl": rec.get("ttl", 3600),
                        "proxied": rec.get("proxied", False),
                        "zone_id": zone_id,
                    }

                safe_err = _sanitize_error_text(res.text)
                raise CloudflareAPIError(
                    f"Cloudflare rejected record update (HTTP {res.status_code}): {safe_err[:200]}",
                    status_code=res.status_code,
                    error_details=data.get("errors", []),
                )
        except httpx.TimeoutException as te:
            raise CloudflareAPIError("Cloudflare record update timed out.") from te
        except CloudflareAPIError:
            raise
        except Exception as e:
            safe_err = _sanitize_error_text(str(e))
            raise CloudflareAPIError(f"Cloudflare update communication error: {safe_err[:200]}") from e

    async def delete_dns_record(
        self,
        token: str,
        zone_id: str,
        record_id: str,
    ) -> bool:
        """
        Delete a DNS record from Cloudflare zone (used during rollback of inserted records).
        Endpoint: DELETE /client/v4/zones/{zone_id}/dns_records/{record_id}
        """
        url = f"{CLOUDFLARE_BASE_URL}/zones/{zone_id}/dns_records/{record_id}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.delete(url, headers=self._headers(token))
                data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}

                if res.status_code in (200, 204) and (data.get("success") or res.status_code == 204):
                    logger.info(f"Cloudflare DNS record {record_id} deleted successfully.")
                    return True

                safe_err = _sanitize_error_text(res.text)
                raise CloudflareAPIError(
                    f"Cloudflare rejected record deletion (HTTP {res.status_code}): {safe_err[:200]}",
                    status_code=res.status_code,
                    error_details=data.get("errors", []),
                )
        except httpx.TimeoutException as te:
            raise CloudflareAPIError("Cloudflare record deletion timed out.") from te
        except CloudflareAPIError:
            raise
        except Exception as e:
            safe_err = _sanitize_error_text(str(e))
            raise CloudflareAPIError(f"Cloudflare delete communication error: {safe_err[:200]}") from e


cloudflare_client = CloudflareClient()
