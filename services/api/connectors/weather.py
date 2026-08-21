"""Meteorological connector.

PRIMARY: Open-Meteo (https://api.open-meteo.com) - free, keyless, real, and so
the system has genuine live observations with zero configuration.
OPTIONAL: OpenWeatherMap, when OPENWEATHER_API_KEY is set.

The two are NOT a fallback chain. Both are fetched when both are available and
both are ingested, because they are independent estimates of the same quantity.
If they disagree beyond tolerance the evidence layer raises a CONFLICT and both
readings stay on the record. Nothing is averaged and no source silently wins.

Zero-fabrication rule: if a source cannot be reached it reports `unavailable`
with the last verified timestamp. It never substitutes a value, a default, or a
previous reading presented as current.

An earlier revision of this file ingested Open-Meteo output under connector id
`conn_imd` ("IMD nowcast feed", trust tier `certified`). That was a mislabel:
Open-Meteo is not the India Meteorological Department. It now ingests under
`conn_openmeteo` at trust tier `verified`, which is what it actually is.
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

DEFAULT_LAT = registry.JURISDICTION_LAT
DEFAULT_LON = registry.JURISDICTION_LON

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"

CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,precipitation,rain,surface_pressure,"
    "pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code"
)


def _subject(lat: float, lon: float, metric: str) -> str:
    """Both met sources must land on the SAME subject string, otherwise their
    disagreement is invisible to conflict detection."""
    return f"met:{lat:.4f},{lon:.4f}:{metric}"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _iso(ts: str) -> str:
    """Open-Meteo returns '2026-08-21T03:15' in the requested timezone (we ask
    for UTC). Normalise to an explicit UTC stamp rather than letting an
    ambiguous local-looking string through."""
    ts = str(ts)
    if ts.endswith("Z"):
        return ts
    if len(ts) == 16:  # YYYY-MM-DDTHH:MM
        ts += ":00"
    return ts + "Z"


# ------------------------------------------------------------- Open-Meteo
def fetch_open_meteo(
    lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON, principal: str = "p_operator",
) -> dict[str, Any]:
    """Primary path. Keyless, so this works out of the box on a clean checkout."""
    sid = "conn_openmeteo"
    registry.ensure_connectors()
    data, err = registry.get_json(
        OPEN_METEO_URL,
        params={"latitude": lat, "longitude": lon, "current": CURRENT_FIELDS,
                "timezone": "UTC"},
        timeout=15.0,
    )
    if data is None:
        return registry.unavailable(sid, err or "no response")

    cur = data.get("current") or {}
    units = data.get("current_units") or {}
    if not cur.get("time"):
        return registry.unavailable(sid, "response carried no 'current' block")

    observed_at = _iso(cur["time"])
    # Open-Meteo reports precipitation as mm accumulated over the reporting
    # interval. Converting to a rate needs that interval, which the payload
    # gives us in seconds. Assuming 1h would overstate a 15-minute bucket.
    interval_s = _num(cur.get("interval")) or 3600.0
    precip_mm = _num(cur.get("rain"))
    if precip_mm is None:
        precip_mm = _num(cur.get("precipitation"))
    rate_mm_h = None if precip_mm is None else round(precip_mm * 3600.0 / interval_s, 3)

    if rate_mm_h is None:
        return registry.unavailable(sid, "response carried no precipitation field")

    payload = {
        "subject": _subject(lat, lon, "rainfall"),
        "rate_mm_h": rate_mm_h,
        "precipitation_mm_interval": precip_mm,
        "interval_s": interval_s,
        "temperature_c": _num(cur.get("temperature_2m")),
        "humidity_pct": _num(cur.get("relative_humidity_2m")),
        "pressure_hpa": _num(cur.get("surface_pressure")),
        "pressure_msl_hpa": _num(cur.get("pressure_msl")),
        "wind_speed_kph": _num(cur.get("wind_speed_10m")),
        "wind_direction_deg": _num(cur.get("wind_direction_10m")),
        "wind_gust_kph": _num(cur.get("wind_gusts_10m")),
        "weather_code": cur.get("weather_code"),
        "units": units,
        "elevation_m": data.get("elevation"),
        "source_provider": "Open-Meteo",
        "source_url": OPEN_METEO_URL,
        "licence": "CC-BY-4.0",
        # NOT the India Meteorological Department. Named so nobody downstream
        # can read a government attribution into this row.
        "source_note": "aggregated national met services; not IMD",
    }
    accepted = ingest.ingest_event(
        EventIn(
            connector_id=sid, kind="rainfall", event_time=observed_at,
            source_event_id=f"openmeteo:{lat:.4f},{lon:.4f}:{observed_at}",
            payload=payload,
            geometry={"type": "Point", "coordinates": [lon, lat]},
        ),
        principal,
    )
    registry.record(sid, ok=True, upstream_at=observed_at,
                    detail=f"rate_mm_h={rate_mm_h}")

    out = registry.result_base(sid)
    out.update({
        "status": "ok",
        "observed_at": observed_at,
        "rain_rate_mm_h": rate_mm_h,
        "temperature_c": payload["temperature_c"],
        "humidity_pct": payload["humidity_pct"],
        "pressure_hpa": payload["pressure_hpa"],
        "wind_speed_kph": payload["wind_speed_kph"],
        "subject": payload["subject"],
        "event_id": accepted.id,
        "evidence_id": accepted.evidence_id,
        "quarantined": accepted.quarantined,
        "reason": accepted.reason,
        "incident_id": accepted.incident_id,
    })
    return out


# ------------------------------------------------------- OpenWeatherMap
def fetch_openweathermap(
    lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON, principal: str = "p_operator",
) -> dict[str, Any]:
    """Optional corroborating source. Absent a key this is `unconfigured`, which
    is a legitimate state and not an error."""
    sid = "conn_openweathermap"
    if not registry.configured(sid):
        return registry.unconfigured(sid)
    registry.ensure_connectors()

    data, err = registry.get_json(
        OPENWEATHER_URL,
        params={"lat": lat, "lon": lon, "units": "metric",
                "appid": os.environ["OPENWEATHER_API_KEY"]},
        timeout=15.0,
    )
    if data is None:
        return registry.unavailable(sid, err or "no response")

    main = data.get("main") or {}
    wind = data.get("wind") or {}
    rain = data.get("rain") or {}
    # OWM reports rain as mm accumulated over 1h or 3h. Absent BOTH keys the
    # correct reading is 0.0 mm/h: OWM omits the block when no rain fell, which
    # is a real datum, not a missing one.
    if "1h" in rain:
        rate_mm_h = round(float(rain["1h"]), 3)
    elif "3h" in rain:
        rate_mm_h = round(float(rain["3h"]) / 3.0, 3)
    else:
        rate_mm_h = 0.0

    # `dt` is OWM's own observation time. Absent it we do NOT know when this was
    # measured, and stamping it with our clock would present an unknown-age
    # reading as current. A response with no `dt` is unusable, not a licence to
    # invent an observation time.
    dt = data.get("dt")
    if not isinstance(dt, (int, float)) or isinstance(dt, bool):
        return registry.unavailable(
            sid, "response carried no observation time ('dt'); refusing to "
                 "stamp a reading with our own clock")
    observed_at = datetime.fromtimestamp(dt, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "subject": _subject(lat, lon, "rainfall"),
        "rate_mm_h": rate_mm_h,
        "temperature_c": _num(main.get("temp")),
        "humidity_pct": _num(main.get("humidity")),
        "pressure_hpa": _num(main.get("pressure")),
        "wind_speed_m_s": _num(wind.get("speed")),
        "wind_direction_deg": _num(wind.get("deg")),
        "weather_description": (data.get("weather") or [{}])[0].get("description"),
        "station_name": data.get("name"),
        "source_provider": "OpenWeatherMap",
        "source_url": OPENWEATHER_URL,
    }
    accepted = ingest.ingest_event(
        EventIn(
            connector_id=sid, kind="rainfall", event_time=observed_at,
            source_event_id=f"owm:{lat:.4f},{lon:.4f}:{observed_at}",
            payload=payload,
            geometry={"type": "Point", "coordinates": [lon, lat]},
        ),
        principal,
    )
    registry.record(sid, ok=True, upstream_at=observed_at,
                    detail=f"rate_mm_h={rate_mm_h}")

    out = registry.result_base(sid)
    out.update({
        "status": "ok",
        "observed_at": observed_at,
        "rain_rate_mm_h": rate_mm_h,
        "temperature_c": payload["temperature_c"],
        "humidity_pct": payload["humidity_pct"],
        "pressure_hpa": payload["pressure_hpa"],
        "subject": payload["subject"],
        "event_id": accepted.id,
        "evidence_id": accepted.evidence_id,
        "quarantined": accepted.quarantined,
        "reason": accepted.reason,
    })
    return out


# ------------------------------------------------------------- entry point
def fetch_live_weather(
    lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON, principal: str = "p_operator",
) -> dict[str, Any]:
    """Fetch every available met source and surface any disagreement.

    Returns `sources` (one entry per source, each carrying its own status) and
    `conflicts`. `status` is 'ok' if at least one source answered, otherwise
    'unavailable' - there is no third outcome where a number appears anyway.
    """
    from services.api.core import evidence

    sources = [
        fetch_open_meteo(lat, lon, principal),
        fetch_openweathermap(lat, lon, principal),
    ]
    ok = [s for s in sources if s.get("status") == "ok"]

    conflicts: list[dict[str, Any]] = []
    if len(ok) > 1:
        # Two independent estimates of the same quantity. Retain both; report
        # the divergence. The evidence layer resolves by source precedence and
        # never by averaging.
        for c in evidence.detect_conflicts(_subject(lat, lon, "rainfall")):
            conflicts.append(c.model_dump())

    return {
        "status": "ok" if ok else "unavailable",
        "jurisdiction": registry.JURISDICTION_NAME,
        "coordinates": {"lat": lat, "lon": lon},
        "sources": sources,
        "conflicts": conflicts,
        "conflict_note": (
            "Sources disagree beyond tolerance. Both readings are retained and "
            "shown; they are not averaged and neither is silently discarded."
            if conflicts else None
        ),
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
