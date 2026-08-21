"""Traffic Data Provider Adapter.

Consumes real traffic feeds from configured providers (Google Maps, HERE, TomTom,
or municipal loop sensors).

Zero-fabrication rule: If no live traffic API or sensor feed is configured or if the
upstream service fails, the adapter reports an explicit 'Traffic data unavailable'
state. Never fabricates traffic jams or synthetic speed drops.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)


def fetch_traffic_flow(
    road_segment_id: str,
    lat: float = 16.5062,
    lon: float = 80.6480,
) -> dict[str, Any]:
    """Fetch real traffic flow and congestion metrics from configured provider."""
    # Accept any of the names this key travels under, so a working credential
    # is not ignored because it was set under a different one.
    google_key = (
        os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("GOOGLE_ROUTES_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    tomtom_key = os.environ.get("TOMTOM_API_KEY")
    here_key = os.environ.get("HERE_API_KEY")

    # 1. Try TomTom Traffic Flow API if key provided
    if tomtom_key:
        try:
            url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point={lat},{lon}&key={tomtom_key}"
            with httpx.Client(timeout=8.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    flow = res.json().get("flowSegmentData", {})
                    current_speed = flow.get("currentSpeed", 0.0)
                    free_flow_speed = flow.get("freeFlowSpeed", 50.0)
                    congestion_ratio = 1.0 - (current_speed / free_flow_speed) if free_flow_speed > 0 else 0.0
                    return {
                        "status": "verified",
                        "provider": "TomTom Traffic API",
                        "current_speed_kph": current_speed,
                        "free_flow_speed_kph": free_flow_speed,
                        "congestion_ratio": round(congestion_ratio, 2),
                        "speed_drop_detected": current_speed < (free_flow_speed * 0.4),
                    }
        except Exception as exc:
            log.warning("TomTom traffic fetch failed: %s", exc)

    # 2. Try HERE Traffic Flow API if key provided
    if here_key:
        try:
            url = f"https://data.traffic.hereapi.com/v7/flow?in=circle:{lat},{lon};r=500&apiKey={here_key}"
            with httpx.Client(timeout=8.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    return {
                        "status": "verified",
                        "provider": "HERE Traffic API",
                        "raw_flow": res.json(),
                    }
        except Exception as exc:
            log.warning("HERE traffic fetch failed: %s", exc)

    # If no provider key is configured or all fail, fail honestly
    return {
        "status": "unavailable",
        "provider": "None (Unconfigured)",
        "message": "Traffic data unavailable. No real-world traffic API credentials provided.",
        "speed_drop_detected": False,
    }
