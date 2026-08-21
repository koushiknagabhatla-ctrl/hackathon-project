"""River and reservoir hydrology.

WHAT IS REAL HERE
-----------------
`fetch_river_discharge()` calls the Open-Meteo Flood API
(https://flood-api.open-meteo.com/v1/flood), which serves GloFAS v4 river
discharge. Keyless, open, and verified working against the Krishna/Budameru
catchment at 16.5062N 80.6480E.

GloFAS is a hydrological MODEL, not a gauge. That distinction is enforced in
code, not in a comment: discharge is ingested with `evidence_class='derived'`,
so no UI surface can render it as an observed river reading, and only days that
are not in the future are ingested at all. Forward days are returned separately,
labelled as forecast, and never minted as evidence.

WHAT IS NOT WIRED, AND WHY
--------------------------
`fetch_india_wris()` and `fetch_cwc_flood_forecast()` report `unconfigured`.
They contain NO parsing code, because no response shape has been verified and
guessing one would be inventing a government data contract.

India-WRIS (https://indiawris.gov.in, https://arc.indiawris.gov.in):
    Probed 2026-08-21. Neither host completed a TCP connection - connect
    timeout, not an HTTP error. No public JSON endpoint for river stage could
    be confirmed. The portal's own documentation describes ArcGIS MapServer
    and WMS layers, but none could be reached to verify a schema. To enable
    this adapter an operator must obtain an NWIC-issued endpoint and
    credential and set INDIAWRIS_API_URL + INDIAWRIS_API_KEY.

CWC Flood Forecasting System (https://ffs.india-water.gov.in):
    Probed 2026-08-21. The portal responds, and an undocumented internal
    surface at /iam/api/ answers: /iam/api/layer-station/all returned HTTP 200
    with a SINGLE groundwater well in Kerala, null coordinates, and no forecast
    or gauge-level fields. /iam/api/layer-station/forecast returned HTTP 200
    with an empty body. That is not a usable public contract - it is an
    internal endpoint that happens to be exposed, with no stability guarantee
    and no data we could ground a flood claim on. Building a parser against it
    would produce confident output from an undefined source, so it is not
    built. Set CWC_FFS_API_URL + CWC_FFS_API_KEY if CWC grants real access.

Neither of these gaps is filled by substituting Open-Meteo. The registry keeps
them listed at their true `statutory` tier in an `unconfigured` state, so
/data-health shows an honest hole rather than a green tick.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from services.api.connectors import registry
from services.api.core import ingest
from services.api.models import EventIn

log = logging.getLogger(__name__)

FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
DAILY_FIELDS = "river_discharge,river_discharge_mean,river_discharge_max"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# ------------------------------------------------- Open-Meteo / GloFAS (REAL)
def fetch_river_discharge(
    lat: float = registry.JURISDICTION_LAT,
    lon: float = registry.JURISDICTION_LON,
    principal: str = "p_operator",
    past_days: int = 2,
    forecast_days: int = 3,
) -> dict[str, Any]:
    """Modelled river discharge for the catchment cell containing (lat, lon).

    Past and current days are ingested as `derived` evidence. Future days are
    returned under `forecast_series` and are NOT ingested - a forecast is not an
    observation, and the ingest clock-skew guard would rightly quarantine them.
    """
    sid = "conn_openmeteo_flood"
    registry.ensure_connectors()
    data, err = registry.get_json(
        FLOOD_URL,
        params={"latitude": lat, "longitude": lon, "daily": DAILY_FIELDS,
                "past_days": past_days, "forecast_days": forecast_days},
        timeout=20.0,
    )
    if data is None:
        return registry.unavailable(sid, err or "no response")

    daily = data.get("daily") or {}
    times = daily.get("time") or []
    discharge = daily.get("river_discharge") or []
    if not times or len(discharge) != len(times):
        return registry.unavailable(sid, "response carried no usable daily discharge series")

    units = (data.get("daily_units") or {}).get("river_discharge", "m3/s")
    # The grid cell Open-Meteo actually resolved to, not the point we asked for.
    # Reporting the requested point as if it were the sampled one would be a
    # small lie about where the number came from.
    cell_lat, cell_lon = data.get("latitude", lat), data.get("longitude", lon)
    subject = f"glofas:{cell_lat:.4f},{cell_lon:.4f}:river_discharge"
    today = datetime.now(UTC).date()

    ingested: list[dict[str, Any]] = []
    forecast: list[dict[str, Any]] = []
    latest_at: str | None = None

    for i, day in enumerate(times):
        v = _num(discharge[i])
        if v is None:
            continue
        entry = {
            "date": day,
            "discharge_m3s": v,
            "discharge_mean_m3s": _num((daily.get("river_discharge_mean") or [None] * len(times))[i]),
            "discharge_max_m3s": _num((daily.get("river_discharge_max") or [None] * len(times))[i]),
        }
        try:
            is_future = date.fromisoformat(day) > today
        except ValueError:
            continue
        if is_future:
            forecast.append({**entry, "evidence": "not ingested: forward model output"})
            continue

        observed_at = f"{day}T00:00:00Z"
        payload = {
            "subject": subject,
            "discharge_m3s": v,
            "value": v,
            "discharge_mean_m3s": entry["discharge_mean_m3s"],
            "discharge_max_m3s": entry["discharge_max_m3s"],
            "unit": units,
            "aggregation": "daily",
            "station_id": subject.split(":")[1],
            "modelled": True,
            "model": "GloFAS v4 (ECMWF/JRC) via Open-Meteo Flood API",
            "source_provider": "Open-Meteo Flood API",
            "source_url": FLOOD_URL,
            "licence": "CC-BY-4.0",
            "grid_cell": {"lat": cell_lat, "lon": cell_lon},
            "requested_point": {"lat": lat, "lon": lon},
            "not_a_gauge": (
                "Model reanalysis/forecast of catchment discharge. NOT a "
                "measured stage or flow at a Central Water Commission gauge."
            ),
        }
        accepted = ingest.ingest_event(
            EventIn(
                connector_id=sid, kind="river_discharge", event_time=observed_at,
                source_event_id=f"glofas:{cell_lat:.4f},{cell_lon:.4f}:{day}",
                payload=payload,
                geometry={"type": "Point", "coordinates": [cell_lon, cell_lat]},
            ),
            principal,
            evidence_class="derived",  # modelled, never presented as observed
        )
        ingested.append({
            **entry, "event_id": accepted.id, "evidence_id": accepted.evidence_id,
            "deduplicated": accepted.deduplicated, "quarantined": accepted.quarantined,
            "reason": accepted.reason,
        })
        latest_at = observed_at

    if not ingested:
        return registry.unavailable(
            sid, "no non-future day in the returned series could be ingested")

    registry.record(sid, ok=True, upstream_at=latest_at,
                    detail=f"{len(ingested)} day(s) ingested")
    out = registry.result_base(sid)
    out.update({
        "status": "ok",
        "evidence_class": "derived",
        "subject": subject,
        "unit": units,
        "grid_cell": {"lat": cell_lat, "lon": cell_lon},
        "latest": ingested[-1],
        "observed_series": ingested,
        "forecast_series": forecast,
        "modelled": True,
        "model": "GloFAS v4 (ECMWF/JRC) via Open-Meteo Flood API",
        "caveat": (
            "Modelled catchment discharge, not a gauge reading. It supports a "
            "trend claim about the Krishna/Budameru catchment; it does not "
            "support a claim about stage at any named barrage or gate."
        ),
    })
    return out


# ------------------------------------------------- India-WRIS (NOT INTEGRATED)
def fetch_india_wris(**_: Any) -> dict[str, Any]:
    """Reports `unconfigured`. See this module's docstring for what was probed.

    There is deliberately no request or parsing code below this line. Writing a
    parser for a response shape nobody has seen would create an integration
    that looks real on /data-health and produces nothing verifiable.
    """
    return registry.unconfigured(
        "conn_indiawris",
        extra=(
            "Probed 2026-08-21: indiawris.gov.in and arc.indiawris.gov.in did "
            "not complete a TCP connection, and no public JSON endpoint for "
            "river stage was verified. To enable, obtain an NWIC-issued "
            "endpoint and credential, then implement the parser against the "
            "documented schema they supply."
        ),
    )


# -------------------------------------------------- CWC FFS (NOT INTEGRATED)
def fetch_cwc_flood_forecast(**_: Any) -> dict[str, Any]:
    """Reports `unconfigured`. See this module's docstring for what was probed."""
    return registry.unconfigured(
        "conn_cwc_ffs",
        extra=(
            "Probed 2026-08-21: ffs.india-water.gov.in responds, but its "
            "undocumented /iam/api surface returned a single Kerala groundwater "
            "well with null coordinates and no forecast fields. No stable public "
            "contract exists to parse, so none is assumed."
        ),
    )


def fetch_hydrology(
    lat: float = registry.JURISDICTION_LAT,
    lon: float = registry.JURISDICTION_LON,
    principal: str = "p_operator",
) -> dict[str, Any]:
    """Every hydrology source, each reporting its own honest state."""
    sources = [
        fetch_river_discharge(lat, lon, principal),
        fetch_india_wris(),
        fetch_cwc_flood_forecast(),
    ]
    ok = [s for s in sources if s.get("status") == "ok"]
    return {
        "status": "ok" if ok else "unavailable",
        "sources": sources,
        "statutory_gauge_available": False,
        "gap_note": (
            "No statutory Indian gauge feed (India-WRIS / CWC) is connected. "
            "The only hydrology signal here is modelled catchment discharge. "
            "Do not present it as a measured river level."
        ),
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
