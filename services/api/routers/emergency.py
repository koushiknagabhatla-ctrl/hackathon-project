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

# Snapshot cache: (timestamp, jpeg-bytes) per camera, so a grid of tiles
# refreshing in step cannot flood a camera.
_SNAP_CACHE: dict[str, tuple[float, bytes]] = {}
_SNAP_TTL_S = 1.5

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


class SMSBroadcastIn(BaseModel):
    phone_number: str = Field(..., description="10-digit Indian mobile number")
    message: str = Field(..., max_length=160, description="SMS message text")
    incident_id: str | None = None
    recipient_category: str = "citizen_emergency"


@router.get("/sms/wallet")
def get_sms_wallet_status(principal: dict = Depends(get_principal)) -> Any:
    """Check active Fast2SMS wallet balance and SMS credits."""
    from services.api.adapters.sms_fast2sms import check_sms_wallet
    return check_sms_wallet()


@router.post("/sms/send")
def send_emergency_sms_endpoint(
    body: SMSBroadcastIn,
    principal: dict = Depends(get_principal),
) -> Any:
    """Dispatch an emergency alert SMS directly to a mobile number via Fast2SMS."""
    from services.api.adapters.sms_fast2sms import send_emergency_sms
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    incident_id = body.incident_id or f"inc_manual_{uuid.uuid4().hex[:8]}"
    return send_emergency_sms(
        to_phone=body.phone_number,
        message_text=body.message,
        incident_id=incident_id,
        recipient_category=body.recipient_category,
        tenant_id=tenant_id,
    )


# ─────────────────────────────────────────────────────────────── CCTV

@router.get("/cctv/status")
def cctv_status() -> Any:
    """Detector availability and the last polling cycle."""
    from services.api.core import cctv_worker

    return cctv_worker.model_status()


@router.get("/cctv/cameras")
def cctv_cameras(tenant_id: str = "ten_vijayawada") -> Any:
    from services.api.core import cctv_worker

    cams = cctv_worker.list_cameras(tenant_id)
    return {
        "count": len(cams),
        "cameras": [
            {
                "id": c.id, "name": c.name, "lat": c.lat, "lon": c.lon,
                "road_segment": c.road_segment, "enabled": c.enabled,
                "authorized_by": c.authorized_by, "sample_fps": c.sample_fps,
                # The URL can carry credentials, so it is never returned.
                "stream_configured": bool(c.stream_url),
            }
            for c in cams
        ],
    }


class CameraIn(BaseModel):
    name: str
    stream_url: str
    lat: float
    lon: float
    authorized_by: str
    road_segment: str = ""
    sample_fps: float | None = None
    tenant_id: str = "ten_vijayawada"


@router.post("/cctv/cameras")
def cctv_register(body: CameraIn) -> Any:
    from services.api.core import cctv_worker

    return cctv_worker.register_camera(
        name=body.name, stream_url=body.stream_url, lat=body.lat, lon=body.lon,
        authorized_by=body.authorized_by, road_segment=body.road_segment,
        sample_fps=body.sample_fps, tenant_id=body.tenant_id,
    )


@router.post("/cctv/poll")
def cctv_poll(tenant_id: str = "ten_vijayawada", seconds_per_camera: float = 15.0) -> Any:
    """Run one analysis pass now. Bounded so it cannot hang the request."""
    from services.api.core import cctv_worker

    return cctv_worker.poll_once(tenant_id, seconds_per_camera=seconds_per_camera)


@router.post("/cctv/worker/start")
def cctv_worker_start(interval_s: float = 60.0, tenant_id: str = "ten_vijayawada") -> Any:
    from services.api.core import cctv_worker

    return cctv_worker.start_worker(interval_s=interval_s, tenant_id=tenant_id)


@router.post("/cctv/worker/stop")
def cctv_worker_stop() -> Any:
    from services.api.core import cctv_worker

    return cctv_worker.stop_worker()


# ──────────────────────────────────────────────────────── public alerting

class AlertIn(BaseModel):
    incident_id: str
    headline: str
    instruction: str = ""
    lat: float
    lon: float
    hazard_kind: str = "other"
    severity: str = "major"
    certainty: str = "Likely"
    area_desc: str = ""
    radius_m: float | None = None
    tenant_id: str = "ten_vijayawada"
    test_mode: bool = True


@router.post("/alerts/public")
def dispatch_alert(body: AlertIn) -> Any:
    """Author a CAP 1.2 alert and deliver it to consenting people in radius.

    Defaults to test_mode: sending a real warning to real phones has to be an
    explicit act, never something a default value does.
    """
    from services.api.core import public_alert

    return public_alert.dispatch_public_alert(
        incident_id=body.incident_id, headline=body.headline,
        instruction=body.instruction, lat=body.lat, lon=body.lon,
        hazard_kind=body.hazard_kind, severity=body.severity,
        certainty=body.certainty, area_desc=body.area_desc,
        radius_m=body.radius_m, tenant_id=body.tenant_id,
        test_mode=body.test_mode,
    )


class SubscriberIn(BaseModel):
    phone_e164: str
    lat: float
    lon: float
    consent_verified: bool = False
    consent_source: str = ""
    language: str = "en"
    tenant_id: str = "ten_vijayawada"


