"""OpenStreetMap physical-infrastructure GIS connector (Overpass API).

Queries Overpass for real-world municipal infrastructure (waterways, power
substations, pumping stations and primary highways) in the jurisdiction bounding
box and writes them into the digital twin as `asset` rows.

Zero-fabrication rule: only entities that are actually mapped in OSM become
assets. Nothing invents a road, a substation or a coordinate.

AUDIT NOTE (2026-08-21). This module previously stood outside the connector
registry, and three things followed from that:

  * a failed fetch returned `{"status": "unavailable"}` with no `last_verified_at`,
    so a caller could not tell whether the twin was an hour stale or had never
    loaded at all. The governing rule requires the LAST VERIFIED TIME alongside
    the gap, so the failure path now goes through `registry.unavailable()`.
  * success returned `{"status": "verified"}` - a TrustTier word used as a
    status word. Trust tier is `crowdsourced` (volunteer survey) and comes from
    the registry row; the status is now `ok`.
  * nothing recorded the fetch, so `/data-health` never learned that OSM had
    answered, and the Overpass `osm3s.timestamp_osm_base` - the upstream time
    the extract was cut - was discarded. It is now recorded as the upstream
    timestamp, so twin freshness is judged on OSM's clock, not ours.

A resync also no longer clobbers operator-owned columns: OSM owns geometry,
name, kind, criticality and the OSM tag blob, and only those are updated.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.api.connectors import registry
from services.api.core import db

log = logging.getLogger(__name__)

SOURCE_ID = "conn_osm"
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)

# Vijayawada municipal bounding box [south, west, north, east]
VIJAYAWADA_BBOX = "16.4600,80.5700,16.5800,80.7200"


def _query(bbox: str) -> str:
    return f"""
    [out:json][timeout:25];
    (
      node["waterway"="canal"]({bbox});
      way["waterway"="canal"]({bbox});
      node["power"="substation"]({bbox});
      way["power"="substation"]({bbox});
      node["man_made"="pumping_station"]({bbox});
      way["highway"="primary"]({bbox});
    );
    out center;
    """


def _classify(tags: dict[str, Any]) -> tuple[str, int, str]:
    """(kind, criticality, owning department) from the OSM tags, nothing else."""
    if "substation" in str(tags.get("power", "")):
        return "substation", 5, "power"
    if "pumping_station" in str(tags.get("man_made", "")):
        return "pump_station", 5, "water"
    if "waterway" in tags:
        return "waterway", 4, "water"
    return "road", 3, "transport"


def fetch_osm_infrastructure(
    bbox: str = VIJAYAWADA_BBOX,
    tenant_id: str = registry.TENANT_ID,
) -> dict[str, Any]:
    """Sync real mapped infrastructure from OpenStreetMap into the twin."""
    query = _query(bbox)
    data, last_err = None, "no attempt made"
    for url in OVERPASS_MIRRORS:
        data, last_err = registry.get_json(
            url, method="POST", data={"data": query}, timeout=25.0
        )
        if data is not None:
            break

    if data is None:
        # No mirror answered. Report the gap and the last time the twin was
        # genuinely refreshed; never a partial or remembered element set.
        log.warning("OSM infrastructure fetch failed on every mirror: %s", last_err)
        return registry.unavailable(
            SOURCE_ID, f"all {len(OVERPASS_MIRRORS)} Overpass mirrors failed: {last_err}")

    elements = data.get("elements") or []
    # Overpass reports the cut time of the extract it answered from. That is the
    # age of this twin data, and it is not the same as "now".
    upstream_at = (data.get("osm3s") or {}).get("timestamp_osm_base")

    synced = 0
    skipped_no_geometry = 0
    with db.tx() as c:
        for elem in elements:
            tags = elem.get("tags") or {}
            lat = elem.get("lat") or (elem.get("center") or {}).get("lat")
            lon = elem.get("lon") or (elem.get("center") or {}).get("lon")
            if lat is None or lon is None:
                # An element with no resolvable position cannot be placed on a
                # map, and guessing one would be inventing geometry.
                skipped_no_geometry += 1
                continue

            kind, crit, dept = _classify(tags)
            name = tags.get("name") or tags.get("ref") or f"OSM-{elem.get('id')}"
            asset_id = f"osm_{str(elem.get('type', 'node'))[:1]}_{elem['id']}"
            geom = json.dumps({"type": "Point", "coordinates": [lon, lat]})
            state = json.dumps({
                "osm_id": elem["id"],
                "osm_type": elem.get("type", "node"),
                "tags": tags,
                "source_url": (
                    f"https://www.openstreetmap.org/"
                    f"{elem.get('type', 'node')}/{elem['id']}"
                ),
                "osm_extract_at": upstream_at,
            })
            # OSM owns survey facts only. `reported_state` and `desired_state`
            # belong to operators and the twin; a resync must not wipe them,
            # which INSERT OR REPLACE used to do silently.
            c.execute(
                "INSERT INTO asset(id,tenant_id,kind,name,geometry,criticality,"
                "owner_dept,current_state,reported_state,desired_state,"
                "geometry_accuracy_m) VALUES(?,?,?,?,?,?,?,?,'{}','{}',?) "
                "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,"
                "name=excluded.name,geometry=excluded.geometry,"
                "criticality=excluded.criticality,owner_dept=excluded.owner_dept,"
                "current_state=excluded.current_state,"
                "geometry_accuracy_m=excluded.geometry_accuracy_m",
                (asset_id, tenant_id, kind, name, geom, crit, dept, state, 5.0),
            )
            synced += 1

    registry.record(SOURCE_ID, ok=True, upstream_at=upstream_at,
                    detail=f"{synced} asset(s) from {len(elements)} element(s)")
    out = registry.result_base(SOURCE_ID)
    out.update({
        "status": "ok",
        "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
        "bbox": bbox,
        "osm_extract_at": upstream_at,
        "elements_found": len(elements),
        "assets_synced": synced,
        "skipped_no_geometry": skipped_no_geometry,
        "note": (
            "Volunteer-surveyed data. Every asset carries its OSM element id and "
            "a resolvable openstreetmap.org URL, so any twin claim is checkable "
            "against the source."
        ),
    })
    return out
