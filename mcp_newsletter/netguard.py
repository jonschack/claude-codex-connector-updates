from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlparse


def _allowlist() -> set:
    raw = os.environ.get("MCP_NEWSLETTER_SSRF_ALLOW", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_safe_url(url: str) -> Tuple[bool, str]:
    """Return (ok, reason). ok=False means do not connect to this URL.

    Blocks non-http(s) schemes and any host that resolves to a loopback,
    private, link-local, reserved, multicast, or unspecified address. Hosts
    listed in MCP_NEWSLETTER_SSRF_ALLOW bypass the address check.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported scheme: {parsed.scheme or 'none'}"
    host = parsed.hostname
    if not host:
        return False, "missing host"

    allow = _allowlist()
    if host in allow:
        return True, ""

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return False, f"dns resolution failed: {exc}"

    for info in infos:
        addr = info[4][0]
        if addr in allow:
            continue
        ip = ipaddress.ip_address(addr.split("%")[0])  # strip zone id if present
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"blocked address: {ip}"
    return True, ""


MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def max_response_bytes() -> int:
    raw = os.environ.get("MCP_NEWSLETTER_MAX_RESPONSE_BYTES")
    if raw and raw.isdigit():
        return int(raw)
    return MAX_RESPONSE_BYTES


def read_capped(resp, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read at most `limit` bytes; raise ValueError if the body is larger.

    `resp` is any object with a .read(n) method (an http.client.HTTPResponse
    or a BytesIO in tests).
    """
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"response exceeded {limit} bytes")
    return data


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0


RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def should_retry(
    policy: RetryPolicy,
    attempt: int,
    status: Optional[int],
    retry_after: Optional[float],
) -> Tuple[bool, float]:
    """Decide whether to retry. Returns (retry, delay_seconds).

    `attempt` is zero-based: 0 = first try just failed. `status` is the HTTP
    status, or None for a transport-level error. A 429/5xx (or None) is
    retryable until max_retries is reached. `retry_after`, when present,
    overrides the computed backoff delay.
    """
    if attempt >= policy.max_retries:
        return False, 0.0
    retryable = status is None or status in RETRYABLE_STATUSES
    if not retryable:
        return False, 0.0
    if retry_after is not None:
        return True, retry_after
    delay = min(policy.base_delay * (2 ** attempt), policy.max_delay)
    return True, delay