@router.post("/alerts/subscribers")
def add_subscriber(body: SubscriberIn) -> Any:
    """Register someone to be warned. Consent is recorded, not assumed."""
    import uuid
    from datetime import UTC, datetime

    from services.api.core import db

    if body.consent_verified and not body.consent_source.strip():
        return {"status": "error",
                "error": "consent_source is required when consent_verified is true"}

    sid = f"sub_{uuid.uuid4().hex[:10]}"
    now = datetime.now(UTC).isoformat()
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO alert_subscriber(id, tenant_id, phone_e164, language, "
            "last_lat, last_lon, consent_verified, consent_source, active, registered_at, "
            "last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (sid, body.tenant_id, body.phone_e164, body.language, body.lat, body.lon,
             1 if body.consent_verified else 0, body.consent_source or None, 1, now, now),
        )
    return {"status": "ok", "subscriber_id": sid,
            "consent_verified": body.consent_verified,
            "note": ("Only consent_verified subscribers are ever contacted."
                     if not body.consent_verified else None)}


@router.get("/cctv/cameras/near")
def cctv_cameras_near(
    lat: float,
    lon: float,
    radius_km: float = 60.0,
    tenant_id: str = "ten_vijayawada",
) -> Any:
    """Cameras within `radius_km` of a point, nearest first.

    The viewing page asks for the selected city's coordinates, so a town with
    no registered camera gets an empty list and says so, rather than being
    shown somebody else's street.
    """
    import math

    from services.api.core import cctv_worker

    def dist_km(a_lat, a_lon, b_lat, b_lon):
        r = 6371.0
        p1, p2 = math.radians(a_lat), math.radians(b_lat)
        dp = math.radians(b_lat - a_lat)
        dl = math.radians(b_lon - a_lon)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return r * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))

    out = []
    for c in cctv_worker.list_cameras(tenant_id):
        d = dist_km(lat, lon, c.lat, c.lon)
        if d > radius_km:
            continue
        out.append({
            "id": c.id,
            "name": c.name,
            "lat": c.lat,
            "lon": c.lon,
            "road_segment": c.road_segment,
            "enabled": c.enabled,
            "authorized_by": c.authorized_by,
            "sample_fps": c.sample_fps,
            "distance_km": round(d, 2),
            # The URL can carry credentials; only its transport is exposed.
            "transport": (
                "rtsp" if c.stream_url.startswith("rtsp") else
                "hls" if ".m3u8" in c.stream_url else
                "mjpeg" if "mjpg" in c.stream_url.lower() or "mjpeg" in c.stream_url.lower() else
                "file" if "://" not in c.stream_url else "http"
            ),
        })
    out.sort(key=lambda c: c["distance_km"])
    return {"count": len(out), "radius_km": radius_km, "cameras": out}


@router.get("/cctv/cameras/{camera_id}/snapshot")
def cctv_snapshot(camera_id: str, tenant_id: str = "ten_vijayawada") -> Any:
    """One current frame as JPEG.

    Cached briefly so a wall of tiles refreshing together cannot hammer a
    camera that is also serving an operator's own client.
    """
    import time

    import cv2
    from fastapi import Response

    from services.api.core import cctv_worker

    cams = [c for c in cctv_worker.list_cameras(tenant_id) if c.id == camera_id]
    if not cams:
        raise HTTPException(status_code=404, detail="camera not found")
    cam = cams[0]

    cached = _SNAP_CACHE.get(camera_id)
    if cached and (time.time() - cached[0]) < _SNAP_TTL_S:
        return Response(content=cached[1], media_type="image/jpeg",
                        headers={"Cache-Control": "no-store", "X-Auralis-Snapshot": "cached"})

    cap = cv2.VideoCapture(cam.stream_url)
    try:
        if not cap.isOpened():
            raise HTTPException(status_code=503,
                                detail=f"stream for {cam.name} could not be opened")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(status_code=503, detail=f"no frame from {cam.name}")
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
        if not ok:
            raise HTTPException(status_code=500, detail="frame could not be encoded")
    finally:
        cap.release()

    data = buf.tobytes()
    _SNAP_CACHE[camera_id] = (time.time(), data)
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Auralis-Snapshot": "live"})


@router.post("/cctv/cameras/{camera_id}/analyze")
def cctv_analyze_one(
    camera_id: str,
    seconds: float = 12.0,
    tenant_id: str = "ten_vijayawada",
) -> Any:
    """Run a bounded analysis pass on one camera and return what it saw."""
    from services.api.core import cctv_worker

    cams = [c for c in cctv_worker.list_cameras(tenant_id) if c.id == camera_id]
    if not cams:
        raise HTTPException(status_code=404, detail="camera not found")
    return cctv_worker.analyze_stream(cams[0], max_seconds=seconds, max_frames=45)


@router.delete("/cctv/cameras/{camera_id}")
def cctv_delete(camera_id: str, tenant_id: str = "ten_vijayawada") -> Any:
    from services.api.core import db

    with db.tx() as c:
        c.execute("DELETE FROM camera WHERE id = ? AND tenant_id = ?", (camera_id, tenant_id))
    return {"status": "ok", "deleted": camera_id}


@router.get("/cctv/public-webcams")
def cctv_public_webcams(lat: float, lon: float, radius_km: float = 100.0, limit: int = 12) -> Any:
    """Fallback path: webcams whose operators published them.

    Used when no camera is registered for the selected place. These are not the
    city's own traffic cameras and are labelled as such in the UI.
    """
    from services.api.connectors import public_webcams

    return public_webcams.find_nearby(lat=lat, lon=lon, radius_km=radius_km, limit=limit)
