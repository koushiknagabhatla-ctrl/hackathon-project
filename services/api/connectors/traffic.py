"""Andhra Pradesh Urban Traffic Flow & TomTom Live Corridor Intelligence.

Analyzes real-time traffic speeds, Level of Service (LOS A-F), and delay estimates
across primary municipal transit corridors in Andhra Pradesh cities using TomTom
Traffic Flow API and municipal sensor feeds.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from services.api.core import db, repo

log = logging.getLogger("auralis.traffic")

# City-Specific Major Arterial Transit Corridors across Andhra Pradesh
AP_CORRIDORS: dict[str, list[dict[str, Any]]] = {
    "vijayawada": [
        {
            "id": "cor_vja_mg_road",
            "name": "MG Road (Bandar Road)",
            "from": "Police Control Room",
            "to": "Benz Circle",
            "length_km": 4.2,
            "free_flow_speed_kph": 45.0,
            "midpoint": [16.5081, 80.6340],
            "coordinates": [[80.6200, 16.5100], [80.6480, 16.5062]],
        },
        {
            "id": "cor_vja_eluru_road",
            "name": "Eluru Road Corridor",
            "from": "Kaleswara Rao Market",
            "to": "Gunadala Junction",
            "length_km": 5.8,
            "free_flow_speed_kph": 40.0,
            "midpoint": [16.5165, 80.6400],
            "coordinates": [[80.6150, 16.5180], [80.6650, 16.5150]],
        },
        {
            "id": "cor_vja_kanaka_durga",
            "name": "Kanaka Durga Flyover",
            "from": "Kummaripalem",
            "to": "Prakasam Barrage North",
            "length_km": 2.6,
            "free_flow_speed_kph": 60.0,
            "midpoint": [16.5115, 80.6085],
            "coordinates": [[80.6050, 16.5180], [80.6120, 16.5050]],
        },
        {
            "id": "cor_vja_benz_nh16",
            "name": "Benz Circle / NH-16 Elevated Corridor",
            "from": "Ramavarappadu Ring",
            "to": "Tadepalli Junction",
            "length_km": 5.2,
            "free_flow_speed_kph": 65.0,
            "midpoint": [16.5062, 80.6480],
            "coordinates": [[80.6680, 16.5200], [80.6480, 16.5062], [80.6100, 16.4850]],
        },
        {
            "id": "cor_vja_brts",
            "name": "BRTS Rapid Transit Road",
            "from": "RTC Bus Terminal",
            "to": "Prasadampadu",
            "length_km": 6.0,
            "free_flow_speed_kph": 50.0,
            "midpoint": [16.5200, 80.6525],
            "coordinates": [[80.6250, 16.5150], [80.6800, 16.5250]],
        },
        {
            "id": "cor_vja_prakasam",
            "name": "Prakasam Barrage Causeway",
            "from": "Vijayawada One Town",
            "to": "Guntur / Seethanagaram",
            "length_km": 1.8,
            "free_flow_speed_kph": 35.0,
            "midpoint": [16.5000, 80.6100],
            "coordinates": [[80.6120, 16.5050], [80.6080, 16.4950]],
        },
    ],
    "visakhapatnam": [
        {
            "id": "cor_vzk_beach_road",
            "name": "RK Beach / Coastal Promenade Corridor",
            "from": "Naval Coastal Battery",
            "to": "Rushikonda IT Hill",
            "length_km": 14.5,
            "free_flow_speed_kph": 55.0,
            "midpoint": [17.7460, 83.3425],
            "coordinates": [[83.3000, 17.7100], [83.3850, 17.7820]],
        },
        {
            "id": "cor_vzk_nad_junction",
            "name": "NAD Flyover / Airport Corridor",
            "from": "Gajuwaka Industrial Belt",
            "to": "Maddilapalem Junction",
            "length_km": 11.2,
            "free_flow_speed_kph": 60.0,
            "midpoint": [17.7275, 83.2625],
            "coordinates": [[83.2100, 17.7200], [83.3150, 17.7350]],
        },
        {
            "id": "cor_vzk_vip_road",
            "name": "VIP Road / Siripuram Junction",
            "from": "RTC Complex",
            "to": "Siripuram Circle",
            "length_km": 3.8,
            "free_flow_speed_kph": 45.0,
            "midpoint": [17.7240, 83.3125],
            "coordinates": [[83.3050, 17.7220], [83.3200, 17.7260]],
        },
        {
            "id": "cor_vzk_port_express",
            "name": "Visakhapatnam Port Express Corridor",
            "from": "Scindia Junction",
            "to": "Port Outer Harbour",
            "length_km": 6.4,
            "free_flow_speed_kph": 50.0,
            "midpoint": [17.6900, 83.2865],
            "coordinates": [[83.2750, 17.6950], [83.2980, 17.6850]],
        },
    ],
    "tirupati": [
        {
            "id": "cor_tpt_alipiri",
            "name": "Alipiri Bypass / Temple Transit Road",
            "from": "Tirupati Central Station",
            "to": "Alipiri Foothills Gate",
            "length_km": 5.4,
            "free_flow_speed_kph": 45.0,
            "midpoint": [13.6400, 79.4075],
            "coordinates": [[79.4200, 13.6280], [79.3950, 13.6520]],
        },
        {
            "id": "cor_tpt_renigunta",
            "name": "Renigunta Airport Express Corridor",
            "from": "Tirupati RTC Central",
            "to": "Tirupati Airport (Renigunta)",
            "length_km": 13.8,
            "free_flow_speed_kph": 65.0,
            "midpoint": [13.6310, 79.4850],
            "coordinates": [[79.4250, 13.6300], [79.5450, 13.6320]],
        },
        {
            "id": "cor_tpt_svims",
            "name": "SVIMS / Medical University Transit Link",
            "from": "Bhavani Nagar",
            "to": "SVIMS Hospital Complex",
            "length_km": 3.2,
            "free_flow_speed_kph": 40.0,
            "midpoint": [13.6385, 79.4060],
            "coordinates": [[79.4100, 13.6350], [79.4020, 13.6420]],
        },
    ],
    "guntur": [
        {
            "id": "cor_gtr_gt_road",
            "name": "GT Road / Market Corridor",
            "from": "Guntur Railway Station",
            "to": "Lodge Centre",
            "length_km": 3.5,
            "free_flow_speed_kph": 40.0,
            "midpoint": [16.3025, 80.4350],
            "coordinates": [[80.4400, 16.3050], [80.4300, 16.3000]],
        },
        {
            "id": "cor_gtr_inner_ring",
            "name": "Guntur Inner Ring Road Corridor",
            "from": "Autonagar Junction",
            "to": "Pattabhipuram Circle",
            "length_km": 7.8,
            "free_flow_speed_kph": 55.0,
            "midpoint": [16.3075, 80.4375],
            "coordinates": [[80.4600, 16.3200], [80.4150, 16.2950]],
        },
    ],
    "kurnool": [
        {
            "id": "cor_knl_bellary_road",
            "name": "Bellary Road Commercial Corridor",
            "from": "Kurnool Old Bus Stand",
            "to": "Tungabhadra Bridge North",
            "length_km": 4.6,
            "free_flow_speed_kph": 45.0,
            "midpoint": [15.8350, 78.0400],
            "coordinates": [[78.0350, 15.8250], [78.0450, 15.8450]],
        },
        {
            "id": "cor_knl_medical_college",
            "name": "KMC Medical College / Hospital Corridor",
            "from": "Collectorate Junction",
            "to": "Kurnool Medical College",
            "length_km": 3.8,
            "free_flow_speed_kph": 40.0,
            "midpoint": [15.8175, 78.0300],
            "coordinates": [[78.0320, 15.8200], [78.0280, 15.8150]],
        },
    ],
}


def fetch_tomtom_traffic_flow(lat: float, lon: float) -> dict[str, Any] | None:
    """Fetch live real-time traffic flow telemetry from TomTom Traffic API."""
    key = os.environ.get("TOMTOM_API_KEY")
    if not key:
        return None
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?point={lat:.4f},{lon:.4f}&key={key}"
    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                flow = data.get("flowSegmentData", {})
                return {
                    "current_speed_kph": float(flow.get("currentSpeed", 0)),
                    "free_flow_speed_kph": float(flow.get("freeFlowSpeed", 0)),
                    "current_travel_time_sec": float(flow.get("currentTravelTime", 0)),
                    "free_flow_travel_time_sec": float(flow.get("freeFlowTravelTime", 0)),
                    "confidence": float(flow.get("confidence", 0.9)),
                    "road_closure": bool(flow.get("roadClosure", False)),
                    "provider": "tomtom_live_probe",
                }
    except Exception as exc:
        log.debug("TomTom flow fetch failed for (%s, %s): %s", lat, lon, exc)
    return None


def _compute_los(speed_ratio: float) -> str:
    """Compute Highway Capacity Manual Level of Service (LOS A through F)."""
    if speed_ratio >= 0.85:
        return "A"  # Free flow
    elif speed_ratio >= 0.70:
        return "B"  # Reasonably free flow
    elif speed_ratio >= 0.55:
        return "C"  # Stable flow
    elif speed_ratio >= 0.40:
        return "D"  # Approaching unstable flow
    elif speed_ratio >= 0.25:
        return "E"  # Unstable flow / heavy congestion
    return "F"      # Forced breakdown / gridlock


def get_corridor_status(
    tenant_id: str = "ten_vijayawada",
    city_name: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> list[dict[str, Any]]:
    """Calculate current congestion, speed, and delay for city corridors in Andhra Pradesh."""
    # Resolve city key
    c_key = "vijayawada"
    if city_name:
        clean = city_name.lower().strip()
        for k in AP_CORRIDORS:
            if k in clean or clean in k:
                c_key = k
                break
    elif lat and lon:
        if 17.4 < lat < 18.0 and 83.0 < lon < 83.5:
            c_key = "visakhapatnam"
        elif 13.4 < lat < 13.8 and 79.2 < lon < 79.6:
            c_key = "tirupati"
        elif 16.1 < lat < 16.4 and 80.3 < lon < 80.6:
            c_key = "guntur"
        elif 15.6 < lat < 16.0 and 77.8 < lon < 78.2:
            c_key = "kurnool"

    corridor_list = AP_CORRIDORS.get(c_key, AP_CORRIDORS["vijayawada"])

    # Check for active incidents per corridor
    active_incidents = repo.list_incidents(tenant_id, limit=50)
    traffic_incidents = [i for i in active_incidents if i.state != "closed"]

    results = []
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    for c in corridor_list:
        cid = c["id"]
        c_name = c["name"]
        free_speed = c["free_flow_speed_kph"]
        length = c["length_km"]
        mid = c.get("midpoint", [16.5062, 80.6480])

        # Try fetching real-time TomTom flow first
        tomtom_data = fetch_tomtom_traffic_flow(mid[0], mid[1])
        source_provider = "model_baseline"

        if tomtom_data and tomtom_data["current_speed_kph"] > 0:
            speed_kph = tomtom_data["current_speed_kph"]
            if tomtom_data["free_flow_speed_kph"] > 0:
                free_speed = tomtom_data["free_flow_speed_kph"]
            source_provider = "tomtom_live_probe"
        else:
            # Check if corridor has associated incidents in municipal DB
            has_critical = any(
                i.severity == "critical" and (c_name.lower() in i.title.lower() or "traffic" in i.incident_class)
                for i in traffic_incidents
            )
            has_major = any(
                i.severity == "major" and (c_name.lower() in i.title.lower() or "traffic" in i.incident_class)
                for i in traffic_incidents
            )

            if has_critical:
                speed_kph = round(free_speed * 0.22, 1)
            elif has_major:
                speed_kph = round(free_speed * 0.48, 1)
            else:
                # Baseline normal urban flow (approx 80% of free-flow)
                speed_kph = round(free_speed * 0.80, 1)

        speed_ratio = speed_kph / max(10.0, free_speed)
        los = _compute_los(speed_ratio)
        congestion_index = round(max(0.0, min(1.0, 1.0 - speed_ratio)), 2)

        free_time_min = (length / max(10.0, free_speed)) * 60.0
        current_time_min = (length / max(5.0, speed_kph)) * 60.0
        delay_min = round(max(0.0, current_time_min - free_time_min), 1)

        results.append({
            "id": cid,
            "name": c_name,
            "from": c["from"],
            "to": c["to"],
            "length_km": length,
            "current_speed_kph": round(speed_kph, 1),
            "free_flow_speed_kph": round(free_speed, 1),
            "speed_ratio": round(speed_ratio, 2),
            "level_of_service": los,
            "congestion_index": congestion_index,
            "travel_time_min": round(current_time_min, 1),
            "delay_min": delay_min,
            "status": "congested" if los in ("E", "F") else "moderate" if los == "D" else "clear",
            "source_provider": source_provider,
            "coordinates": c["coordinates"],
            "updated_at": now_iso,
        })

    return results
