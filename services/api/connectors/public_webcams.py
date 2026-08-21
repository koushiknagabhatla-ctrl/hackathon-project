"""Public webcam discovery — the second path when no camera is registered.

Andhra Pradesh traffic cameras are operated by the state police and the Real
Time Governance Society. They are not published as an open stream, so the
first path (a feed an operator registers, with the authority that granted
access recorded against it) is the one that shows a city's own junctions.

This module is the fallback: directories of webcams whose operators chose to
publish them — tourism boards, ports, universities, weather stations, highway
authorities. Windy's webcam API is the index used because it is licensed,
documented, and carries the operator and the publication URL for every entry,
so anything shown here can be traced back to whoever put it online.

A line worth stating plainly, because it is the whole reason this module looks
the way it does:

    Reachable is not the same as public.

Search engines that index unsecured cameras — devices left on default
credentials by people who did not intend to broadcast — are not used here and
should not be. A private camera does not become a public feed because it
answers on port 554. Every source in this module is one an operator
deliberately published, and each result carries that provenance so the
distinction survives into the UI.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from services.api.connectors import registry

log = logging.getLogger("auralis.connectors.public_webcams")

WINDY_WEBCAMS_V3 = "https://api.windy.com/webcams/api/v3/webcams"
CACHE_TTL_S = 900  # a webcam directory does not churn; 15 minutes is honest
MAX_RADIUS_KM = 250.0  # measured: the upstream 400s at 500


@dataclass
class PublicWebcam:
    id: str
    title: str
    lat: float
    lon: float
    distance_km: float | None
    city: str
    region: str
    country: str
    preview_url: str | None       # still image, refreshed by the operator
    player_url: str | None        # embeddable live player, when published
    detail_url: str | None        # the directory page, for provenance
    last_updated: str | None
    source: str = "windy_webcams"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def configured() -> bool:
    return bool(os.environ.get("WINDY_WEBCAMS_API_KEY"))


def _haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _parse(item: dict[str, Any], origin: tuple[float, float] | None = None) -> PublicWebcam | None:
    loc = item.get("location") or {}
    images = item.get("images") or {}
    urls = item.get("urls") or {}
    current = images.get("current") or {}

    lat, lon = loc.get("latitude"), loc.get("longitude")
    if lat is None or lon is None:
        return None

    return PublicWebcam(
        id=str(item.get("webcamId") or item.get("id") or ""),
        title=str(item.get("title") or "Untitled camera"),
        lat=float(lat),
        lon=float(lon),
        distance_km=(
            round(float(item["distance"]), 2) if item.get("distance") is not None
            else (round(_haversine_km(origin[0], origin[1], float(lat), float(lon)), 2)
                  if origin else None)
        ),
        city=str(loc.get("city") or ""),
        region=str(loc.get("region") or ""),
        country=str(loc.get("country") or ""),
        preview_url=current.get("preview") or current.get("thumbnail"),
        player_url=((urls.get("player") or {}).get("live")
                    if isinstance(urls.get("player"), dict) else None),
        detail_url=((urls.get("detail") or {}).get("webcam")
                    if isinstance(urls.get("detail"), dict) else urls.get("detail")),
        last_updated=item.get("lastUpdatedOn"),
    )


def find_nearby(
    lat: float,
    lon: float,
    radius_km: float = 100.0,
    limit: int = 12,
) -> dict[str, Any]:
    """Publicly published webcams near a point.

    Returns a structured answer in every case. "No key configured", "the index
    had nothing here" and "the index could not be read" are three different
    facts and each is reported as itself.
    """
    key = os.environ.get("WINDY_WEBCAMS_API_KEY")
    if not key:
        return {
            "status": "unconfigured",
            "count": 0,
            "webcams": [],
            "detail": (
                "WINDY_WEBCAMS_API_KEY is not set. This is the fallback index of "
                "webcams whose operators published them; without a key it is skipped "
                "and only registered cameras are shown."
            ),
            "fetched_at": datetime.now(UTC).isoformat(),
        }

    # The upstream rejects >= 500 km with HTTP 400; 250 is the usable ceiling.
    radius_km = max(1.0, min(float(radius_km), MAX_RADIUS_KM))

    cache_key = f"webcams:{lat:.3f}:{lon:.3f}:{radius_km}:{limit}"
    cached = registry.cache_get(cache_key, CACHE_TTL_S)
    if cached is not None and not cached.get("stale"):
        return cached["payload"]

    try:
        with httpx.Client(timeout=20, headers={
            "x-windy-api-key": key,
            "User-Agent": registry.USER_AGENT,
        }) as c:
            r = c.get(WINDY_WEBCAMS_V3, params={
                "nearby": f"{lat},{lon},{int(radius_km)}",
                "limit": limit,
                "include": "images,location,urls",
            })
        if r.status_code in (401, 403):
            return {"status": "error", "count": 0, "webcams": [],
                    "detail": f"Windy rejected the key (HTTP {r.status_code}).",
                    "fetched_at": datetime.now(UTC).isoformat()}
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:
        log.warning("public webcam index unavailable: %s", exc)
        return {"status": "error", "count": 0, "webcams": [],
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "fetched_at": datetime.now(UTC).isoformat()}

    cams = [c for c in (_parse(i, (lat, lon)) for i in (payload.get("webcams") or [])) if c]
    cams.sort(key=lambda c: (c.distance_km if c.distance_km is not None else 9e9))

    if not cams:
        return {
            "status": "no_coverage",
            "count": 0,
            "webcams": [],
            "radius_km": radius_km,
            "detail": (
                f"The index is reachable but publishes no webcam within "
                f"{int(radius_km)} km. It carries no camera inside Andhra Pradesh; "
                f"the nearest published feeds are in Hyderabad and Chennai. A feed "
                f"for this city has to be registered directly."
            ),
            "fetched_at": datetime.now(UTC).isoformat(),
        }

    result = {
        "status": "ok",
        "count": len(cams),
        "radius_km": radius_km,
        "webcams": [c.to_dict() for c in cams],
        "provenance": (
            "Cameras published by their operators and indexed by Windy. Each entry "
            "links to its directory page. This index does not include private or "
            "unsecured cameras."
        ),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    if cams:
        registry.cache_put(cache_key, result, result["fetched_at"])
    return result
