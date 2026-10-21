"""SSRF protection: decides which URLs the monitor (and webhooks) may contact.

The same policy is applied when a target is registered/updated *and* again right
before every request, so a changed allowlist takes effect immediately.

Destinations must be either
- a hostname on the explicit hostname allowlist, or
- an IP address inside an explicitly allowlisted network (opt-in), and never a
  loopback, link-local (incl. cloud metadata 169.254.169.254), multicast,
  unspecified or reserved address, even if an allowlisted range contains it.
"""

import ipaddress
import re
from collections.abc import Collection

import httpx

ALLOWED_SCHEMES = frozenset({"http", "https"})
_FORBIDDEN_CHARS = re.compile(r"[\s\\\x00-\x1f\x7f]")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class UnsafeURLError(ValueError):
    """Raised when a URL violates the destination policy."""


def _parse_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _never_allowed(ip: IPAddress) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # judge ::ffff:127.0.0.1 as 127.0.0.1
    if ip.is_loopback:
        return "loopback addresses are never allowed"
    if ip.is_link_local:
        return "link-local addresses (incl. cloud metadata) are never allowed"
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "multicast, unspecified and reserved addresses are never allowed"
    return None


def validate_target_url(
    raw_url: str,
    allowed_hosts: Collection[str],
    allowed_networks: Collection[IPNetwork] = (),
) -> str:
    """Validate a destination URL and return its normalized form.

    Parsing is done with httpx, the same parser that performs the request, so
    there is no parser differential between validation and use.
    """
    if _FORBIDDEN_CHARS.search(raw_url):
        raise UnsafeURLError("URL contains whitespace, backslashes or control characters")

    try:
        url = httpx.URL(raw_url)
    except (httpx.InvalidURL, ValueError, TypeError) as exc:
        raise UnsafeURLError("URL is malformed") from exc

    if url.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("only http and https URLs are allowed")
    if url.userinfo:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")

    host = url.host.lower()
    if not host:
        raise UnsafeURLError("URL must include a hostname")

    ip = _parse_ip(host)
    if ip is not None:
        if (reason := _never_allowed(ip)) is not None:
            raise UnsafeURLError(reason)
        if not any(ip in network for network in allowed_networks):
            raise UnsafeURLError(
                "IP address destinations are not allowed unless the address is inside "
                "ALLOWED_TARGET_NETWORKS; prefer an allowlisted hostname"
            )
    elif host not in allowed_hosts:
        raise UnsafeURLError(f"host '{host}' is not in the monitoring allowlist")

    return str(url.copy_with(fragment=None))
