"""SSRF protection: decides which URLs the monitor is allowed to contact.

The same policy is applied when a target is registered/updated *and* again right
before every check, so a changed allowlist takes effect immediately.
"""

import ipaddress
import re
from collections.abc import Collection

import httpx

ALLOWED_SCHEMES = frozenset({"http", "https"})
_FORBIDDEN_CHARS = re.compile(r"[\s\\\x00-\x1f\x7f]")


class UnsafeURLError(ValueError):
    """Raised when a URL violates the monitoring destination policy."""


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def validate_target_url(raw_url: str, allowed_hosts: Collection[str]) -> str:
    """Validate a monitoring URL and return its normalized form.

    Parsing is done with httpx — the same parser that performs the request — so
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
    if _is_ip_literal(host):
        raise UnsafeURLError("IP address destinations are not allowed; use an allowlisted hostname")
    if host not in allowed_hosts:
        raise UnsafeURLError(f"host '{host}' is not in the monitoring allowlist")

    return str(url.copy_with(fragment=None))
