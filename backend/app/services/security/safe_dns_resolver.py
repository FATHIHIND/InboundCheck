"""
InboundCheck - Safe DNS Resolver with Anti-SSRF Enforcement
===========================================================
Performs pre-connection DNS resolution and strictly blocks non-routable, private,
loopback, link-local, carrier-grade NAT, and cloud metadata IP addresses.
"""

import socket
import ipaddress
import logging
from typing import List

logger = logging.getLogger("SafeDnsResolver")


BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),          # Private IPv4 (RFC 1918)
    ipaddress.ip_network("100.64.0.0/10"),       # Carrier-Grade NAT (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback IPv4
    ipaddress.ip_network("169.254.0.0/16"),      # Link-Local / Cloud Metadata
    ipaddress.ip_network("172.16.0.0/12"),       # Private IPv4 (RFC 1918)
    ipaddress.ip_network("192.168.0.0/16"),      # Private IPv4 (RFC 1918)
    ipaddress.ip_network("192.0.2.0/24"),        # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.51.100.0/24"),     # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),         # Multicast
    ipaddress.ip_network("240.0.0.0/4"),         # Reserved
    ipaddress.ip_network("::1/128"),             # IPv6 Loopback
    ipaddress.ip_network("::/128"),              # Unspecified
    ipaddress.ip_network("fc00::/7"),            # IPv6 Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),           # IPv6 Link-Local
    ipaddress.ip_network("::ffff:0:0/96"),       # IPv4-mapped IPv6
    ipaddress.ip_network("2001:db8::/32"),       # Documentation IPv6
]


class DnsSecurityViolation(Exception):
    """Raised when DNS resolution yields a non-routable or restricted IP."""
    def __init__(self, code: str, message: str, ip: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ip = ip


class SafeDnsResolver:
    """
    Validates domain DNS targets and pins a safe, routable public IP.
    """

    @classmethod
    def is_ip_restricted(cls, ip_str: str) -> bool:
        """Check if an IP string belongs to any blocked/private CIDR."""
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            return any(ip_obj in net for net in BLOCKED_NETWORKS)
        except ValueError:
            return True

    @classmethod
    def resolve_public_ips(cls, hostname: str, port: int = 443) -> List[str]:
        """
        Resolve all A and AAAA records for the hostname.
        If ANY address is within restricted ranges or metadata, raises DnsSecurityViolation.
        Returns a list of validated public IP strings.
        """
        try:
            addr_info = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except Exception as e:
            raise DnsSecurityViolation("DNS_RESOLUTION_FAILED", f"Could not resolve host '{hostname}': {str(e)}")

        if not addr_info:
            raise DnsSecurityViolation("NO_DNS_RECORDS", f"No address records found for '{hostname}'")

        resolved_ips: List[str] = []
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            if ip_str not in resolved_ips:
                resolved_ips.append(ip_str)

        # Audit all resolved addresses against Anti-SSRF policies
        for ip in resolved_ips:
            if cls.is_ip_restricted(ip):
                raise DnsSecurityViolation(
                    "RESTRICTED_IP_BLOCKED",
                    f"Resolved IP '{ip}' for hostname '{hostname}' belongs to a private, loopback, or metadata subnet.",
                    ip=ip,
                )

        return resolved_ips

    @classmethod
    def resolve_pinned_ip(cls, hostname: str, port: int = 443) -> str:
        """
        Resolve and return a single pinned public IP address.
        """
        ips = cls.resolve_public_ips(hostname, port)
        if not ips:
            raise DnsSecurityViolation("NO_PUBLIC_IPS", f"No valid public IPs available for '{hostname}'")
        return ips[0]
