"""Civic Issue Reporting & Automated Triage Pipeline.

Integrates citizen reports, photo analysis, spatial deduplication,
SLA tracking, department routing, and evidence ledger minting.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from services.api.core import audit, db, evidence, ingest, vision

log = logging.getLogger("auralis.civic_report")

Department = Literal[
    "Roads & Bridges Department",
    "Solid Waste Management",
    "Water Supply & Urban Drainage Dept",
    "Municipal Electrical & Power Wing",
    "Traffic Police & Urban Transit Command",
    "Fire & Disaster Response Force",
    "General Municipal Services",
]

DEPARTMENT_MAP: dict[str, Department] = {
    "pothole": "Roads & Bridges Department",
    "infrastructure_damage": "Roads & Bridges Department",
    "garbage_overflow": "Solid Waste Management",
    "waterlogging": "Water Supply & Urban Drainage Dept",
    "broken_streetlight": "Municipal Electrical & Power Wing",
    "traffic_congestion": "Traffic Police & Urban Transit Command",
    "road_blockage": "Traffic Police & Urban Transit Command",
    "accident": "Traffic Police & Urban Transit Command",
    "fire_hazard": "Fire & Disaster Response Force",
    "fallen_tree": "Solid Waste Management",
    "other": "General Municipal Services",
}

SLA_HOURS_MAP: dict[str, int] = {
    "critical": 4,
    "high": 12,
    "medium": 24,
    "low": 72,
}


def _ensure_tables() -> None:
    """Ensure civic_report table exists (idempotent)."""
    sql = """
    CREATE TABLE IF NOT EXISTS civic_report (
      id                  TEXT PRIMARY KEY,
      tenant_id           TEXT NOT NULL,
      incident_id         TEXT,
      category            TEXT NOT NULL,
      title               TEXT NOT NULL,
      description         TEXT NOT NULL,
      latitude            REAL NOT NULL,
      longitude           REAL NOT NULL,
      address             TEXT,
      severity            TEXT NOT NULL,
      status              TEXT NOT NULL DEFAULT 'submitted',
      image_data          TEXT,
      annotated_image     TEXT,
      vision_detections   TEXT NOT NULL DEFAULT '[]',
      ai_verification     TEXT NOT NULL DEFAULT '{}',
      assigned_department TEXT NOT NULL,
      sla_deadline        TEXT NOT NULL,
      reported_by         TEXT NOT NULL,
      corroboration_count INTEGER NOT NULL DEFAULT 1,
      evidence_id         TEXT,
      created_at          TEXT NOT NULL,
      updated_at          TEXT NOT NULL,
      resolved_at         TEXT,
      resolution_notes    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_civic_report_status ON civic_report(status);
    CREATE INDEX IF NOT EXISTS idx_civic_report_tenant ON civic_report(tenant_id);
    """
    try:
        c = db.conn()
        c.executescript(sql)
    except Exception as exc:
        log.warning("Civic report table check error: %s", exc)


def _haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance between two points in meters."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_nearby_duplicate(
    tenant_id: str,
    category: str,
    latitude: float,
    longitude: float,
    max_dist_m: float = 60.0,
    max_age_hours: int = 48,
) -> dict[str, Any] | None:
    """Find recent unclosed reports of the same category within proximity."""
    since = (datetime.now(UTC) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.q(
        """
        SELECT * FROM civic_report
        WHERE tenant_id=? AND category=? AND status NOT IN ('resolved', 'rejected')
          AND created_at >= ?
        """,
        tenant_id,
        category,
        since,
    )
    for r in rows:
        dist = _haversine_distance_m(latitude, longitude, r["latitude"], r["longitude"])
        if dist <= max_dist_m:
            return dict(r)
    return None


def create_civic_report(
    tenant_id: str,
    category: str,
    title: str,
    description: str,
    latitude: float,
    longitude: float,
    address: str | None = None,
    severity: str | None = None,
    image_input: bytes | str | None = None,
    reported_by: str = "citizen_web",
) -> dict[str, Any]:
    """Create and triage a new civic report.

    Performs visual AI analysis, SLA assignment, duplicate check, and evidence minting.
    """
    _ensure_tables()
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Computer Vision Analysis if image provided
    vision_res: vision.VisionAnalysisResult | None = None
    annotated_img_b64: str | None = None
    vision_dets_json = "[]"
    ai_verif: dict[str, Any] = {}

    if image_input:
        try:
            vision_res = vision.analyze_image(image_input, hint_category=category)
            annotated_img_b64 = vision_res.annotated_image_base64
            vision_dets_json = json.dumps([d.to_dict() for d in vision_res.detections])

            # Override or enhance category if vision is highly confident
            if vision_res.confidence >= 0.70 and vision_res.primary_category != "other":
                if category in ("other", "", None):
                    category = vision_res.primary_category

            if severity is None:
                severity = vision_res.severity

            ai_verif = {
                "ai_verified": True,
                "confidence": vision_res.confidence,
                "detected_category": vision_res.primary_category,
                "severity": vision_res.severity,
                "visual_summary": vision_res.visual_summary,
                "engine": vision_res.engine_mode,
            }
        except Exception as exc:
            log.warning("Vision analysis in civic report failed: %s", exc)
            ai_verif = {"ai_verified": False, "error": str(exc)}

    # Default severity if still not set
    if not severity or severity not in ("low", "medium", "high", "critical"):
        severity = "medium"

    # 2. Check for nearby duplicates / corroboration
    duplicate = _find_nearby_duplicate(tenant_id, category, latitude, longitude)
    if duplicate:
        dup_id = duplicate["id"]
        new_count = duplicate["corroboration_count"] + 1
        with db.tx() as c:
            c.execute(
                """
                UPDATE civic_report
                SET corroboration_count=?, updated_at=?
                WHERE id=?
                """,
                (new_count, now_iso, dup_id),
            )
        log.info("Corroborated existing report %s (count=%d)", dup_id, new_count)
        return {
            "id": dup_id,
            "status": duplicate["status"],
            "corroborated": True,
            "corroboration_count": new_count,
            "category": category,
            "title": duplicate["title"],
            "message": f"Corroborated existing report {dup_id}. Issue priority escalated.",
            "sla_deadline": duplicate["sla_deadline"],
            "assigned_department": duplicate["assigned_department"],
        }

    # 3. Department Routing & SLA
    dept = DEPARTMENT_MAP.get(category, "General Municipal Services")
    sla_hours = SLA_HOURS_MAP.get(severity, 24)
    deadline = (datetime.now(UTC) + timedelta(hours=sla_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    report_id = f"rep_{uuid.uuid4().hex[:12]}"
    if not title:
        title = f"{category.replace('_', ' ').title()} at {address or f'{latitude:.3f}, {longitude:.3f}'}"

    # 4. Mint Evidence into Evidence Ledger
    evidence_id = None
    try:
        ev_item = evidence.mint(
            tenant_id=tenant_id,
            connector_id="conn_open311",
            evidence_class="observation",
            statement=f"Citizen report: {title} ({severity.upper()}) at {latitude:.4f},{longitude:.4f}",
            value={
                "report_id": report_id,
                "category": category,
                "severity": severity,
                "department": dept,
                "ai_verified": ai_verif.get("ai_verified", False),
                "confidence": ai_verif.get("confidence", 0.7),
            },
            trust_tier="verified" if ai_verif.get("confidence", 0) >= 0.8 else "crowdsourced",
            geometry={"type": "Point", "coordinates": [longitude, latitude]},
            observed_at=now_iso,
            expires_at=(datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        evidence_id = ev_item.id
    except Exception as exc:
        log.warning("Evidence minting for civic report failed: %s", exc)

    # 5. Save Report
    with db.tx() as c:
        c.execute(
            """
            INSERT INTO civic_report (
              id, tenant_id, category, title, description,
              latitude, longitude, address, severity, status,
              annotated_image, vision_detections, ai_verification,
              assigned_department, sla_deadline, reported_by,
              corroboration_count, evidence_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                tenant_id,
                category,
                title,
                description,
                latitude,
                longitude,
                address or "Vijayawada Urban Zone",
                severity,
                "submitted",
                annotated_img_b64,
                vision_dets_json,
                json.dumps(ai_verif),
                dept,
                deadline,
                reported_by,
                1,
                evidence_id,
                now_iso,
                now_iso,
            ),
        )

    # 6. Append audit log
    try:
        audit.append(
            tenant_id=tenant_id,
            workflow_id=report_id,
            actor_id=reported_by,
            actor_kind="human",
            kind="civic_report_created",
            subject_id=report_id,
            payload={
                "category": category,
                "severity": severity,
                "department": dept,
                "evidence_id": evidence_id,
            },
        )
    except Exception as exc:
        log.warning("Audit append failed: %s", exc)

    return {
        "id": report_id,
        "status": "submitted",
        "corroborated": False,
        "category": category,
        "title": title,
        "severity": severity,
        "assigned_department": dept,
        "sla_deadline": deadline,
        "evidence_id": evidence_id,
        "ai_verification": ai_verif,
        "annotated_image": annotated_img_b64,
        "created_at": now_iso,
    }


