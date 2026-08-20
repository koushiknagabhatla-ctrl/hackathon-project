"""Emergency Response API Router.

Surfaces endpoints for accident detection signals, multi-signal correlation,
ERSS 112 emergency dispatch tracking, and FCM device registration.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.adapters.emergency_dispatch import create_emergency_dispatch_request
from services.api.adapters.llm_openai import analyze_emergency_evidence
from services.api.auth import get_principal
from services.api.core import accident_detector, db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/emergency", tags=["Emergency Response"])


class SignalIn(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    road_segment: str = Field(default="MG Road / Benz Circle Corridor")
    payload: dict[str, Any] = Field(default_factory=dict)


class DeviceRegisterIn(BaseModel):
    fcm_token: str
    device_type: str = "web"
    latitude: float | None = None
    longitude: float | None = None
    opt_in_emergency: bool = True


class ManualDispatchIn(BaseModel):
    service_type: str = "ambulance"
    severity: str = "critical"
    road_segment: str = "MG Road"
    hazards: list[str] = Field(default_factory=list)


@router.post("/cctv/event")
def post_cctv_collision(body: SignalIn, principal: dict = Depends(get_principal)) -> Any:
    """Ingest a camera-based collision detection signal."""
    return accident_detector.process_emergency_signal(
        signal_kind="cctv_collision",
        connector_id="conn_traffic_cam_01",
        latitude=body.latitude,
        longitude=body.longitude,
        payload={
            "detector": "cctv_optical_flow_v2",
            "collision_probability": 0.88,
            "vehicle_count": body.payload.get("vehicle_count", 2),
            **body.payload,
        },
        road_segment=body.road_segment,
        principal_id=principal.get("id", "p_operator"),
        tenant_id=principal.get("tenant_id", "ten_vijayawada"),
    )


@router.post("/traffic/event")
def post_traffic_collapse(body: SignalIn, principal: dict = Depends(get_principal)) -> Any:
    """Ingest a traffic flow speed collapse signal."""
    return accident_detector.process_emergency_signal(
        signal_kind="traffic_collapse",
        connector_id="conn_tomtom_traffic",
        latitude=body.latitude,
        longitude=body.longitude,
        payload={
            "detector": "loop_speed_drop_v1",
            "current_speed_kph": body.payload.get("speed_kph", 4.0),
            "free_flow_kph": 50.0,
            "speed_drop_ratio": 0.92,
            **body.payload,
        },
        road_segment=body.road_segment,
        principal_id=principal.get("id", "p_operator"),
        tenant_id=principal.get("tenant_id", "ten_vijayawada"),
    )


@router.post("/citizen/report")
def post_citizen_report(body: SignalIn, principal: dict = Depends(get_principal)) -> Any:
    """Ingest a verified citizen emergency report."""
    return accident_detector.process_emergency_signal(
        signal_kind="citizen_report",
        connector_id="conn_open311",
        latitude=body.latitude,
        longitude=body.longitude,
        payload={
            "channel": "open311_mobile",
            "report_text": body.payload.get("text", "Vehicular collision observed. Traffic stopped."),
            **body.payload,
        },
        road_segment=body.road_segment,
        principal_id=principal.get("id", "p_operator"),
        tenant_id=principal.get("tenant_id", "ten_vijayawada"),
    )


@router.post("/devices/register")
def register_device(body: DeviceRegisterIn, principal: dict = Depends(get_principal)) -> Any:
    """Register an FCM push token for spatial geofenced emergency alerts."""
    now = datetime.now(timezone.utc).isoformat()
    dev_id = f"dev_{uuid.uuid4().hex[:12]}"
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO registered_device(id, tenant_id, user_id, fcm_token, "
            "device_type, last_lat, last_lon, opt_in_emergency, permissions_granted, "
            "registered_at, last_seen_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (dev_id, principal.get("tenant_id", "ten_vijayawada"), principal.get("id", "p_operator"),
             body.fcm_token, body.device_type, body.latitude, body.longitude,
             1 if body.opt_in_emergency else 0, 1, now, now),
        )
    return {"status": "registered", "device_id": dev_id, "registered_at": now}


@router.get("/dispatches")
def list_dispatches(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    """List all emergency dispatch records and confirmation statuses."""
    rows = db.q(
        "SELECT * FROM emergency_dispatch WHERE tenant_id=? ORDER BY created_at DESC LIMIT 50",
        principal.get("tenant_id", "ten_vijayawada"),
    )
    return [
        {
            "id": r["id"],
            "incident_id": r["incident_id"],
            "service_type": r["service_type"],
            "severity": r["severity"],
            "coordinates": [r["longitude"], r["latitude"]],
            "road_segment": r["road_segment"],
            "status": r["status"],
            "external_ref": r["external_ref"],
            "eta_minutes": r["eta_minutes"],
            "requesting_authority": r["requesting_authority"],
            "created_at": r["created_at"],
            "confirmed_at": r["confirmed_at"],
            "hazards": db.jload(r["hazards_reported"], []),
        }
        for r in rows
    ]


@router.post("/incidents/{incident_id}/analyze")
def analyze_incident_ai(incident_id: str, principal: dict = Depends(get_principal)) -> Any:
    """Run OpenAI analysis strictly on grounded evidence for the incident."""
    inc = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    ev_ids = db.jload(inc["evidence_ids"], [])
    evidence_items = []
    if ev_ids:
        rows = db.q(f"SELECT * FROM evidence WHERE id IN ({','.join(['?']*len(ev_ids))})", *ev_ids)
        evidence_items = [
            {"id": r["id"], "subject": r["subject"], "value": db.jload(r["value_json"], {}),
             "observed_at": r["observed_at"], "trust_tier": r["trust_tier"]}
            for r in rows
        ]

    return analyze_emergency_evidence(dict(inc), evidence_items)


@router.post("/incidents/{incident_id}/dispatch")
def manual_operator_dispatch(
    incident_id: str,
    body: ManualDispatchIn,
    principal: dict = Depends(get_principal),
) -> Any:
    """Operator manual emergency dispatch execution."""
    inc = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    geom = db.jload(inc["geometry"], {})
    coords = geom.get("coordinates", [80.6480, 16.5062])
    lon, lat = coords[0], coords[1]
    ev_ids = db.jload(inc["evidence_ids"], [])

    return create_emergency_dispatch_request(
        incident_id=incident_id,
        service_type=body.service_type,
        severity=body.severity,
        latitude=lat,
        longitude=lon,
        road_segment=body.road_segment,
        evidence_ids=ev_ids,
        requesting_authority=f"Auralis Operator ({principal.get('display_name', 'Operator')})",
        approved_by=principal.get("id", "p_operator"),
        hazards=body.hazards,
        tenant_id=principal.get("tenant_id", "ten_vijayawada"),
    )
