"""Evidence: minting, freshness, conflicts, expiry propagation.

Trust tier is COPIED from the connector row, never inferred from the payload or
from a model. Expiry is observed_at + connector.freshness_sla_s. Retraction is
a status change plus an audit event - evidence rows are never deleted.

value_json convention (one place, so conflicts can be found by SQL):
    {"subject": "<ref>:<metric>", "metric": "...", "value": <float|null>,
     "unit": "...", "ref": "<asset/station id>", "payload": {<raw>}}
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from services.api.models import Evidence, EvidenceConflict, EvidenceRef

from . import audit, db

# statutory > certified > verified > crowdsourced > unknown. Index 0 wins.
PRECEDENCE = ["statutory", "certified", "verified", "crowdsourced", "unknown"]
PRECEDENCE_RULE = "rule.source_precedence.v1"

# Per-metric absolute divergence tolerance. Anything not listed falls back to a
# relative tolerance of DEFAULT_REL.
TOLERANCE_ABS = {
    "water_level": 0.10,      # m
    "rainfall": 2.0,          # mm/h
    "traffic_flow": 50.0,     # vehicles/h
    "traffic_speed": 5.0,     # km/h
    "reservoir_level": 0.10,  # m
}
DEFAULT_REL = 0.05

UNITS = {
    "water_level": "m", "reservoir_level": "m", "rainfall": "mm/h",
    "traffic_flow": "veh/h", "traffic_speed": "km/h", "cyber_alert": "severity",
}

# fields a payload may carry the measured number in, in priority order
VALUE_FIELDS = ["level_m", "rate_mm_h", "flow_vph", "speed_kph", "value"]
REF_FIELDS = ["asset_id", "station_id", "sensor_id", "segment_id", "subject"]


def subject_of(payload: dict[str, Any], kind: str) -> str:
    """Stable identity for 'the thing being measured', so two sources reporting
    the same real-world quantity land on the same subject string."""
    if isinstance(payload.get("subject"), str) and ":" in payload["subject"]:
        return payload["subject"]
    ref = next((str(payload[f]) for f in REF_FIELDS if payload.get(f)), "unknown")
    return f"{ref}:{kind}"


def value_of(payload: dict[str, Any]) -> float | None:
    for f in VALUE_FIELDS:
        v = payload.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def tolerance_for(metric: str, a: float, b: float) -> float:
    if metric in TOLERANCE_ABS:
        return TOLERANCE_ABS[metric]
    return DEFAULT_REL * max(abs(a), abs(b), 1.0)


# ----------------------------------------------------------------- minting
def mint(
    event_row: Any,
    connector_row: Any | None = None,
    evidence_class: str = "observation",
    actor_id: str = "svc.ingest",
    workflow_id: str | None = None,
    prov_derived_from: list[str] | None = None,
) -> Any:
    """Mint one evidence row from a persisted event. Returns the evidence row."""
    con = connector_row or db.q1("SELECT * FROM connector WHERE id=?", event_row["connector_id"])
    if con is None:
        raise ValueError(f"unknown connector: {event_row['connector_id']}")

    payload = db.jload(event_row["payload"], {})
    kind = event_row["kind"]
    subject = subject_of(payload, kind)
    value = value_of(payload)
    unit = UNITS.get(kind, payload.get("unit", ""))
    observed_at = event_row["event_time"]
    expires_at = db.iso(
        db.parse_iso(observed_at) + timedelta(seconds=con["freshness_sla_s"])
    )
    shown = f"{value} {unit}".strip() if value is not None else db.jdump(payload)
    statement = f"{con['name']} reports {kind} = {shown} for {subject.split(':')[0]}"
    value_json = {
        "subject": subject, "metric": kind, "value": value, "unit": unit,
        "ref": subject.split(":")[0], "payload": payload,
    }
    ev_id = db.new_id("ev")
    integrity_hash = audit.canonical_json({
        "event_id": event_row["id"], "connector_id": con["id"],
        "evidence_class": evidence_class, "statement": statement,
        "value": value_json, "observed_at": observed_at, "expires_at": expires_at,
        "trust_tier": con["trust_tier"], "geometry": event_row["geometry"],
    })
    integrity_hash = hashlib.sha256(integrity_hash.encode("utf-8")).hexdigest()

    with db.tx() as c:
        c.execute(
            "INSERT INTO evidence(id,tenant_id,connector_id,event_id,evidence_class,statement,"
            "value_json,observed_at,expires_at,trust_tier,integrity_hash,geometry,status,"
            "prov_activity,prov_derived_from) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'valid',?,?)",
            (
                ev_id, event_row["tenant_id"], con["id"], event_row["id"], evidence_class,
                statement, db.jdump(value_json), observed_at, expires_at,
                con["trust_tier"],  # NEVER inferred: copied from the connector row
                integrity_hash, event_row["geometry"], f"ingest:{con['id']}",
                db.jdump(prov_derived_from or []),
            ),
        )
        audit.append(
            event_row["tenant_id"], workflow_id or event_row["id"], actor_id, "service",
            "evidence.minted", ev_id,
            {"event_id": event_row["id"], "connector_id": con["id"], "subject": subject,
             "trust_tier": con["trust_tier"], "evidence_class": evidence_class,
             "expires_at": expires_at, "integrity_hash": integrity_hash},
        )
    return db.q1("SELECT * FROM evidence WHERE id=?", ev_id)


def verify_integrity(row: Any) -> bool:
    payload = db.jload(row["value_json"], {})
    body = audit.canonical_json({
        "event_id": row["event_id"], "connector_id": row["connector_id"],
        "evidence_class": row["evidence_class"], "statement": row["statement"],
        "value": payload, "observed_at": row["observed_at"],
        "expires_at": row["expires_at"], "trust_tier": row["trust_tier"],
        "geometry": row["geometry"],
    })
    return hashlib.sha256(body.encode("utf-8")).hexdigest() == row["integrity_hash"]


# -------------------------------------------------------------------- reads
def _source_name(connector_id: str) -> str:
    return db.scalar("SELECT name FROM connector WHERE id=?", connector_id, default=connector_id)


def as_ref(row: Any, at: str | None = None) -> EvidenceRef:
    """age_s and fresh are computed at READ time, never stored."""
    age = db.age_s(row["observed_at"], at)
    now = db.parse_iso(at) if at else db.parse_iso(db.now_iso())
    fresh = row["status"] == "valid" and db.parse_iso(row["expires_at"]) > now
    return EvidenceRef(
        id=row["id"], source=_source_name(row["connector_id"]), trust_tier=row["trust_tier"],
        observed_at=row["observed_at"], age_s=age, fresh=fresh,
        evidence_class=row["evidence_class"], status=row["status"],
    )


def as_full(row: Any, at: str | None = None) -> Evidence:
    ref = as_ref(row, at)
    return Evidence(
        **ref.model_dump(), connector_id=row["connector_id"], event_id=row["event_id"],
        statement=row["statement"], value=db.jload(row["value_json"], {}),
        expires_at=row["expires_at"], integrity_hash=row["integrity_hash"],
        geometry=db.jload(row["geometry"]),
        prov_activity=row["prov_activity"],
        prov_derived_from=db.jload(row["prov_derived_from"], []),
    )


def conflict_model(row: Any) -> EvidenceConflict:
    a = db.q1("SELECT * FROM evidence WHERE id=?", row["evidence_a"])
    b = db.q1("SELECT * FROM evidence WHERE id=?", row["evidence_b"])
    return EvidenceConflict(
        id=row["id"], subject=row["subject"], evidence_a=as_ref(a), evidence_b=as_ref(b),
        detected_at=row["detected_at"], resolution=row["resolution"],
        resolved_by_rule=row["resolved_by_rule"], winner_evidence_id=row["winner_evidence_id"],
        impact=_impact(row, a, b),
    )


def _impact(row: Any, a: Any, b: Any) -> str:
    if row["resolution"] == "unresolved":
        return (f"Both sources are {a['trust_tier']}: no precedence rule applies. "
                "Needs human adjudication - the values are not averaged.")
    loser = b if row["winner_evidence_id"] == a["id"] else a
    winner = a if row["winner_evidence_id"] == a["id"] else b
    return (f"{winner['trust_tier']} source takes precedence over "
            f"{loser['trust_tier']}; {loser['id']} is superseded, not merged.")


# ---------------------------------------------------------------- conflicts
def detect_conflicts(
    subject: str, actor_id: str = "svc.evidence", workflow_id: str | None = None
) -> list[EvidenceConflict]:
    """Two valid evidence rows about the same subject whose numeric values
    diverge beyond the per-subject tolerance become an evidence_conflict row.

    Resolution is deterministic source precedence. Values are NEVER averaged:
    a losing measurement stays on the record, it just does not win.

    ponytail: O(n^2) over the valid evidence for one subject. Fine at a handful
    of sensors per subject; window it by observed_at if that ever stops holding.
    """
    rows = db.q(
        "SELECT * FROM evidence WHERE status='valid' "
        "AND json_extract(value_json,'$.subject')=? "
        "AND json_extract(value_json,'$.value') IS NOT NULL "
        "ORDER BY observed_at, id",
        subject,
    )
    out: list[EvidenceConflict] = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["tenant_id"] != b["tenant_id"] or a["connector_id"] == b["connector_id"]:
                continue
            va = db.jload(a["value_json"], {})["value"]
            vb = db.jload(b["value_json"], {})["value"]
            metric = db.jload(a["value_json"], {}).get("metric", "")
            if abs(va - vb) <= tolerance_for(metric, va, vb):
                continue
            existing = db.q1(
                "SELECT * FROM evidence_conflict WHERE (evidence_a=? AND evidence_b=?) "
                "OR (evidence_a=? AND evidence_b=?)",
                a["id"], b["id"], b["id"], a["id"],
            )
            if existing is not None:
                out.append(conflict_model(existing))
                continue

            pa, pb = PRECEDENCE.index(a["trust_tier"]), PRECEDENCE.index(b["trust_tier"])
            if pa == pb:
                resolution, winner, rule = "unresolved", None, None
            else:
                resolution = "precedence"
                winner = a["id"] if pa < pb else b["id"]
                rule = PRECEDENCE_RULE

            cid = db.new_id("conflict")
            detected_at = db.now_iso()
            with db.tx() as c:
                c.execute(
                    "INSERT INTO evidence_conflict(id,tenant_id,evidence_a,evidence_b,subject,"
                    "detected_at,resolution,resolved_by_rule,winner_evidence_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (cid, a["tenant_id"], a["id"], b["id"], subject, detected_at,
                     resolution, rule, winner),
                )
                audit.append(
                    a["tenant_id"], workflow_id or cid, actor_id, "service",
                    "evidence.conflict_detected", cid,
                    {"subject": subject, "evidence_a": a["id"], "evidence_b": b["id"],
                     "value_a": va, "value_b": vb,
                     "tier_a": a["trust_tier"], "tier_b": b["trust_tier"],
                     "resolution": resolution, "resolved_by_rule": rule,
                     "winner_evidence_id": winner, "averaged": False},
                )
            out.append(conflict_model(db.q1("SELECT * FROM evidence_conflict WHERE id=?", cid)))
    return out


# -------------------------------------------------------- expiry/retraction
def retract(
    evidence_id: str, reason: str, actor_id: str = "svc.evidence",
    actor_kind: str = "service", workflow_id: str | None = None,
) -> None:
    """Retraction is an EVENT, never a deletion."""
    row = db.q1("SELECT * FROM evidence WHERE id=?", evidence_id)
    if row is None:
        raise ValueError(f"unknown evidence: {evidence_id}")
    with db.tx() as c:
        c.execute("UPDATE evidence SET status='retracted' WHERE id=?", (evidence_id,))
        audit.append(
            row["tenant_id"], workflow_id or evidence_id, actor_id, actor_kind,
            "evidence.retracted", evidence_id,
            {"reason": reason, "previous_status": row["status"]},
        )


def expire_and_propagate(
    actor_id: str = "svc.evidence", workflow_id: str = "wf.evidence.sweep"
) -> list[str]:
    """Mark past-SLA evidence expired, flag every claim that leaned on evidence
    that is no longer valid, and return the plan ids that must be re-validated."""
    now = db.now_iso()
    plan_ids: list[str] = []
    with db.tx() as c:
        expired = c.execute(
            "SELECT * FROM evidence WHERE status='valid' AND expires_at < ?", (now,)
        ).fetchall()
        for e in expired:
            c.execute("UPDATE evidence SET status='expired' WHERE id=?", (e["id"],))
            audit.append(
                e["tenant_id"], workflow_id, actor_id, "service", "evidence.expired", e["id"],
                {"observed_at": e["observed_at"], "expires_at": e["expires_at"]},
            )

        stale = [r["id"] for r in c.execute(
            "SELECT id FROM evidence WHERE status<>'valid'"
        ).fetchall()]
        flagged = c.execute(
            "SELECT DISTINCT c.id AS claim_id, c.tenant_id AS tenant_id, e.id AS ev_id "
            "FROM claim c, json_each(c.evidence_ids) j, evidence e "
            "WHERE e.id = j.value AND c.status='active' AND e.status<>'valid'"
        ).fetchall()
        for f in flagged:
            c.execute("UPDATE claim SET status='flagged' WHERE id=?", (f["claim_id"],))
            audit.append(
                f["tenant_id"], workflow_id, actor_id, "service", "claim.flagged",
                f["claim_id"], {"reason": "supporting evidence no longer valid",
                                "evidence_id": f["ev_id"]},
            )

        claim_ids = sorted({f["claim_id"] for f in flagged})
        seen: set[str] = set()
        for ids, column in ((claim_ids, "claim_ids"), (stale, "evidence_ids")):
            if not ids:
                continue
            marks = ",".join("?" * len(ids))
            for r in c.execute(
                f"SELECT DISTINCT p.id FROM plan p, json_each(p.{column}) j "
                f"WHERE j.value IN ({marks}) AND p.status NOT IN ('rejected','failed')",
                ids,
            ).fetchall():
                if r["id"] not in seen:
                    seen.add(r["id"])
                    plan_ids.append(r["id"])
    return plan_ids
