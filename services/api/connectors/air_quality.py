"""Air quality from OpenAQ v3 (https://api.openaq.org/v3).

Real monitoring stations. For India these are largely CPCB reference monitors
relayed by OpenAQ, plus low-cost sensors. OpenAQ is an AGGREGATOR, so the
connector's trust tier is `verified`, not `statutory` - we are not reading CPCB
directly and must not imply that we are. Each ingested reading carries the
OpenAQ location id, sensor id, provider name and a resolvable source URL, so the
station behind any number is checkable.

v3 requires a free API key in the `X-API-Key` header. Without OPENAQ_API_KEY set
this connector reports `unconfigured` - it does not fail loudly, and it
absolutely does not invent a reading. Register at https://explore.openaq.org/register

Response shapes below are taken from the published OpenAPI document at
https://api.openaq.org/openapi.json (fetched and read, not guessed):
    GET /v3/locations?coordinates=lat,lon&radius=<=25000
        -> {meta, results: [{id, name, locality, coordinates:{latitude,longitude},
                             provider:{name}, sensors:[{id, name,
                             parameter:{id,name,units,displayName}}], ...}]}
    GET /v3/locations/{id}/latest
        -> {meta, results: [{datetime:{utc,local}, value,
                             coordinates:{...}, sensorsId, locationsId}]}
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from services.api.connectors import registry
from services.api.core import ingest
from services.api.models import EventIn

log = logging.getLogger(__name__)

BASE = "https://api.openaq.org/v3"
MAX_RADIUS_M = 25000  # hard ceiling in the OpenAQ v3 schema


def _headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["OPENAQ_API_KEY"]}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def fetch_air_quality(
    lat: float = registry.JURISDICTION_LAT,
    lon: float = registry.JURISDICTION_LON,
    radius_m: int = MAX_RADIUS_M,
    principal: str = "p_operator",
    max_stations: int = 10,
) -> dict[str, Any]:
    """Ingest the latest reading from every OpenAQ sensor near the jurisdiction.

    A station with no recent measurement is reported as such and skipped. It is
    never backfilled with a neighbouring station's value.
    """
    sid = "conn_openaq"
    if not registry.configured(sid):
        return registry.unconfigured(sid)
    registry.ensure_connectors()

    radius = min(int(radius_m), MAX_RADIUS_M)
    locs, err = registry.get_json(
        f"{BASE}/locations",
        params={"coordinates": f"{lat},{lon}", "radius": radius,
                "limit": max_stations},
        headers=_headers(), timeout=20.0,
    )
    if locs is None:
        return registry.unavailable(sid, err or "no response from /v3/locations")

    results = locs.get("results") or []
    if not results:
        # A genuine, reportable finding: there is no monitor here. Not an error,
        # and emphatically not a reason to model a value.
        registry.record(sid, ok=True, detail=f"0 stations within {radius} m")
        out = registry.result_base(sid)
        out.update({
            "status": "no_stations",
            "stations": [], "readings": [],
            "radius_m": radius,
            "message": (
                f"OpenAQ reports no monitoring station within {radius} m of "
                f"{lat},{lon}. No air quality value is available for this "
                "jurisdiction and none is estimated."
            ),
        })
        return out

    stations: list[dict[str, Any]] = []
    readings: list[dict[str, Any]] = []
    errors: list[str] = []
    latest_at: str | None = None

    for loc in results:
        loc_id = loc.get("id")
        coords = loc.get("coordinates") or {}
        slat = _num(coords.get("latitude"))
        slon = _num(coords.get("longitude"))
        # sensorsId -> the parameter it measures, so a latest value can be named
        sensors = {
            s.get("id"): (s.get("parameter") or {})
            for s in (loc.get("sensors") or []) if s.get("id") is not None
        }
        provider = (loc.get("provider") or {}).get("name") or "unknown provider"
        station = {
            "location_id": loc_id,
            "name": loc.get("name"),
            "locality": loc.get("locality"),
            "provider": provider,
            "is_monitor": loc.get("isMonitor"),
            "coordinates": {"lat": slat, "lon": slon},
            "source_url": f"https://explore.openaq.org/locations/{loc_id}",
            "parameters": sorted({p.get("name") for p in sensors.values() if p.get("name")}),
        }
        stations.append(station)

        latest, lerr = registry.get_json(
            f"{BASE}/locations/{loc_id}/latest",
            headers=_headers(), timeout=20.0,
        )
        if latest is None:
            errors.append(f"location {loc_id}: {lerr}")
            station["status"] = "unavailable"
            continue

        rows = latest.get("results") or []
        if not rows:
            station["status"] = "no_recent_measurement"
            continue
        station["status"] = "ok"

        for row in rows:
            value = _num(row.get("value"))
            when = (row.get("datetime") or {}).get("utc")
            param = sensors.get(row.get("sensorsId")) or {}
            name = param.get("name")
            if value is None or not when or not name:
                continue
            rcoords = row.get("coordinates") or {}
            plat = _num(rcoords.get("latitude")) or slat
            plon = _num(rcoords.get("longitude")) or slon

            payload = {
                # One subject per station AND parameter: PM2.5 and NO2 at the
                # same station are different quantities and must never be
                # compared to each other as if they conflicted.
                "subject": f"openaq:{loc_id}:{name}",
                "station_id": f"openaq:{loc_id}",
                "parameter": name,
                "value": value,
                name: value,
                "unit": param.get("units") or "",
                "display_name": param.get("displayName"),
                "sensor_id": row.get("sensorsId"),
                "location_id": loc_id,
                "station_name": loc.get("name"),
                "locality": loc.get("locality"),
                "provider": provider,
                "is_reference_monitor": bool(loc.get("isMonitor")),
                "source_provider": "OpenAQ v3",
                "source_url": station["source_url"],
                "aggregator_note": (
                    "OpenAQ relays this station; it is not the operating "
                    "authority. For India the underlying operator is typically "
                    "CPCB, but this reading has not been read from CPCB directly."
                ),
            }
            accepted = ingest.ingest_event(
                EventIn(
                    connector_id=sid, kind="air_quality", event_time=when,
                    source_event_id=f"openaq:{row.get('sensorsId')}:{when}",
                    payload=payload,
                    geometry=(
                        {"type": "Point", "coordinates": [plon, plat]}
                        if plat is not None and plon is not None else None
                    ),
                ),
                principal,
            )
            readings.append({
                "location_id": loc_id, "station": loc.get("name"),
                "parameter": name, "value": value, "unit": payload["unit"],
                "observed_at": when, "event_id": accepted.id,
                "evidence_id": accepted.evidence_id,
                "deduplicated": accepted.deduplicated,
                "quarantined": accepted.quarantined, "reason": accepted.reason,
            })
            if latest_at is None or when > latest_at:
                latest_at = when

    if not readings:
        return registry.unavailable(
            sid,
            "; ".join(errors) or
            f"{len(stations)} station(s) found but none returned a recent measurement",
        )

    registry.record(sid, ok=True, upstream_at=latest_at,
                    detail=f"{len(readings)} reading(s) from {len(stations)} station(s)")
    out = registry.result_base(sid)
    out.update({
        "status": "ok",
        "radius_m": radius,
        "stations": stations,
        "readings": readings,
        "station_errors": errors,
        "partial": bool(errors),
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return out
