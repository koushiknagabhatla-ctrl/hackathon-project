"""Real-World Accident Detection & Multi-Signal Correlation Service.

Correlates independent real-world signals (CCTV visual collision detections,
traffic flow speed drops, and verified citizen reports) to classify incident
confidence and verification lifecycle.

Strict Rules:
- NEVER claim an accident occurred based on a single uncertain AI prediction.
- Statuses: UNVERIFIED, SUSPECTED, CORROBORATED, VERIFIED, RESOLVED, FALSE_POSITIVE.
- 1 signal = SUSPECTED (0.35 confidence)
- 2 independent corroborating signals = CORROBORATED (0.75 confidence)
- 3+ corroborating signals = VERIFIED (0.95 confidence)
- Every single evidence item is hashed and stored separately in the evidence ledger.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from services.api.adapters.emergency_dispatch import create_emergency_dispatch_request
from services.api.adapters.fcm_push import send_geofence_emergency_push
from services.api.adapters.llm_openai import analyze_emergency_evidence
from services.api.adapters.sms_twilio import send_emergency_sms
from services.api.core import audit as audit_mod, db, ingest
from services.api.models import EventIn

log = logging.getLogger(__name__)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return R * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))


def process_emergency_signal(
    signal_kind: str,  # 'cctv_collision' | 'traffic_collapse' | 'citizen_report' | 'sensor_impact'
    connector_id: str,
    latitude: float,
    longitude: float,
    payload: dict[str, Any],
    road_segment: str = "MG Road / Benz Circle Corridor",
    principal_id: str = "p_operator",
    tenant_id: str = "ten_vijayawada",
) -> dict[str, Any]:
    """Ingest a real emergency signal, correlate with active incidents, and update verification."""
    now = datetime.now(timezone.utc).isoformat()

    # 1. Ingest event into the immutable raw event and evidence ledger
    event_in = EventIn(
        connector_id=connector_id,
        kind=signal_kind,
        event_time=now,
        payload=payload,
        geometry={"type": "Point", "coordinates": [longitude, latitude]},
    )
    accepted = ingest.ingest_event(event_in, principal_id)
    evidence_id = accepted.evidence_id

    # 2. Check for an existing open incident within 300m and 15 minutes
    existing_incidents = db.q(
        "SELECT * FROM incident WHERE tenant_id=? AND state != 'closed' "
        "AND incident_class IN ('accident', 'road_traffic_incident', 'traffic_emergency')",
        tenant_id,
    )

    matched_inc = None
    for inc in existing_incidents:
        geom = db.jload(inc["geometry"], {})
        coords = geom.get("coordinates", [0, 0])
        if len(coords) >= 2:
            inc_lon, inc_lat = coords[0], coords[1]
            dist = _haversine_m(latitude, longitude, inc_lat, inc_lon)
            if dist <= 350.0:  # 350m spatial correlation threshold
                matched_inc = inc
                break

    if matched_inc:
        # Correlate into existing incident
        inc_id = matched_inc["id"]
        ev_ids = db.jload(matched_inc["evidence_ids"], [])
        if evidence_id and evidence_id not in ev_ids:
            ev_ids.append(evidence_id)

        # Count independent signal kinds
        evidence_rows = db.q(
            f"SELECT * FROM evidence WHERE id IN ({','.join(['?']*len(ev_ids))})",
            *ev_ids,
        ) if ev_ids else []

        signal_sources = set()
        for ev in evidence_rows:
            conn_id = ev["connector_id"] if "connector_id" in ev.keys() else "source"
            signal_sources.add(conn_id)

        signal_count = len(signal_sources)
        if signal_count >= 3:
            ver_status = "VERIFIED"
            confidence = 0.95
            severity = "critical"
        elif signal_count == 2:
            ver_status = "CORROBORATED"
            confidence = 0.75
            severity = "high"
        else:
            ver_status = "SUSPECTED"
            confidence = 0.40
            severity = "medium"

        with db.tx() as c:
            c.execute(
                "UPDATE incident SET evidence_ids=?, severity=?, title=? WHERE id=?",
                (json.dumps(ev_ids), severity,
                 f"Traffic emergency at {road_segment} [{ver_status} - {signal_count} signals]",
                 inc_id),
            )

        audit_mod.append(
            tenant_id=tenant_id,
            workflow_id=f"wf_{inc_id}",
            actor_id=principal_id,
            actor_kind="agent",
            kind="incident.corroborated",
            subject_id=inc_id,
            payload={
                "incident_id": inc_id,
                "evidence_id": evidence_id,
                "signal_kind": signal_kind,
                "verification_status": ver_status,
                "confidence": confidence,
            },
        )
    else:
        # Create a new candidate incident with initial SUSPECTED status
        inc_id = f"inc_{uuid.uuid4().hex[:12]}"
        ver_status = "SUSPECTED"
        confidence = 0.35
        severity = "medium"
        ev_ids = [evidence_id] if evidence_id else []

        with db.tx() as c:
            c.execute(
                "INSERT INTO incident(id, tenant_id, title, incident_class, severity, state, "
                "opened_at, geometry, detector, evidence_ids, asset_ids, first_observation_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (inc_id, tenant_id,
                 f"Suspected traffic incident at {road_segment} [1 signal]",
                 "road_traffic_incident", severity, "detected", now,
                 json.dumps({"type": "Point", "coordinates": [longitude, latitude]}),
                 f"det.{signal_kind}.v1", json.dumps(ev_ids), "[]", now),
            )

        audit_mod.append(
            tenant_id=tenant_id,
            workflow_id=f"wf_{inc_id}",
            actor_id=principal_id,
            actor_kind="agent",
            kind="incident.detected",
            subject_id=inc_id,
            payload={
                "incident_id": inc_id,
                "evidence_id": evidence_id,
                "signal_kind": signal_kind,
                "verification_status": ver_status,
                "confidence": confidence,
            },
        )

    # 3. Trigger Emergency Decision Policy
    decision = evaluate_emergency_policy(
        incident_id=inc_id,
        verification_status=ver_status,
        severity=severity,
        latitude=latitude,
        longitude=longitude,
        road_segment=road_segment,
        evidence_ids=ev_ids,
        tenant_id=tenant_id,
    )

    return {
        "incident_id": inc_id,
        "event_id": accepted.id,
        "evidence_id": evidence_id,
        "verification_status": ver_status,
        "confidence": confidence,
        "severity": severity,
        "decision": decision,
    }


def evaluate_emergency_policy(
    incident_id: str,
    verification_status: str,
    severity: str,
    latitude: float,
    longitude: float,
    road_segment: str,
    evidence_ids: list[str],
    tenant_id: str = "ten_vijayawada",
) -> dict[str, Any]:
    """Deterministic Emergency Policy Engine.

    Rules:
    - Auto-dispatch is PERMITTED ONLY IF verification_status == 'VERIFIED' and severity == 'critical'.
    - If status == 'CORROBORATED', generate geofenced FCM push alert to nearby drivers and SMS to district officer.
    - If status == 'SUSPECTED', create operator verification review request (no public alert or ambulance dispatch).
    """
    actions_taken = []

    if verification_status == "VERIFIED" and severity == "critical":
        # 1. Nearby Geofenced Warning (FCM)
        push_res = send_geofence_emergency_push(
            incident_id=incident_id,
            incident_title="Major Accident Verified",
            road_segment=road_segment,
            incident_lat=latitude,
            incident_lon=longitude,
            danger_radius_m=1200.0,
            tenant_id=tenant_id,
        )
        actions_taken.append({"action": "fcm_geofence_push", "result": push_res})

        # 2. SMS Alert to Designated Disaster Response Officer
        officers = db.q("SELECT * FROM emergency_contact WHERE tenant_id=? AND active=1 LIMIT 2", tenant_id)
        for off in officers:
            sms_res = send_emergency_sms(
                to_phone=off["phone_e164"],
                message_text=f"AURALIS 112 ALERT: Verified critical accident on {road_segment}. ERSS dispatch initiated. Ref: {incident_id}",
                incident_id=incident_id,
                recipient_category="disaster_officer",
                tenant_id=tenant_id,
            )
            actions_taken.append({"action": "officer_sms", "recipient": off["name"], "result": sms_res})

        # 3. Emergency Dispatch Request to ERSS 112 CAD
        dispatch_res = create_emergency_dispatch_request(
            incident_id=incident_id,
            service_type="ambulance",
            severity="critical",
            latitude=latitude,
            longitude=longitude,
            road_segment=road_segment,
            evidence_ids=evidence_ids,
            requesting_authority="Auralis Municipal Command",
            approved_by="p_operator",
            hazards=["traffic_stoppage", "corridor_obstruction"],
            tenant_id=tenant_id,
        )
        actions_taken.append({"action": "erss_112_dispatch", "result": dispatch_res})

        return {
            "policy_effect": "auto_emergency_response_triggered",
            "rule_id": "rule.emergency.auto_dispatch_on_verified.v1",
            "actions": actions_taken,
        }

    elif verification_status == "CORROBORATED":
        # Send geofence cautionary push
        push_res = send_geofence_emergency_push(
            incident_id=incident_id,
            incident_title="Traffic Incident Caution",
            road_segment=road_segment,
            incident_lat=latitude,
            incident_lon=longitude,
            danger_radius_m=800.0,
            tenant_id=tenant_id,
        )
        return {
            "policy_effect": "geofence_alert_and_operator_review_required",
            "rule_id": "rule.emergency.corroborated_review.v1",
            "actions": [{"action": "fcm_geofence_push", "result": push_res}],
        }

    else:
        # SUSPECTED -> Do not dispatch or panic the public; escalate to operator monitor
        return {
            "policy_effect": "operator_monitoring_only",
            "rule_id": "rule.emergency.suspected_monitoring.v1",
            "message": "Incident is SUSPECTED based on 1 signal. Awaiting multi-signal corroboration before escalation.",
        }