def get_report(report_id: str) -> dict[str, Any] | None:
    """Fetch single report with decoded JSON fields."""
    _ensure_tables()
    row = db.q1("SELECT * FROM civic_report WHERE id=?", report_id)
    if not row:
        return None
    r = dict(row)
    r["vision_detections"] = json.loads(r.get("vision_detections") or "[]")
    r["ai_verification"] = json.loads(r.get("ai_verification") or "{}")
    return r


def list_reports(
    tenant_id: str,
    category: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List reports with optional filters."""
    _ensure_tables()
    sql = "SELECT * FROM civic_report WHERE tenant_id=?"
    args: list[Any] = [tenant_id]

    if category:
        sql += " AND category=?"
        args.append(category)
    if status:
        sql += " AND status=?"
        args.append(status)
    if severity:
        sql += " AND severity=?"
        args.append(severity)

    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)

    results = []
    for row in db.q(sql, *args):
        r = dict(row)
        r["vision_detections"] = json.loads(r.get("vision_detections") or "[]")
        r["ai_verification"] = json.loads(r.get("ai_verification") or "{}")
        results.append(r)
    return results


def update_report_status(
    report_id: str,
    new_status: Literal["submitted", "verified", "in_progress", "resolved", "rejected"],
    notes: str | None = None,
    principal_id: str = "p_operator",
) -> dict[str, Any]:
    """Update report workflow status (operator / field crew action)."""
    _ensure_tables()
    report = get_report(report_id)
    if not report:
        raise ValueError(f"Report {report_id} not found")

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    resolved_at = now_iso if new_status == "resolved" else report.get("resolved_at")

    with db.tx() as c:
        c.execute(
            """
            UPDATE civic_report
            SET status=?, updated_at=?, resolved_at=?, resolution_notes=?
            WHERE id=?
            """,
            (new_status, now_iso, resolved_at, notes, report_id),
        )

    try:
        audit.append(
            tenant_id=report["tenant_id"],
            workflow_id=report_id,
            actor_id=principal_id,
            actor_kind="human",
            kind="civic_report_status_updated",
            subject_id=report_id,
            payload={"old_status": report["status"], "new_status": new_status, "notes": notes},
        )
    except Exception:
        pass

    return get_report(report_id) or {}


def get_report_stats(tenant_id: str) -> dict[str, Any]:
    """Calculate summary metrics for reporting dashboard."""
    _ensure_tables()
    rows = db.q("SELECT * FROM civic_report WHERE tenant_id=?", tenant_id)
    total = len(rows)
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_dept: dict[str, int] = {}
    by_sev: dict[str, int] = {}

    for r in rows:
        st = r["status"]
        cat = r["category"]
        dept = r["assigned_department"]
        sev = r["severity"]

        by_status[st] = by_status.get(st, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1
        by_dept[dept] = by_dept.get(dept, 0) + 1
        by_sev[sev] = by_sev.get(sev, 0) + 1

    return {
        "total_reports": total,
        "by_status": by_status,
        "by_category": by_category,
        "by_department": by_dept,
        "by_severity": by_sev,
        "pending_count": by_status.get("submitted", 0) + by_status.get("in_progress", 0),
        "resolved_count": by_status.get("resolved", 0),
    }
