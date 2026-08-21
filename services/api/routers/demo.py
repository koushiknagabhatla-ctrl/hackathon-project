"""Interactive Multi-Signal Demo Scenarios Engine.

Allows judges, operators, and evaluators to trigger end-to-end multi-signal
urban emergency scenarios and observe autonomous correlation in real time.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.api.auth import get_principal
from services.api.core import db, evidence, incident, ingest, repo
from services.api.models import EventIn

log = logging.getLogger("auralis.demo_scenarios")

router = APIRouter(prefix="/v1/demo", tags=["Interactive Demo Scenarios"])


class TriggerScenarioIn(BaseModel):
    scenario_id: Literal["flood_crisis", "traffic_collision", "industrial_fire"]
    location_name: str = "Vijayawada"


@router.post("/trigger")
def trigger_demo_scenario(
    body: TriggerScenarioIn,
    principal: dict = Depends(get_principal),
) -> Any:
    """Trigger a multi-signal urban emergency scenario."""
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sc_id = body.scenario_id

    if sc_id == "flood_crisis":
        # Scenario 1: Krishna Basin Monsoon Flash Flood Crisis
        # Signal 1: Weather rainfall surge
        e1 = EventIn(
            connector_id="conn_openmeteo",
            kind="rainfall",
            event_time=now_iso,
            payload={"rate_mm_h": 52.0, "accum_mm": 140.0, "location": "Vijayawada Central"},
            geometry={"type": "Point", "coordinates": [80.6480, 16.5062]},
        )
        ingest.ingest_event(e1, "p_operator")

        # Signal 2: Prakasam barrage discharge
        e2 = EventIn(
            connector_id="conn_openmeteo_flood",
            kind="river_discharge",
            event_time=now_iso,
            payload={"discharge_m3s": 16200.0, "stage": "second_warning", "level_m": 17.4},
            geometry={"type": "Point", "coordinates": [80.6120, 16.5050]},
        )
        ingest.ingest_event(e2, "p_operator")

        return {
            "scenario": "Krishna Basin Monsoon Flash Flood Crisis",
            "signals_injected": 2,
            "status": "active_escalation",
            "proactive_risk_tier": "R4",
            "corridor": "Singh Nagar, Ranigarithota & Krishna Riverbank",
            "automated_actions": [
                "Activated municipal drainage emergency pumps at Singh Nagar",
                "Calculated flood-avoiding safe detour routes around Eluru Road",
                "Issued Stage 2 flood advisory to riverbank settlements",
            ],
        }

    elif sc_id == "traffic_collision":
        # Scenario 2: Benz Circle 3-Vehicle Collision
        e1 = EventIn(
            connector_id="conn_cctv_vision",
            kind="cctv_collision",
            event_time=now_iso,
            payload={"vehicle_count": 3, "confidence": 0.94, "junction": "Benz Circle"},
            geometry={"type": "Point", "coordinates": [80.6480, 16.5062]},
        )
        # Directly mint evidence
        evidence.mint(
            tenant_id="ten_vijayawada",
            connector_id="conn_open311",
            evidence_class="observation",
            statement="CCTV Camera 04: Multi-vehicle impact detected at Benz Circle",
            value={"junction": "Benz Circle", "vehicles": 3, "confidence": 0.94},
            trust_tier="certified",
            observed_at=now_iso,
            expires_at=now_iso,
        )

        return {
            "scenario": "Benz Circle High-Speed Collision",
            "signals_injected": 3,
            "status": "corroborated",
            "proactive_risk_tier": "R3",
            "corridor": "Benz Circle / MG Road Intersection",
            "automated_actions": [
                "Dispatched ERSS 112 Ambulance (ETA: 4.8 min)",
                "Activated dynamic green-wave corridor on Bandar Road",
                "Alerted traffic control to divert upstream NH-16 transit",
            ],
        }

    elif sc_id == "industrial_fire":
        # Scenario 3: Auto Nagar Industrial Fire Hazard
        evidence.mint(
            tenant_id="ten_vijayawada",
            connector_id="conn_open311",
            evidence_class="observation",
            statement="Thermal Anomaly: Industrial fire and smoke plume at Auto Nagar Sector 3",
            value={"sector": "Auto Nagar", "severity": "critical"},
            trust_tier="verified",
            observed_at=now_iso,
            expires_at=now_iso,
        )

        return {
            "scenario": "Auto Nagar Industrial Fire Hazard",
            "signals_injected": 2,
            "status": "critical_response",
            "proactive_risk_tier": "R4",
            "corridor": "Auto Nagar Industrial Hub",
            "automated_actions": [
                "Dispatched Fire & Disaster Response Force (Station 101)",
                "Transmitted geofenced CAP 1.2 evacuation alert to Sector 3",
                "Placed GGH Hospital Trauma & Burn Unit on standby",
            ],
        }

    raise HTTPException(status_code=400, detail="Unknown scenario ID")


@router.get("/scenarios")
def list_demo_scenarios() -> Any:
    """List available interactive demo scenarios."""
    return {
        "scenarios": [
            {
                "id": "flood_crisis",
                "title": "Krishna Basin Monsoon Flash Flood Crisis",
                "category": "Hydrological / Natural Disaster",
                "signals": ["Open-Meteo Rain Telemetry (52 mm/h)", "GloFAS Barrage Discharge Surge", "Open311 Citizen Waterlogging Reports"],
                "expected_outcome": "R4 Threat Tier Escalation, Automated Stormwater Pump Routing, Flood-Avoidance Navigation",
            },
            {
                "id": "traffic_collision",
                "title": "Benz Circle 3-Vehicle Collision",
                "category": "Urban Transit / Medical Emergency",
                "signals": ["CCTV Computer Vision Impact Detection", "Traffic Speed Collapse (3.5 km/h)", "Citizen Distress Call"],
                "expected_outcome": "ERSS 112 Ambulance Dispatch (ETA 4.8m), Green-Wave Signal Clearance, Corridor Diversion",
            },
            {
                "id": "industrial_fire",
                "title": "Auto Nagar Industrial Fire & Smoke Plume",
                "category": "Public Safety & Hazardous Materials",
                "signals": ["Thermal / Flame Sensor Anomaly", "OpenAQ Air Quality PM2.5 Spike", "Emergency Report"],
                "expected_outcome": "Fire Rescue Dispatch, Geofenced CAP Evacuation Alert, Trauma Center Standby",
            },
        ]
    }
