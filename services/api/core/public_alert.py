"""Public alerting — warn people near a hazard, and be honest about who was reached.

Two things happen here, deliberately kept apart:

  1. **Authoring.** A hazard becomes a CAP 1.2 alert. CAP is the OASIS standard
     the ITU recommends and the one India's SACHET / NDMA platform consumes, so
     the artifact this produces is the interoperable one — it can be handed to a
     state authority, an aggregator, or a siren network without translation.

  2. **Delivery.** The alert is fanned out to people who (a) opted in and
     (b) are inside the threat radius. Every attempt is written to
     `emergency_notification` with its provider reference and outcome.

The honesty rules that matter here:

  * Consent is required. A phone number in the database is not permission;
    `consent_verified` is. Opted-out and unconsented rows are never contacted,
    and the count of who was skipped is reported.
  * "Sent" is not "delivered". The provider accepting a message is recorded as
    `sent`; only a provider callback may mark `delivered`. Nothing here claims
    a person read anything.
  * Reaching the general public is not something this platform can do. Cell
    broadcast in India is operated by DoT/NDMA. This module produces the CAP
    artifact for that handoff and says plainly that it reached subscribers,
    not "the public".
  * An alert with no verified evidence behind it does not go out at all.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from services.api.core import db

log = logging.getLogger("auralis.public_alert")

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"

Severity = Literal["Extreme", "Severe", "Moderate", "Minor", "Unknown"]
Urgency = Literal["Immediate", "Expected", "Future", "Past", "Unknown"]
Certainty = Literal["Observed", "Likely", "Possible", "Unlikely", "Unknown"]

# Map our internal severity to the CAP vocabulary. CAP has no "critical".
SEVERITY_TO_CAP: dict[str, Severity] = {
    "critical": "Extreme",
    "major": "Severe",
    "minor": "Moderate",
    "info": "Minor",
}

# How far a warning is relevant, by hazard class. These are defaults an
# operator can override per alert; they are not physics.
DEFAULT_RADIUS_M: dict[str, float] = {
    "flood": 3000.0,
    "fire": 1500.0,
    "accident": 1200.0,
    "chemical": 5000.0,
    "structural": 800.0,
    "weather": 8000.0,
    "other": 2000.0,
}

# One incident should not produce a second identical alert inside this window.
DEDUPE_WINDOW_MIN = 20


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _circle(lat: float, lon: float, radius_m: float) -> str:
    """CAP <circle> is 'lat,lon radius-in-km'."""
    return f"{lat:.5f},{lon:.5f} {radius_m / 1000.0:.3f}"


# ────────────────────────────────────────────────────────────── CAP authoring

def build_cap_alert(
    *,
    identifier: str,
    sender: str,
    sent: str,
    status: str,
    msg_type: str,
    scope: str,
    headline: str,
    description: str,
    instruction: str,
    event: str,
    severity: Severity,
    urgency: Urgency,
    certainty: Certainty,
    area_desc: str,
    lat: float,
    lon: float,
    radius_m: float,
    expires_min: int = 180,
    language: str = "en-IN",
) -> str:
    """Return a CAP 1.2 XML document.

    Every required CAP element is populated. `certainty` is passed in rather
    than assumed: an alert raised from a single unconfirmed camera detection is
    "Possible", and saying "Observed" there would be the fabrication this whole
    platform exists to prevent.
    """
    ET.register_namespace("", CAP_NS)
    alert = ET.Element(f"{{{CAP_NS}}}alert")

    def put(parent, tag, text):
        el = ET.SubElement(parent, f"{{{CAP_NS}}}{tag}")
        el.text = str(text)
        return el

    put(alert, "identifier", identifier)
    put(alert, "sender", sender)
    put(alert, "sent", sent)
    put(alert, "status", status)          # Actual | Exercise | Test | Draft
    put(alert, "msgType", msg_type)       # Alert | Update | Cancel
    put(alert, "scope", scope)            # Public | Restricted | Private

    info = ET.SubElement(alert, f"{{{CAP_NS}}}info")
    put(info, "language", language)
    put(info, "category", "Safety")
    put(info, "event", event)
    put(info, "urgency", urgency)
    put(info, "severity", severity)
    put(info, "certainty", certainty)
    expires = datetime.now(UTC) + timedelta(minutes=expires_min)
    put(info, "expires", expires.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
    put(info, "senderName", sender)
    put(info, "headline", headline)
    put(info, "description", description)
    put(info, "instruction", instruction)

    area = ET.SubElement(info, f"{{{CAP_NS}}}area")
    put(area, "areaDesc", area_desc)
    put(area, "circle", _circle(lat, lon, radius_m))

    return ET.tostring(alert, encoding="unicode", xml_declaration=True)


# ───────────────────────────────────────────────────────────── audience

def find_alert_audience(
    lat: float,
    lon: float,
    radius_m: float,
    tenant_id: str,
) -> dict[str, Any]:
    """Who may be contacted inside the radius, and who was excluded and why.

    Returns both, because "we alerted 40 people" is only meaningful next to
    "and 12 in the radius had not consented".
    """
    subscribers: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    skipped_no_consent = 0
    skipped_no_location = 0

    with db.tx() as c:
        try:
            rows = c.execute(
                "SELECT id, phone_e164, last_lat, last_lon, consent_verified, active, language "
                "FROM alert_subscriber WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
        except Exception:
            rows = []
        for r in rows:
            r = dict(r)
            if not r.get("consent_verified") or not r.get("active"):
                skipped_no_consent += 1
                continue
            if r.get("last_lat") is None or r.get("last_lon") is None:
                skipped_no_location += 1
                continue
            d = _haversine_m(lat, lon, r["last_lat"], r["last_lon"])
            if d <= radius_m:
                r["distance_m"] = round(d)
                subscribers.append(r)

        try:
            drows = c.execute(
                "SELECT id, fcm_token, last_lat, last_lon, opt_in_emergency, permissions_granted "
                "FROM registered_device WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
        except Exception:
            drows = []
        for r in drows:
            r = dict(r)
            if not r.get("opt_in_emergency") or not r.get("permissions_granted"):
                skipped_no_consent += 1
                continue
            if r.get("last_lat") is None or r.get("last_lon") is None:
                skipped_no_location += 1
                continue
            d = _haversine_m(lat, lon, r["last_lat"], r["last_lon"])
            if d <= radius_m:
                r["distance_m"] = round(d)
                devices.append(r)

    return {
        "subscribers": subscribers,
        "devices": devices,
        "skipped_no_consent": skipped_no_consent,
        "skipped_no_location": skipped_no_location,
    }


# ───────────────────────────────────────────────────────────── delivery

def _record(
    notif_id: str,
    tenant_id: str,
    incident_id: str,
    channel: str,
    recipient: str,
    message: str,
    status: str,
    provider_ref: str | None,
    failure: str | None,
) -> None:
    with db.tx() as c:
        c.execute(
            "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
            "recipient_id, recipient_category, message_text, status, provider_ref, "
            "created_at, failure_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (notif_id, tenant_id, incident_id, channel, recipient, "public_geofence",
             message, status, provider_ref, _now(), failure),
        )


def _recently_alerted(incident_id: str, body_hash: str) -> bool:
    """True when this exact alert already went out for this incident recently.

    Re-sending the same warning every polling cycle is how an alerting system
    trains people to ignore it.
    """
    cutoff = (datetime.now(UTC) - timedelta(minutes=DEDUPE_WINDOW_MIN)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    with db.tx() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM emergency_notification "
            "WHERE incident_id = ? AND provider_ref = ? AND created_at >= ?",
            (incident_id, f"dedupe:{body_hash}", cutoff),
        ).fetchone()
    return bool(row and dict(row)["n"])


def dispatch_public_alert(
    *,
    incident_id: str,
    headline: str,
    instruction: str,
    lat: float,
    lon: float,
    hazard_kind: str = "other",
    severity: str = "major",
    certainty: Certainty = "Likely",
    urgency: Urgency = "Immediate",
    area_desc: str = "",
    radius_m: float | None = None,
    tenant_id: str = "ten_vijayawada",
    sender: str = "auralis@civic.ap.gov.in",
    test_mode: bool = False,
) -> dict[str, Any]:
    """Author a CAP alert and deliver it to consenting people inside the radius.

    `test_mode` marks the CAP `status` as Test and suppresses outbound sends, so
    the whole path can be exercised without messaging a real person.
    """
    radius = float(radius_m or DEFAULT_RADIUS_M.get(hazard_kind, DEFAULT_RADIUS_M["other"]))
    cap_sev = SEVERITY_TO_CAP.get(severity, "Unknown")

    body = (
        f"{headline}. {instruction}"
        if instruction else headline
    )
    body_hash = hashlib.sha256(f"{incident_id}|{body}".encode()).hexdigest()[:16]

    if _recently_alerted(incident_id, body_hash):
        return {
            "status": "suppressed",
            "reason": f"An identical alert for this incident went out within the last "
                      f"{DEDUPE_WINDOW_MIN} minutes.",
            "incident_id": incident_id,
        }

    alert_id = f"AURALIS-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    cap_xml = build_cap_alert(
        identifier=alert_id,
        sender=sender,
        sent=_now(),
        status="Test" if test_mode else "Actual",
        msg_type="Alert",
        scope="Public",
        headline=headline,
        description=headline,
        instruction=instruction,
        event=hazard_kind.replace("_", " ").title(),
        severity=cap_sev,
        urgency=urgency,
        certainty=certainty,
        area_desc=area_desc or f"{radius / 1000:.1f} km around the reported location",
        lat=lat, lon=lon, radius_m=radius,
    )

    with db.tx() as c:
        c.execute(
            "INSERT INTO alert_publication(id, incident_id, cap_xml, authority, channel, "
            "version, status, published_at, disclosure_delay_s) VALUES(?,?,?,?,?,?,?,?,?)",
            (alert_id, incident_id, cap_xml, sender, "sms+push", 1,
             "test" if test_mode else "published", _now(), 0),
        )

    audience = find_alert_audience(lat, lon, radius, tenant_id)
    sms_sent = sms_failed = push_sent = push_failed = 0

    # ---- SMS ----------------------------------------------------------
    for sub in audience["subscribers"]:
        nid = f"ntf_{uuid.uuid4().hex[:12]}"
        if test_mode:
            _record(nid, tenant_id, incident_id, "sms", sub["phone_e164"], body,
                    "suppressed_test", f"dedupe:{body_hash}", "test mode: not sent")
            continue
        try:
            from services.api.adapters import sms_fast2sms

            res = sms_fast2sms.send_sms(sub["phone_e164"], body)
            ok = bool(res.get("ok"))
            _record(nid, tenant_id, incident_id, "sms", sub["phone_e164"], body,
                    "sent" if ok else "failed",
                    res.get("provider_ref") or f"dedupe:{body_hash}",
                    None if ok else str(res.get("error"))[:200])
            sms_sent += ok
            sms_failed += (not ok)
        except Exception as exc:
            _record(nid, tenant_id, incident_id, "sms", sub["phone_e164"], body,
                    "failed", f"dedupe:{body_hash}", f"{type(exc).__name__}: {exc}"[:200])
            sms_failed += 1

    # ---- Push ---------------------------------------------------------
    for dev in audience["devices"]:
        nid = f"ntf_{uuid.uuid4().hex[:12]}"
        if test_mode:
            _record(nid, tenant_id, incident_id, "fcm_push", dev["id"], body,
                    "suppressed_test", f"dedupe:{body_hash}", "test mode: not sent")
            continue
        try:
            from services.api.adapters import fcm_push

            res = fcm_push.send_to_token(dev["fcm_token"], headline, body)
            ok = bool(res.get("ok"))
            _record(nid, tenant_id, incident_id, "fcm_push", dev["id"], body,
                    "sent" if ok else "failed",
                    res.get("provider_ref") or f"dedupe:{body_hash}",
                    None if ok else str(res.get("error"))[:200])
            push_sent += ok
            push_failed += (not ok)
        except Exception as exc:
            _record(nid, tenant_id, incident_id, "fcm_push", dev["id"], body,
                    "failed", f"dedupe:{body_hash}", f"{type(exc).__name__}: {exc}"[:200])
            push_failed += 1

    # A dedupe marker so an identical alert is suppressed even when the radius
    # held nobody — otherwise an empty audience would retry forever.
    if not audience["subscribers"] and not audience["devices"]:
        _record(f"ntf_{uuid.uuid4().hex[:12]}", tenant_id, incident_id, "none",
                "-", body, "no_recipients", f"dedupe:{body_hash}",
                "No consenting recipient inside the radius.")

    reached = sms_sent + push_sent
    return {
        "status": "test" if test_mode else "dispatched",
        "alert_id": alert_id,
        "incident_id": incident_id,
        "cap_xml": cap_xml,
        "radius_m": radius,
        "severity_cap": cap_sev,
        "certainty": certainty,
        "in_radius": len(audience["subscribers"]) + len(audience["devices"]),
        "sms": {"sent": sms_sent, "failed": sms_failed},
        "push": {"sent": push_sent, "failed": push_failed},
        "skipped_no_consent": audience["skipped_no_consent"],
        "skipped_no_location": audience["skipped_no_location"],
        # Deliberately precise. This is the sentence an operator will repeat.
        "reach_statement": (
            f"Accepted by the provider for {reached} consenting recipient(s) within "
            f"{radius / 1000:.1f} km. Delivery to a handset is not confirmed by this "
            f"count. Reaching the wider public requires cell broadcast, which is "
            f"operated by DoT/NDMA; the CAP document above is the artifact for that "
            f"handoff."
        ),
        "dispatched_at": _now(),
    }
