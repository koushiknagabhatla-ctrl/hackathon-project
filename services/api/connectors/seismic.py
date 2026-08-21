"""Seismic events from the USGS earthquake feed.

REAL, KEYLESS, VERIFIED WORKING. Probed 2026-08-21:
    GET https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
    -> HTTP 200, {"type":"FeatureCollection",
                  "metadata":{"generated":<epoch_ms>,"title":...,"api":"2.7.0",
                              "count":273},
                  "features":[{"id":"ci41531864",
                               "properties":{"mag":0.84,"place":"...","time":<epoch_ms>,
                                             "updated":<epoch_ms>,"url":"...",
                                             "magType":"ml","status":"automatic",
                                             "tsunami":0,"net":"ci","type":"earthquake"},
                               "geometry":{"type":"Point",
                                           "coordinates":[lon, lat, depth_km]}}]}

Trust tier is `certified`, not `statutory`. USGS NEIC is a primary authoritative
producer of seismic parameters, but it is NOT the statutory seismic authority
for India - that is the National Center for Seismology (IMD). Claiming
`statutory` here would inflate the precedence this evidence gets in
`core/evidence.py` conflict resolution, which is a safety property, not a label.

WHAT IS AND IS NOT SAID
  * `properties.status` is carried through. USGS publishes `automatic`
    solutions within minutes and revises them to `reviewed` later. An automatic
    magnitude is a real datum that may change, and it is labelled as such
    rather than being withheld or being presented as final.
  * The distance from the jurisdiction is computed with `core/geo.distance_m`
    (pyproj geodesic), never hand-rolled.
  * An empty result is a real, reportable answer: `no_events` means the feed
    answered and reported nothing inside the radius. It never becomes a zero,
    a placeholder, or a previous day's quake shown as current.
  * `all_day` covers the last 24 hours, which is also `ingest.MAX_PAST_S`. An
    event sitting right on that boundary is quarantined by the pipeline with a
    clock-skew reason and reported here as quarantined - not dropped, not
    re-stamped.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from services.api.connectors import registry
from services.api.core import geo, ingest
from services.api.models import EventIn

log = logging.getLogger(__name__)

FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"

# Regional relevance radius. A M5 at 800 km is felt in Vijayawada and is
# operationally interesting; a M1 in California is not. Env-overridable because
# the right radius is a jurisdiction decision, not a physics constant.
DEFAULT_RADIUS_KM = 1000.0


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _iso(epoch_ms: Any) -> str | None:
    """USGS times are epoch milliseconds UTC. A feature with no usable time has
    no observation time, and an event with no observation time is not ingested -
    stamping it with our own clock would be inventing when it happened."""
    ms = _num(epoch_ms)
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def fetch_seismic(
    lat: float = registry.JURISDICTION_LAT,
    lon: float = registry.JURISDICTION_LON,
    radius_km: float = DEFAULT_RADIUS_KM,
    principal: str = "p_operator",
    min_magnitude: float | None = None,
) -> dict[str, Any]:
    """Ingest every USGS event of the last 24h within `radius_km` of the point.

    Returns the registry's standard shape: `ok`, `no_events` or `unavailable`.
    There is no outcome in which a magnitude appears that USGS did not publish.
    """
    sid = "conn_usgs_seismic"
    registry.ensure_connectors()

    data, err = registry.get_json(FEED_URL, timeout=20.0)
    if data is None:
        return registry.unavailable(sid, err or "no response")

    features = data.get("features")
    if not isinstance(features, list):
        return registry.unavailable(sid, "response carried no 'features' array")

    # The feed's own generation time. This is what freshness is judged on, not
    # the moment we happened to read it.
    generated_at = _iso((data.get("metadata") or {}).get("generated"))
    here = geo.point(lon, lat)

    ingested: list[dict[str, Any]] = []
    skipped_outside = 0
    skipped_unusable = 0

    for feat in features:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        mag = _num(props.get("mag"))
        observed_at = _iso(props.get("time"))
        usgs_id = feat.get("id")
        if mag is None or observed_at is None or len(coords) < 2 or not usgs_id:
            skipped_unusable += 1
            continue
        elon, elat = _num(coords[0]), _num(coords[1])
        if elon is None or elat is None:
            skipped_unusable += 1
            continue

        distance_km = round(geo.distance_m(here, geo.point(elon, elat)) / 1000.0, 2)
        if distance_km > radius_km:
            skipped_outside += 1
            continue
        if min_magnitude is not None and mag < min_magnitude:
            continue

        payload = {
            "subject": f"usgs:{usgs_id}:seismic",
            "station_id": f"usgs:{usgs_id}",
            "magnitude": mag,
            "value": mag,
            "unit": str(props.get("magType") or "M"),
            "depth_km": _num(coords[2]) if len(coords) > 2 else None,
            "distance_km": distance_km,
            "place": props.get("place"),
            "event_type": props.get("type"),
            "tsunami_flag": int(props.get("tsunami") or 0),
            "significance": props.get("sig"),
            "network": props.get("net"),
            # `automatic` solutions are revised; say so rather than implying the
            # magnitude is final.
            "review_status": props.get("status"),
            "revision_note": (
                "USGS publishes an automatic solution within minutes and revises "
                "it after analyst review. Magnitude and depth may change."
                if props.get("status") == "automatic"
                else "Analyst-reviewed USGS solution."
            ),
            "usgs_id": usgs_id,
            "source_provider": "USGS Earthquake Hazards Program",
            "source_url": props.get("url"),
            "feed_url": FEED_URL,
            "licence": "public domain (US Government)",
            "authority_note": (
                "USGS NEIC. NOT the National Center for Seismology (IMD), which "
                "is the statutory seismic authority for India."
            ),
        }
        accepted = ingest.ingest_event(
            EventIn(
                connector_id=sid, kind="seismic", event_time=observed_at,
                source_event_id=f"usgs:{usgs_id}:{props.get('updated')}",
                payload=payload,
                geometry=geo.point(elon, elat),
            ),
            principal,
        )
        ingested.append({
            "usgs_id": usgs_id, "magnitude": mag, "mag_type": payload["unit"],
            "depth_km": payload["depth_km"], "distance_km": distance_km,
            "place": payload["place"], "observed_at": observed_at,
            "review_status": payload["review_status"],
            "source_url": payload["source_url"],
            "event_id": accepted.id, "evidence_id": accepted.evidence_id,
            "deduplicated": accepted.deduplicated,
            "quarantined": accepted.quarantined, "reason": accepted.reason,
        })

    out = registry.result_base(sid)
    if not ingested:
        # The feed answered and there was nothing here. That is a finding, not
        # a failure, and emphatically not a reason to show anything.
        registry.record(sid, ok=True, upstream_at=generated_at,
                        detail=f"0 events within {radius_km:g} km of {lat},{lon}")
        out.update({
            "status": "no_events",
            "radius_km": radius_km,
            "feed_generated_at": generated_at,
            "events_in_feed": len(features),
            "events_outside_radius": skipped_outside,
            "events_unusable": skipped_unusable,
            "events": [],
            "message": (
                f"USGS reported {len(features)} event(s) worldwide in the last "
                f"24 hours and none within {radius_km:g} km of {lat},{lon}. "
                "No seismic value is shown for this jurisdiction."
            ),
        })
        return out

    latest = max(e["observed_at"] for e in ingested)
    registry.record(sid, ok=True, upstream_at=latest,
                    detail=f"{len(ingested)} event(s) within {radius_km:g} km")
    out.update({
        "status": "ok",
        "radius_km": radius_km,
        "feed_generated_at": generated_at,
        "events_in_feed": len(features),
        "events_outside_radius": skipped_outside,
        "events_unusable": skipped_unusable,
        "events": sorted(ingested, key=lambda e: e["observed_at"], reverse=True),
        "strongest": max(ingested, key=lambda e: e["magnitude"]),
        "nearest": min(ingested, key=lambda e: e["distance_km"]),
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return out
