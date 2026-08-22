"""Approximate location from an IP address, resolved server-side.

Doing this in the browser meant three cross-origin calls that the app's own
CSP refused, and that any privacy extension would block anyway. Server-side it
is one same-origin call, and the providers only ever see this service.

Accuracy is city-level at best and is often the ISP's exchange rather than the
user, so every result says so.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger("auralis.connectors.ip_geo")

# Coarse by nature: never present this as a fix.
IP_ACCURACY_M = 25000.0
_CACHE_TTL_S = 900.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

PROVIDERS = [
    ("ipwho.is", "https://ipwho.is/{ip}"),
    ("geojs", "https://get.geojs.io/v1/ip/geo/{ip}.json"),
    ("ipapi.co", "https://ipapi.co/{ip}/json/"),
]


def _is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved)
    except ValueError:
        return False


def client_ip(headers: dict[str, str], socket_host: str | None) -> str | None:
    """The caller's address. Forwarded headers are only trusted behind a proxy."""
    if os.environ.get("AURALIS_TRUST_PROXY") == "true":
        fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
        if fwd:
            first = fwd.split(",")[0].strip()
            if _is_public(first):
                return first
    if socket_host and _is_public(socket_host):
        return socket_host
    return None


def _parse(name: str, d: dict[str, Any]) -> dict[str, Any] | None:
    lat = d.get("latitude") if d.get("latitude") is not None else d.get("lat")
    lon = d.get("longitude") if d.get("longitude") is not None else d.get("lon")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {
        "lat": lat,
        "lon": lon,
        "city": d.get("city") or d.get("cityName") or "",
        "region": d.get("region") or d.get("regionName") or d.get("region_name") or "",
        "country": d.get("country") or d.get("country_name") or "",
        "provider": name,
    }


def locate(ip: str | None) -> dict[str, Any]:
    """Resolve an IP to a coarse position.

    `ip` None or private means "look up whoever is asking", which on a local
    machine resolves this host's own public address — the right answer there.
    """
    key = ip or "self"
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_S:
        return hit[1]

    errors: list[str] = []
    for name, tpl in PROVIDERS:
        # An empty {ip} makes every provider resolve the caller, which here is
        # this service.
        url = tpl.format(ip=ip if ip and _is_public(ip) else "")
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True,
                              headers={"User-Agent": "Auralis-CivicIntelligence/1.0"}) as c:
                r = c.get(url)
            if r.status_code != 200:
                errors.append(f"{name}: HTTP {r.status_code}")
                continue
            parsed = _parse(name, r.json())
            if not parsed:
                errors.append(f"{name}: no coordinates")
                continue
            result = {
                "status": "ok",
                "accuracy_m": IP_ACCURACY_M,
                "source": "ip",
                "note": "City-level approximation from the network address, not a device fix.",
                **parsed,
            }
            _cache[key] = (time.time(), result)
            return result
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}")

    return {
        "status": "unavailable",
        "source": "ip",
        "detail": "; ".join(errors) or "no provider answered",
    }
