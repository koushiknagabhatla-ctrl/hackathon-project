"""Vijayawada Urban Traffic Flow & Corridor Congestion Intelligence.

Analyzes traffic speeds, Level of Service (LOS A-F), and delay estimates
across primary municipal transit corridors.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from services.api.core import db, repo

log = logging.getLogger("auralis.traffic")

CORRIDORS: list[dict[str, Any]] = [
    {
        "id": "cor_mg_road",
        "name": "MG Road (Bandar Road)",
        "from": "Police Control Room",
        "to": "Benz Circle",
        "length_km": 4.2,
        "free_flow_speed_kph": 45.0,
        "coordinates": [[80.6200, 16.5100], [80.6480, 16.5062]],
    },
    {
        "id": "cor_eluru_road",
        "name": "Eluru Road Corridor",
        "from": "Kaleswara Rao Market",
        "to": "Gunadala Junction",
        "length_km": 5.8,
        "free_flow_speed_kph": 40.0,
        "coordinates": [[80.6150, 16.5180], [80.6650, 16.5150]],
    },
    {
        "id": "cor_kanaka_durga_flyover",
        "name": "Kanaka Durga Elevated Flyover",
        "from": "Kummaripalem",
        "to": "Prakasam Barrage North",
        "length_km": 2.6,
        "free_flow_speed_kph": 60.0,
        "coordinates": [[80.6050, 16.5180], [80.6120, 16.5050]],
    },
    {
        "id": "cor_benz_circle_nh16",
        "name": "Benz Circle / NH-16 Elevated Corridor",
        "from": "Ramavarappadu Ring",
        "to": "Tadepalli Junction",
        "length_km": 5.2,
        "free_flow_speed_kph": 65.0,
        "coordinates": [[80.6680, 16.5200], [80.6480, 16.5062], [80.6100, 16.4850]],
    },
    {
        "id": "cor_brts",
        "name": "BRTS Rapid Transit Road",
        "from": "RTC Bus Terminal",
        "to": "Prasadampadu",
        "length_km": 6.0,
        "free_flow_speed_kph": 50.0,
        "coordinates": [[80.6250, 16.5150], [80.6800, 16.5250]],
    },
    {
        "id": "cor_prakasam_barrage",
        "name": "Prakasam Barrage Causeway",
        "from": "Vijayawada One Town",
        "to": "Guntur / Seethanagaram",
        "length_km": 1.8,
        "free_flow_speed_kph": 35.0,
        "coordinates": [[80.6120, 16.5050], [80.6080, 16.4950]],
    },
]


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


def get_corridor_status(tenant_id: str = "ten_vijayawada") -> list[dict[str, Any]]:
    """Calculate current congestion, speed, and delay for all city corridors."""
    # Check for active incidents per corridor
    active_incidents = repo.list_incidents(tenant_id, limit=50)
    traffic_incidents = [i for i in active_incidents if i.state != "closed"]

    results = []
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    for c in CORRIDORS:
        cid = c["id"]
        c_name = c["name"]
        free_speed = c["free_flow_speed_kph"]
        length = c["length_km"]

        # Check if corridor has associated incidents
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
            # Baseline normal urban flow (approx 78% of free-flow)
            speed_kph = round(free_speed * 0.80, 1)

        speed_ratio = speed_kph / free_speed
        los = _compute_los(speed_ratio)
        congestion_index = round(max(0.0, min(1.0, 1.0 - speed_ratio)), 2)

        free_time_min = (length / free_speed) * 60.0
        current_time_min = (length / max(5.0, speed_kph)) * 60.0
        delay_min = round(max(0.0, current_time_min - free_time_min), 1)

        results.append({
            "id": cid,
            "name": c_name,
            "from": c["from"],
            "to": c["to"],
            "length_km": length,
            "current_speed_kph": speed_kph,
            "free_flow_speed_kph": free_speed,
            "speed_ratio": round(speed_ratio, 2),
            "level_of_service": los,
            "congestion_index": congestion_index,
            "travel_time_min": round(current_time_min, 1),
            "delay_min": delay_min,
            "status": "congested" if los in ("E", "F") else "moderate" if los == "D" else "clear",
            "coordinates": c["coordinates"],
            "updated_at": now_iso,
        })

    return results
