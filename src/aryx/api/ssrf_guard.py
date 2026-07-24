"""Shared SSRF guard for any route that lets a caller supply an outbound URL.

Single source of truth for the private/reserved-address blocklist — used by
both the REST API ingest form (rest_ingest_api.py) and the CPQ share-config
route (share_config_api.py). Two independent copies of this logic risk
silently drifting out of sync; import from here instead of re-deriving it.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# Hop-by-hop and host-override headers that must never be forwarded to
# third-party endpoints — prevents header injection attacks.
BLOCKED_HEADERS = frozenset({
    "host", "connection", "transfer-encoding", "upgrade",
    "proxy-authorization", "proxy-authenticate", "te", "trailers",
})

# RFC-1918, loopback, and cloud IMDS ranges blocked to prevent SSRF.
BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0",
                            "metadata.google.internal"})
PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / IMDS
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def check_outbound_url(v: str) -> str:
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url must use http or https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("url must include a hostname")
    if host in BLOCKED_HOSTS:
        raise ValueError(f"url targets a blocked host: {host}")
    try:
        addr = ipaddress.ip_address(host)
        if any(addr in net for net in PRIVATE_NETS):
            raise ValueError(f"url targets a private or reserved address: {host}")
    except ValueError as exc:
        if "url targets" in str(exc):
            raise
        # Not an IP literal — hostname allowed; DNS resolved at request time
    return v


def check_outbound_headers(v: dict[str, str]) -> dict[str, str]:
    bad = {k for k in v if k.lower() in BLOCKED_HEADERS}
    if bad:
        raise ValueError(f"headers may not include: {sorted(bad)}")
    return v
