"""Network security utilities for outbound URL validation and token redaction."""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

BLOCKED_HOSTNAMES = {"localhost", "loopback", "localhost.localdomain"}
ALLOWED_SCHEMES = {"http", "https"}


def validate_outbound_url(url: str) -> str:
    """Validate an outbound URL to prevent SSRF and unsafe protocol execution.

    Enforces:
    - Allowed schemes: http, https only.
    - Rejection of localhost, loopback, and cloud metadata hostnames.
    - Rejection of private, loopback, and link-local IP addresses.

    Args:
        url: URL string to inspect.

    Returns:
        The validated clean URL string.

    Raises:
        ValueError: If URL uses a disallowed scheme or points to an internal/private address.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")

    cleaned_url = url.strip()
    parsed = urlparse(cleaned_url)

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme '{scheme}'. Only HTTP and HTTPS are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL does not contain a valid hostname.")

    lower_host = hostname.lower()

    # Block well-known internal hostnames
    if lower_host in BLOCKED_HOSTNAMES or lower_host.endswith(".local") or lower_host.endswith(".internal"):
        raise ValueError(f"Access to local or internal host '{hostname}' is blocked.")

    # Check if host is a direct IP address
    try:
        ip = ipaddress.ip_address(lower_host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"Access to private or restricted IP address '{hostname}' is blocked.")
        return cleaned_url
    except ValueError as exc:
        if "does not appear to be an IPv4 or IPv6 address" not in str(exc):
            raise

    # For standard domain names, resolve to IP to verify it does not point to internal/loopback range
    try:
        resolved_ips = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for family, _, _, _, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError(f"Hostname '{hostname}' resolves to a restricted IP address ({ip_str}).")
    except socket.gaierror:
        # DNS resolution failure will be handled gracefully by subsequent HTTP requests
        pass

    return cleaned_url


def redact_url_for_logging(url: str) -> str:
    """Strip query parameters and userinfo from a URL for safe logging.

    Prevents leaking temporary authentication tokens, API keys, or session secrets.

    Args:
        url: Full URL string.

    Returns:
        Sanitized URL string containing only scheme, host, and path.
    """
    if not url or not isinstance(url, str):
        return ""

    try:
        parsed = urlparse(url.strip())
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        return f"{parsed.scheme}://{host}{port}{parsed.path}"
    except Exception:
        return "[redacted-url]"
