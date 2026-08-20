"""Event ingest. The pipeline runs in exactly this order:

  1. authenticate  - principal is active, connector exists and is in its tenant
  2. schema        - validate the body against the connector contract
  3. content hash  - sha256 of the canonical raw body, stored immutably
  4. dedup         - (connector_id, source_event_id, content_hash)
  5. clock skew    - >24h old or >5min ahead  => quarantine
  6. quality       - impossible values from the contract rules => quarantine
  7. persist       - event row (quarantined rows are kept and queryable)
  8. evidence      - mint, then run deterministic detection

Quarantine never deletes: the row is stored with quarantined=1 and a reason and
the call still succeeds. Every outcome writes an audit event.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from typing import Any

from services.api.models import EventAccepted, EventIn

from . import audit, db, evidence, incident

MAX_PAST_S = 24 * 3600
MAX_FUTURE_S = 5 * 60

# The connector contract, keyed by event kind: what the body must contain and
# what values are physically possible. ponytail: a module dict, not a table -
# these change with a code deploy, not at runtime. Move to a `connector_contract`
# table when operators need to edit them without shipping.
CONTRACTS: dict[str, dict[str, Any]] = {
    "water_level": {
        "required": ["level_m"],
        "numeric": {"level_m": (-10.0, 30.0), "flow_m3s": (0.0, 20000.0)},
    },
    "reservoir_level": {
        "required": ["level_m"],
        "numeric": {"level_m": (-10.0, 200.0), "pct_full": (0.0, 100.0)},
    },
    "rainfall": {
        "required": ["rate_mm_h"],
        "numeric": {"rate_mm_h": (0.0, 400.0), "accum_mm": (0.0, 2000.0)},
    },
    "traffic_flow": {
        "required": ["flow_vph"],
        "numeric": {"flow_vph": (0.0, 20000.0), "speed_kph": (0.0, 300.0),
                    "baseline_vph": (0.0, 20000.0)},
    },
    "cyber_alert": {
        "required": ["severity"],
        "enum": {"severity": ["info", "low", "medium", "high", "critical"]},
    },
    "asset_state": {"required": ["asset_id"], "numeric": {}},
}
DEFAULT_CONTRACT: dict[str, Any] = {"required": [], "numeric": {}, "enum": {}}


def contract_for(kind: str) -> dict[str, Any]:
    return CONTRACTS.get(kind, DEFAULT_CONTRACT)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _principal(principal: Any) -> tuple[str, str]:
    pid = principal
    if isinstance(principal, (sqlite3.Row, dict)):
        pid = principal["id"]
    elif not isinstance(principal, str):
        pid = getattr(principal, "id")
    row = db.q1("SELECT * FROM principal WHERE id=?", pid)
    if row is None or row["status"] != "active":
        raise PermissionError(f"unknown or inactive principal: {pid}")
    return row["id"], row["tenant_id"]


def _schema_errors(ev: EventIn, contract: dict[str, Any]) -> list[str]:
    errs = [f"missing required field: {f}"
            for f in contract.get("required", []) if ev.payload.get(f) is None]
    for f in contract.get("numeric", {}):
        if f in ev.payload and not _num(ev.payload[f]):
            errs.append(f"field {f} must be numeric, got {type(ev.payload[f]).__name__}")
    for f, allowed in contract.get("enum", {}).items():
        if f in ev.payload and ev.payload[f] not in allowed:
            errs.append(f"field {f} must be one of {allowed}, got {ev.payload[f]!r}")
    try:
        db.parse_iso(ev.event_time)
    except ValueError:
        errs.append(f"event_time is not ISO8601: {ev.event_time!r}")
    if ev.geometry is not None and not isinstance(ev.geometry, dict):
        errs.append("geometry must be a GeoJSON object (EPSG:4326)")
    return errs


def _quality_errors(ev: EventIn, contract: dict[str, Any]) -> list[str]:
    out = []
    for f, (lo, hi) in contract.get("numeric", {}).items():
        v = ev.payload.get(f)
        if _num(v) and not (lo <= v <= hi):
            out.append(f"impossible value: {f}={v} outside [{lo}, {hi}]")
    return out


def ingest_event(ev: EventIn, principal: Any) -> EventAccepted:
    actor_id, tenant_id = _principal(principal)
    event_id = db.new_id("evt")
    workflow_id = event_id

    def log(kind: str, payload: dict[str, Any], subject: str | None = event_id) -> None:
        audit.append(tenant_id, workflow_id, actor_id, "service", kind, subject, payload)

    # 1. authenticate the connector
    con = db.q1("SELECT * FROM connector WHERE id=?", ev.connector_id)
    if con is None or con["tenant_id"] != tenant_id:
        reason = f"unknown connector for this tenant: {ev.connector_id}"
        log("ingest.rejected", {"reason": reason, "connector_id": ev.connector_id}, None)
        return EventAccepted(id=None, accepted=False, reason=reason)

    # 2. schema-validate against the connector contract
    contract = contract_for(ev.kind)
    errs = _schema_errors(ev, contract)
    if errs:
        reason = "schema validation failed: " + "; ".join(errs)
        log("ingest.rejected", {"reason": reason, "connector_id": con["id"], "kind": ev.kind},
            None)
        return EventAccepted(id=None, accepted=False, reason=reason)

    # 3. content-hash the raw body, store it immutably
    body = audit.canonical_json(ev.model_dump(mode="json"))
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    # 4. dedup
    dup = db.q1(
        "SELECT * FROM event WHERE connector_id=? AND source_event_id IS ? AND content_hash=?",
        con["id"], ev.source_event_id, content_hash,
    )
    if dup is not None:
        log("ingest.deduplicated",
            {"existing_event_id": dup["id"], "content_hash": content_hash}, dup["id"])
        ev_id = db.scalar("SELECT id FROM evidence WHERE event_id=?", dup["id"])
        return EventAccepted(
            id=dup["id"], accepted=True, deduplicated=True, evidence_id=ev_id,
            quarantined=bool(dup["quarantined"]), reason=dup["quarantine_reason"],
        )

    # 5. clock skew, 6. impossible values -> quarantine, never drop
    skew = (datetime.now(UTC) - db.parse_iso(ev.event_time)).total_seconds()
    reasons: list[str] = []
    if skew > MAX_PAST_S:
        reasons.append(f"clock skew: event_time is {int(skew)}s in the past (limit {MAX_PAST_S}s)")
    elif skew < -MAX_FUTURE_S:
        reasons.append(f"clock skew: event_time is {int(-skew)}s in the future (limit {MAX_FUTURE_S}s)")
    reasons += _quality_errors(ev, contract)
    quarantine_reason = "; ".join(reasons) or None

    # 7. persist
    with db.tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO raw_payload(content_hash,connector_id,received_at,body) "
            "VALUES(?,?,?,?)",
            (content_hash, con["id"], db.now_iso(), body),
        )
        c.execute(
            "INSERT INTO event(id,tenant_id,connector_id,source_event_id,content_hash,kind,"
            "event_time,ingest_time,geometry,payload,schema_version,quarantined,"
            "quarantine_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, tenant_id, con["id"], ev.source_event_id, content_hash, ev.kind,
                ev.event_time, db.now_iso(), db.jdump(ev.geometry) if ev.geometry else None,
                db.jdump(ev.payload), ev.schema_version,
                1 if quarantine_reason else 0, quarantine_reason,
            ),
        )
        c.execute("UPDATE connector SET last_seen_at=? WHERE id=?", (db.now_iso(), con["id"]))
        log("ingest.quarantined" if quarantine_reason else "ingest.accepted",
            {"connector_id": con["id"], "kind": ev.kind, "content_hash": content_hash,
             "event_time": ev.event_time, "reason": quarantine_reason})

    if quarantine_reason:
        # stored, queryable, excluded from evidence until a human clears it
        return EventAccepted(id=event_id, accepted=True, quarantined=True,
                             reason=quarantine_reason)

    # 8. mint evidence, then run deterministic detection
    row = db.q1("SELECT * FROM event WHERE id=?", event_id)
    ev_row = evidence.mint(row, con, actor_id=actor_id, workflow_id=workflow_id)
    incident_id = incident.detect(row, ev_row, actor_id=actor_id)
    return EventAccepted(
        id=event_id, accepted=True, evidence_id=ev_row["id"], incident_id=incident_id
    )


def release_from_quarantine(
    event_id: str, actor_id: str, reason: str
) -> EventAccepted:
    """Human override: keep the row, clear the flag, mint the evidence that was
    withheld. The original quarantine reason stays in the audit ledger."""
    row = db.q1("SELECT * FROM event WHERE id=?", event_id)
    if row is None:
        raise ValueError(f"unknown event: {event_id}")
    with db.tx() as c:
        c.execute("UPDATE event SET quarantined=0 WHERE id=?", (event_id,))
        audit.append(row["tenant_id"], event_id, actor_id, "human",
                     "ingest.quarantine_released", event_id,
                     {"reason": reason, "original_quarantine_reason": row["quarantine_reason"]})
    row = db.q1("SELECT * FROM event WHERE id=?", event_id)
    ev_row = evidence.mint(row, actor_id=actor_id, workflow_id=event_id)
    return EventAccepted(id=event_id, accepted=True, evidence_id=ev_row["id"])
