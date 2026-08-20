"""Firebase Cloud Messaging (FCM) Emergency Push Notification Adapter.

Sends emergency push notifications to registered, permission-consenting devices
located within a spatial danger geofence of an emergency incident.

Zero-fabrication rule: Only devices with verified registrations in the database
are targeted. Never broadcasts to arbitrary unconsented phones.
"""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from services.api.core import db

log = logging.getLogger(__name__)

FCM_SEND_URL = "https://fcm.googleapis.com/fcm/send"


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def find_nearby_registered_devices(
    incident_lat: float,
    incident_lon: float,
    radius_meters: float = 1500.0,
    tenant_id: str = "ten_vijayawada",
) -> list[dict[str, Any]]:
    """Find all registered devices with active location consent within the danger radius."""
    devices = db.q(
        "SELECT * FROM registered_device WHERE tenant_id=? AND opt_in_emergency=1 "
        "AND permissions_granted=1 AND last_lat IS NOT NULL AND last_lon IS NOT NULL",
        tenant_id,
    )
    matching = []
    for d in devices:
        dist = haversine_distance_m(incident_lat, incident_lon, d["last_lat"], d["last_lon"])
        if dist <= radius_meters:
            matching.append({
                "id": d["id"],
                "fcm_token": d["fcm_token"],
                "distance_m": round(dist, 1),
                "device_type": d["device_type"],
            })
    return matching


def send_geofence_emergency_push(
    incident_id: str,
    incident_title: str,
    road_segment: str,
    incident_lat: float,
    incident_lon: float,
    danger_radius_m: float = 1500.0,
    tenant_id: str = "ten_vijayawada",
) -> dict[str, Any]:
    """Broadcast an emergency push notification to registered devices in the geofence."""
    fcm_server_key = os.environ.get("FIREBASE_SERVER_KEY") or os.environ.get("FCM_SERVER_KEY")
    nearby_devices = find_nearby_registered_devices(incident_lat, incident_lon, danger_radius_m, tenant_id)

    now = datetime.now(timezone.utc).isoformat()
    msg_title = "⚠️ EMERGENCY CIVIC ADVISORY"
    msg_body = (
        f"Verified traffic incident reported on {road_segment or 'monitored corridor'}. "
        f"Slow down and observe emergency responder diversions."
    )

    if not nearby_devices:
        return {
            "status": "completed",
            "recipients_count": 0,
            "danger_radius_m": danger_radius_m,
            "message": "No registered consenting devices currently inside the calculated danger radius.",
        }

    sent_count = 0
    failed_count = 0

    for dev in nearby_devices:
        notif_id = f"fcm_{uuid.uuid4().hex[:12]}"
        if not fcm_server_key:
            # Server key unconfigured -> record honest unconfigured state
            with db.tx() as c:
                c.execute(
                    "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                    "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (notif_id, tenant_id, incident_id, "fcm_push", dev["id"], "public_geofence",
                     msg_body, "failed", "FCM server key unconfigured on backend", now),
                )
            failed_count += 1
            continue

        # Live FCM Dispatch
        headers = {
            "Authorization": f"key={fcm_server_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "to": dev["fcm_token"],
            "notification": {"title": msg_title, "body": msg_body},
            "data": {
                "incident_id": incident_id,
                "lat": str(incident_lat),
                "lon": str(incident_lon),
                "radius_m": str(danger_radius_m),
            },
            "priority": "high",
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(FCM_SEND_URL, headers=headers, json=payload)
                if res.status_code == 200:
                    sent_count += 1
                    with db.tx() as c:
                        c.execute(
                            "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                            "recipient_id, recipient_category, message_text, status, provider_ref, created_at, delivered_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (notif_id, tenant_id, incident_id, "fcm_push", dev["id"], "public_geofence",
                             msg_body, "sent", f"fcm_res_{res.status_code}", now, now),
                        )
                else:
                    failed_count += 1
                    with db.tx() as c:
                        c.execute(
                            "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                            "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (notif_id, tenant_id, incident_id, "fcm_push", dev["id"], "public_geofence",
                             msg_body, "failed", f"HTTP {res.status_code}: {res.text[:100]}", now),
                        )
        except Exception as exc:
            failed_count += 1
            with db.tx() as c:
                c.execute(
                    "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                    "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (notif_id, tenant_id, incident_id, "fcm_push", dev["id"], "public_geofence",
                     msg_body, "failed", str(exc), now),
                )

    return {
        "status": "completed",
        "recipients_targeted": len(nearby_devices),
        "sent_successfully": sent_count,
        "failed_or_unconfigured": failed_count,
        "danger_radius_m": danger_radius_m,
    }
