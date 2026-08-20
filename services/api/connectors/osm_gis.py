"""OpenStreetMap Physical Infrastructure GIS Connector.

Queries the Overpass API for real-world municipal infrastructure (waterways,
power substations, pumping stations, bridges, and primary highways) in the city
bounding box.

Zero-fabrication rule: Only real entities mapped in OSM are converted into digital
twin asset records. Never creates fake roads or imaginary infrastructure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from services.api.core import db

log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Vijayawada municipal bounding box [south, west, north, east]
VIJAYAWADA_BBOX = "16.4600,80.5700,16.5800,80.7200"


def fetch_osm_infrastructure(bbox: str = VIJAYAWADA_BBOX, tenant_id: str = "ten_vijayawada") -> dict[str, Any]:
    """Fetch real mapped infrastructure from OpenStreetMap."""
    query = f"""
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
    headers = {
        "User-Agent": "Auralis-AutonomousCity/3.0 (Civic Intelligence; research)",
    }
    mirrors = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    data = None
    last_err = ""
    for url in mirrors:
        try:
            with httpx.Client(timeout=25.0, headers=headers) as client:
                resp = client.post(url, data={"data": query})
                if resp.status_code == 200:
                    data = resp.json()
                    break
                last_err = f"HTTP {resp.status_code}: {resp.text[:100]}"
        except Exception as exc:
            last_err = str(exc)

    if data is None:
        log.warning("OSM infrastructure fetch failed: %s", last_err)
        return {
            "status": "unavailable",
            "source": "OpenStreetMap Overpass API",
            "error": last_err,
        }

    elements = data.get("elements", [])
    synced_assets = 0

    with db.tx() as c:
        for elem in elements:
            tags = elem.get("tags", {})
            name = tags.get("name", tags.get("ref", f"OSM-{elem.get('id')}"))
            lat = elem.get("lat") or elem.get("center", {}).get("lat")
            lon = elem.get("lon") or elem.get("center", {}).get("lon")

            if lat is None or lon is None:
                continue

            kind = "substation" if "substation" in tags.get("power", "") else \
                   "waterway" if "waterway" in tags else \
                   "pump_station" if "pumping_station" in tags.get("man_made", "") else "road"

            crit = 5 if kind in ("substation", "pump_station") else 4 if kind == "waterway" else 3
            dept = "power" if kind == "substation" else "water" if kind in ("pump_station", "waterway") else "transport"
            asset_id = f"osm_{elem.get('type', 'node')[:1]}_{elem['id']}"

            geom = json.dumps({"type": "Point", "coordinates": [lon, lat]})
            state = {"osm_id": elem["id"], "tags": tags}

            c.execute(
                "INSERT OR REPLACE INTO asset(id,tenant_id,kind,name,geometry,criticality,"
                "owner_dept,current_state,reported_state,desired_state,geometry_accuracy_m) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, tenant_id, kind, name, geom, crit, dept,
                 json.dumps(state), "{}", "{}", 5.0),
            )
            synced_assets += 1

    return {
        "status": "verified",
        "source": "OpenStreetMap Contributors (ODbL)",
        "elements_found": len(elements),
        "assets_synced": synced_assets,
    }
