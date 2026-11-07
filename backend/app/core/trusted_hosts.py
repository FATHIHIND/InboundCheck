"""Exact host configuration for the API, independent of forwarded client headers."""
import os
import re

_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def get_allowed_hosts(config):
    environment = (config.ENVIRONMENT or "").strip().lower()
    staging = bool(config.STAGING_MODE) or os.getenv("STAGING_MODE", "").strip().lower() in {"1", "true", "yes"}
    local = environment in {"development", "test", "testing"} and not staging
    configured = list(getattr(config, "ALLOWED_HOSTS", []))
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        configured.append(railway_domain)
    result = []
    for value in configured:
        host = str(value).strip().lower()
        if not host or len(host) > 253 or not _HOST.fullmatch(host):
            raise ValueError("ALLOWED_HOSTS requires exact DNS names or IPv4 addresses, without wildcards, schemes or ports")
        if host not in result:
            result.append(host)
    if local:
        for host in ("localhost", "127.0.0.1"):
            if host not in result:
                result.append(host)
        if environment in {"test", "testing"}:
            result.extend(host for host in ("test", "testserver") if host not in result)
    if not result:
        raise ValueError("Deployment requires ALLOWED_HOSTS or its exact RAILWAY_PUBLIC_DOMAIN")
    return result
