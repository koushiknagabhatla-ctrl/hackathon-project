"""Edge protections: rate limiting, body caps, response headers, optional
shared-secret gate.

The principal header alone is role *selection*, not authentication. On a LAN
or a public host, anyone who can reach the port can claim any role. Setting
AURALIS_API_TOKEN turns the API into a closed door: every request must carry
the secret, and the principal header only chooses a role behind it.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

# Requests per window, per client, per bucket class.
# A dashboard page fans out 10-20 reads on load, and an operator moving through
# screens can legitimately spend hundreds in a minute. These are set to stop
# scraping and brute force without throttling normal use.
READ_LIMIT = int(os.environ.get("AURALIS_RATE_READ", "600"))      # per minute
WRITE_LIMIT = int(os.environ.get("AURALIS_RATE_WRITE", "60"))     # per minute
WINDOW_S = 60.0
MAX_BODY_BYTES = int(os.environ.get("AURALIS_MAX_BODY", str(2 * 1024 * 1024)))

# Endpoints that must never be throttled: the stream is long-lived and health
# is what a load balancer polls.
EXEMPT_PREFIXES = ("/v1/stream", "/v1/health", "/docs", "/openapi.json", "/redoc")

_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # X-Forwarded-For only when a trusted proxy sets it; otherwise the socket.
    if os.environ.get("AURALIS_TRUST_PROXY") == "true":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allowed(key: str, bucket: str, limit: int) -> tuple[bool, int]:
    now = time.monotonic()
    q = _hits[(key, bucket)]
    cutoff = now - WINDOW_S
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= limit:
        retry = max(1, int(WINDOW_S - (now - q[0])))
        return False, retry
    q.append(now)
    return True, 0


def _prune() -> None:
    """Drop empty buckets so a long uptime cannot grow the dict without bound."""
    if len(_hits) < 4096:
        return
    for k in [k for k, v in _hits.items() if not v]:
        _hits.pop(k, None)


async def security_middleware(request: Request, call_next: Callable):
    path = request.url.path

    # ---- shared secret ------------------------------------------------
    token = os.environ.get("AURALIS_API_TOKEN")
    if token and not path.startswith(("/v1/health", "/docs", "/openapi.json")):
        provided = request.headers.get("x-auralis-token", "")
        # compare_digest: constant time, so the secret cannot be guessed by timing
        if not hmac.compare_digest(provided, token):
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized",
                                   "message": "A valid X-Auralis-Token is required."}},
            )

    # ---- body cap -----------------------------------------------------
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": {"code": "payload_too_large",
                               "message": f"Body exceeds {MAX_BODY_BYTES} bytes."}},
        )

    # ---- rate limit ---------------------------------------------------
    if not path.startswith(EXEMPT_PREFIXES):
        write = request.method in ("POST", "PUT", "PATCH", "DELETE")
        limit = WRITE_LIMIT if write else READ_LIMIT
        ok, retry = _allowed(_client_key(request), "w" if write else "r", limit)
        _prune()
        if not ok:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry)},
                content={"error": {"code": "rate_limited",
                                   "message": f"Too many requests. Retry in {retry}s.",
                                   "limit_per_minute": limit}},
            )

    response = await call_next(request)

    # ---- response hardening -------------------------------------------
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
    # The API returns JSON, never markup, so nothing here should ever execute.
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    # MutableHeaders has no .pop(); delete only if present.
    if "server" in response.headers:
        del response.headers["server"]
    return response
