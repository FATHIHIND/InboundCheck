"""
InboundCheck - Hardened Remote Asset HTTP Fetcher
=================================================
SSRF-immune, socket-pinned, size-capped asynchronous HTTP client for fetching
external BIMI SVG logos and VMC certificates.
"""

import hashlib
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Optional, List, Set, Tuple

import httpx

from app.core.config import settings
from app.services.security.url_policy import UrlPolicy, UrlPolicyViolation
from app.services.security.safe_dns_resolver import SafeDnsResolver, DnsSecurityViolation

logger = logging.getLogger("SafeHttpFetcher")


@dataclass
class SafeFetchResult:
    fetch_status: str  # "verified" | "rejected" | "failed"
    http_status: Optional[int]
    requested_url: str
    final_url: Optional[str]
    pinned_ip: Optional[str]
    content_type: Optional[str]
    content_length_bytes: int
    content_sha256: Optional[str]
    redirect_count: int
    failure_code: Optional[str]
    error_message: Optional[str]
    body: Optional[bytes] = None


class SafeHttpFetcher:
    """
    Hardened HTTP client enforcing:
    - Zero trust of OS environment proxy variables (trust_env=False)
    - Socket-level IP pinning to eliminate DNS rebinding
    - Strict manual redirect tracking (max 3 hops, Anti-downgrade)
    - Early streaming termination at 500 KB limit
    - Cryptographic SHA-256 integrity digest computation
    """

    def __init__(
        self,
        max_bytes: int = settings.ASSET_FETCH_MAX_BYTES,
        max_redirects: int = settings.ASSET_FETCH_MAX_REDIRECTS,
        timeout: float = settings.ASSET_FETCH_TIMEOUT_SECONDS,
    ):
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.timeout = timeout

    async def fetch(
        self,
        url: str,
        asset_type: str = "bimi_logo",
        allowed_mime_prefixes: Optional[List[str]] = None,
    ) -> SafeFetchResult:
        """
        Execute security-hardened fetch of the remote asset.
        """
        requested_url = url.strip()
        current_url = requested_url
        redirect_count = 0
        visited_urls: Set[str] = set()
        pinned_ip: Optional[str] = None
        last_http_status: Optional[int] = None
        content_type: Optional[str] = None

        while True:
            # 1. Check redirect budget
            if redirect_count > self.max_redirects:
                return SafeFetchResult(
                    fetch_status="rejected",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=pinned_ip,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code="MAX_REDIRECTS_EXCEEDED",
                    error_message=f"Exceeded maximum allowed redirects ({self.max_redirects}).",
                )

            # 2. Check redirect loop
            if current_url in visited_urls:
                return SafeFetchResult(
                    fetch_status="rejected",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=pinned_ip,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code="REDIRECT_LOOP",
                    error_message=f"Circular redirect loop detected for URL: {current_url}",
                )

            visited_urls.add(current_url)

            # 3. URL Policy Validation
            try:
                norm_url, hostname, port = UrlPolicy.validate_and_normalize(current_url)
            except UrlPolicyViolation as upv:
                return SafeFetchResult(
                    fetch_status="rejected",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=pinned_ip,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code=upv.code,
                    error_message=upv.message,
                )

            # 4. Safe DNS Resolution & Public IP Pinning
            try:
                pinned_ip = SafeDnsResolver.resolve_pinned_ip(hostname, port)
            except DnsSecurityViolation as dsv:
                return SafeFetchResult(
                    fetch_status="rejected",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=dsv.ip or None,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code=dsv.code,
                    error_message=dsv.message,
                )

            # 5. Connect strictly to pinned IP with SNI verification and Host header
            parsed_u = urllib.parse.urlsplit(norm_url)
            path_query = parsed_u.path or "/"
            if parsed_u.query:
                path_query += f"?{parsed_u.query}"

            pinned_target_url = f"https://{pinned_ip}:{port}{path_query}"
            headers = {
                "Host": hostname,
                "User-Agent": "InboundCheck-AssetValidator/3.0 (+https://inboundcheck.com/compliance)",
                "Accept": "image/svg+xml,application/xml,text/xml,*/*;q=0.8" if asset_type == "bimi_logo" else "*/*",
            }

            try:
                async with httpx.AsyncClient(
                    verify=True,
                    trust_env=False,
                    timeout=self.timeout,
                    follow_redirects=False,  # Manual redirect control
                ) as client:
                    async with client.stream(
                        "GET",
                        pinned_target_url,
                        headers=headers,
                        extensions={"sni_hostname": hostname},
                    ) as response:
                        last_http_status = response.status_code
                        content_type = response.headers.get("Content-Type", "")

                        # Handle redirects manually
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location:
                                return SafeFetchResult(
                                    fetch_status="failed",
                                    http_status=last_http_status,
                                    requested_url=requested_url,
                                    final_url=current_url,
                                    pinned_ip=pinned_ip,
                                    content_type=content_type,
                                    content_length_bytes=0,
                                    content_sha256=None,
                                    redirect_count=redirect_count,
                                    failure_code="MISSING_REDIRECT_LOCATION",
                                    error_message="Redirect status received without Location header.",
                                )

                            # Resolve target location
                            next_url = urllib.parse.urljoin(current_url, location)

                            # Reject HTTPS to HTTP downgrades
                            if next_url.lower().startswith("http://"):
                                return SafeFetchResult(
                                    fetch_status="rejected",
                                    http_status=last_http_status,
                                    requested_url=requested_url,
                                    final_url=next_url,
                                    pinned_ip=pinned_ip,
                                    content_type=content_type,
                                    content_length_bytes=0,
                                    content_sha256=None,
                                    redirect_count=redirect_count,
                                    failure_code="HTTPS_DOWNGRADE_PROHIBITED",
                                    error_message=f"Redirect attempted to downgrade to plain HTTP: {next_url}",
                                )

                            current_url = next_url
                            redirect_count += 1
                            continue  # Loop to re-evaluate URL policy & re-resolve DNS

                        # If non-200, return failed
                        if response.status_code != 200:
                            return SafeFetchResult(
                                fetch_status="failed",
                                http_status=last_http_status,
                                requested_url=requested_url,
                                final_url=current_url,
                                pinned_ip=pinned_ip,
                                content_type=content_type,
                                content_length_bytes=0,
                                content_sha256=None,
                                redirect_count=redirect_count,
                                failure_code="HTTP_ERROR",
                                error_message=f"HTTP response returned non-200 code: {response.status_code}",
                            )

                        # Stream body with strict byte cap
                        body_chunks: List[bytes] = []
                        total_bytes = 0

                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            total_bytes += len(chunk)
                            if total_bytes > self.max_bytes:
                                return SafeFetchResult(
                                    fetch_status="rejected",
                                    http_status=last_http_status,
                                    requested_url=requested_url,
                                    final_url=current_url,
                                    pinned_ip=pinned_ip,
                                    content_type=content_type,
                                    content_length_bytes=total_bytes,
                                    content_sha256=None,
                                    redirect_count=redirect_count,
                                    failure_code="PAYLOAD_TOO_LARGE",
                                    error_message=f"Remote asset exceeds maximum allowable size of {self.max_bytes // 1024} KB.",
                                )
                            body_chunks.append(chunk)

                        full_body = b"".join(body_chunks)
                        content_sha256 = hashlib.sha256(full_body).hexdigest()

                        # MIME check
                        if allowed_mime_prefixes:
                            lower_ct = (content_type or "").lower()
                            if not any(lower_ct.startswith(prefix) for prefix in allowed_mime_prefixes):
                                return SafeFetchResult(
                                    fetch_status="rejected",
                                    http_status=last_http_status,
                                    requested_url=requested_url,
                                    final_url=current_url,
                                    pinned_ip=pinned_ip,
                                    content_type=content_type,
                                    content_length_bytes=len(full_body),
                                    content_sha256=content_sha256,
                                    redirect_count=redirect_count,
                                    failure_code="INVALID_MIME_TYPE",
                                    error_message=f"Content-Type '{content_type}' is not allowed for {asset_type}.",
                                    body=full_body,
                                )

                        return SafeFetchResult(
                            fetch_status="verified",
                            http_status=last_http_status,
                            requested_url=requested_url,
                            final_url=current_url,
                            pinned_ip=pinned_ip,
                            content_type=content_type,
                            content_length_bytes=len(full_body),
                            content_sha256=content_sha256,
                            redirect_count=redirect_count,
                            failure_code=None,
                            error_message=None,
                            body=full_body,
                        )

            except httpx.TimeoutException:
                return SafeFetchResult(
                    fetch_status="failed",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=pinned_ip,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code="CONNECTION_TIMEOUT",
                    error_message=f"Connection timed out after {self.timeout}s to {pinned_ip}.",
                )
            except httpx.ConnectError as ce:
                return SafeFetchResult(
                    fetch_status="failed",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=pinned_ip,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code="CONNECTION_REFUSED_OR_TLS_ERROR",
                    error_message=str(ce),
                )
            except Exception as e:
                logger.error(f"Unexpected error fetching {current_url}: {e}", exc_info=True)
                return SafeFetchResult(
                    fetch_status="failed",
                    http_status=last_http_status,
                    requested_url=requested_url,
                    final_url=current_url,
                    pinned_ip=pinned_ip,
                    content_type=content_type,
                    content_length_bytes=0,
                    content_sha256=None,
                    redirect_count=redirect_count,
                    failure_code="UNEXPECTED_FETCH_ERROR",
                    error_message=str(e),
                )


safe_http_fetcher = SafeHttpFetcher()
