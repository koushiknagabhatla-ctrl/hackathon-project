"""Incidents: the deterministic detector and the state machine.

Detection here is rules only - no ML, no LLM. Every detection records the rule
id in `detector` and writes an audit event naming it, so an operator can always
answer "why did this open?" without a model in the loop.
"""

from __future__ import annotations

from typing import Any

from services.api.models import Incident

from . import audit, db, geo

# ------------------------------------------------------------- state machine
TRANSITIONS: dict[str, set[str]] = {
    "detected": {"assessing", "closed"},
    "assessing": {"planning", "closed"},
    "planning": {"awaiting_approval", "closed"},
    "awaiting_approval": {"acting", "planning", "closed"},
    "acting": {"verifying", "closed"},
    "verifying": {"closed", "acting"},
    "closed": set(),
}

# ------------------------------------------------------------- detector knobs
ASSET_MATCH_M = 250.0        # how close an event must be to be "about" an asset
CORRELATION_M = 500.0        # same-incident spatial window
CORRELATION_S = 30 * 60      # same-incident temporal window
DEFAULT_WATER_THRESHOLD_M = 3.0
RAINFALL_MAJOR_MM_H = 30.0
RAINFALL_CRITICAL_MM_H = 50.0
TRAFFIC_COLLAPSE_FRACTION = 0.3
SEVERITY_ORDER = ["info", "minor", "major", "critical"]


class IllegalTransition(ValueError):
    """Attempted a state change the machine does not allow."""


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _threshold(asset: Any, key: str, default: float) -> float:
    if asset is None:
        return default
    for col in ("current_state", "desired_state", "reported_state"):
        v = db.jload(asset[col], {}).get(key)
        if _num(v):
            return float(v)
    return default


# ------------------------------------------------------------------- rules
def _water_level(payload: dict[str, Any], asset: Any) -> tuple[str, str, dict] | None:
    v = payload.get("level_m")
    if not _num(v):
        return None
    threshold = _threshold(asset, "threshold_m", DEFAULT_WATER_THRESHOLD_M)
    if v < threshold:
        return None
    severity = "critical" if v >= threshold * 1.25 else "major"
    return severity, f"Water level {v} m over threshold {threshold} m", {
        "level_m": v, "threshold_m": threshold}


def _rainfall(payload: dict[str, Any], asset: Any) -> tuple[str, str, dict] | None:
    v = payload.get("rate_mm_h")
    if not _num(v) or v < RAINFALL_MAJOR_MM_H:
        return None
    severity = "critical" if v >= RAINFALL_CRITICAL_MM_H else "major"
    return severity, f"Rainfall rate {v} mm/h", {
        "rate_mm_h": v, "threshold_mm_h": RAINFALL_MAJOR_MM_H}


def _traffic_collapse(payload: dict[str, Any], asset: Any) -> tuple[str, str, dict] | None:
    flow, base = payload.get("flow_vph"), payload.get("baseline_vph")
    if not (_num(flow) and _num(base) and base > 0):
        return None
    if flow > TRAFFIC_COLLAPSE_FRACTION * base:
        return None
    return "major", f"Traffic flow collapsed to {flow} veh/h from a {base} veh/h baseline", {
        "flow_vph": flow, "baseline_vph": base, "fraction": TRAFFIC_COLLAPSE_FRACTION}


def _cyber(payload: dict[str, Any], asset: Any) -> tuple[str, str, dict] | None:
    sev = str(payload.get("severity", "")).lower()
    if sev not in ("high", "critical"):
        return None
    return ("critical" if sev == "critical" else "major",
            f"Cyber alert severity {sev}", {"severity": sev})


# rule_id -> (incident_class, predicate). Order is evaluation order.
RULES: list[tuple[str, str, Any]] = [
    ("det.water_level.over_asset_threshold.v1", "flood", _water_level),
    ("det.rainfall.rate.v1", "flood", _rainfall),
    ("det.traffic.flow_collapse.v1", "traffic", _traffic_collapse),
    ("det.cyber.alert_severity.v1", "cyber", _cyber),
]


def _asset_for(event_row: Any) -> tuple[Any, float | None]:
    """Nearest asset, by explicit payload reference or by geodesic distance."""
    payload = db.jload(event_row["payload"], {})
    if payload.get("asset_id"):
        named = db.q1("SELECT * FROM asset WHERE id=?", payload["asset_id"])
        if named is not None:
            return named, 0.0
    if not event_row["geometry"]:
        return None, None
    # ponytail: linear scan over the tenant's assets. Fine for a city-scale twin;
    # add an R-tree (shapely.STRtree) once this is thousands of assets per event.
    best, best_d = None, None
    for a in db.q("SELECT * FROM asset WHERE tenant_id=?", event_row["tenant_id"]):
        d = geo.distance_m(a["geometry"], event_row["geometry"])
        if best_d is None or d < best_d:
            best, best_d = a, d
    if best is not None and best_d <= ASSET_MATCH_M + geo.uncertainty_m(best["geometry_accuracy_m"]):
        return best, best_d
    return None, best_d


def _correlate(tenant_id: str, incident_class: str, geometry: str | None, at: str) -> Any:
    """An open incident of the same class within 500 m and 30 min, or None."""
    if not geometry:
        return None
    when = db.parse_iso(at)
    for inc in db.q(
        "SELECT * FROM incident WHERE tenant_id=? AND incident_class=? AND state<>'closed' "
        "ORDER BY opened_at DESC",
        tenant_id, incident_class,
    ):
        if not inc["geometry"]:
            continue
        ref = inc["first_observation_at"] or inc["opened_at"]
        if abs((when - db.parse_iso(ref)).total_seconds()) > CORRELATION_S:
            continue
        if geo.distance_m(inc["geometry"], geometry) <= CORRELATION_M:
            return inc
    return None


def detect(event_row: Any, evidence_row: Any = None, actor_id: str = "svc.detector") -> str | None:
    """Run the deterministic rules over one event. Returns the incident id it
    opened or correlated into, or None when no rule fires."""
    payload = db.jload(event_row["payload"], {})
    asset, distance = _asset_for(event_row)

    hit = None
    for rule_id, incident_class, rule in RULES:
        hit = rule(payload, asset)
        if hit:
            break
    if not hit:
        return None
    severity, headline, detail = hit

    geometry = event_row["geometry"] or (asset["geometry"] if asset is not None else None)
    tenant_id = event_row["tenant_id"]
    ev_ids = [evidence_row["id"]] if evidence_row is not None else []
    asset_ids = [asset["id"]] if asset is not None else []
    observed_at = event_row["event_time"]
    detection = {
        "detector": rule_id, "rule": rule_id, "incident_class": incident_class,
        "severity": severity, "headline": headline, "inputs": detail,
        "event_id": event_row["id"], "evidence_ids": ev_ids, "asset_ids": asset_ids,
        "distance_to_asset_m": round(distance, 1) if distance is not None else None,
        "accuracy_note": geo.accuracy_note(asset["geometry_accuracy_m"]) if asset is not None else None,
        "first_observation_at": observed_at,
    }

    existing = _correlate(tenant_id, incident_class, geometry, observed_at)
    if existing is not None:
        merged_ev = list(dict.fromkeys(db.jload(existing["evidence_ids"], []) + ev_ids))
        merged_as = list(dict.fromkeys(db.jload(existing["asset_ids"], []) + asset_ids))
        severity = max(
            [existing["severity"], severity], key=lambda s: SEVERITY_ORDER.index(s)
        )
        first_obs = min(existing["first_observation_at"] or observed_at, observed_at)
        with db.tx() as c:
            c.execute(
                "UPDATE incident SET evidence_ids=?, asset_ids=?, severity=?, "
                "first_observation_at=? WHERE id=?",
                (db.jdump(merged_ev), db.jdump(merged_as), severity, first_obs, existing["id"]),
            )
            audit.append(tenant_id, existing["id"], actor_id, "service",
                         "incident.correlated", existing["id"],
                         dict(detection, correlated_into=existing["id"],
                              window_m=CORRELATION_M, window_s=CORRELATION_S))
        return existing["id"]

    inc_id = db.new_id("inc")
    opened_at = db.now_iso()
    title = f"{headline} at {asset['name'] if asset is not None else 'unmapped location'}"
    with db.tx() as c:
        c.execute(
            "INSERT INTO incident(id,tenant_id,title,incident_class,severity,state,opened_at,"
            "geometry,detector,evidence_ids,asset_ids,first_observation_at) "
            "VALUES(?,?,?,?,?,'detected',?,?,?,?,?,?)",
            (inc_id, tenant_id, title, incident_class, severity, opened_at, geometry,
             rule_id, db.jdump(ev_ids), db.jdump(asset_ids), observed_at),
        )
        audit.append(tenant_id, inc_id, actor_id, "service", "incident.detected", inc_id,
                     dict(detection, incident_id=inc_id, opened_at=opened_at,
                          time_to_detect_s=db.age_s(observed_at, opened_at)))
    return inc_id


# ---------------------------------------------------------------- lifecycle
def transition(
    incident_id: str, to_state: str, actor_id: str, actor_kind: str = "human",
    reason: str | None = None,
) -> Incident:
    row = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
    if row is None:
        raise ValueError(f"unknown incident: {incident_id}")
    current = row["state"]
    if to_state not in TRANSITIONS:
        raise IllegalTransition(f"{to_state!r} is not an incident state")
    if to_state not in TRANSITIONS[current]:
        allowed = ", ".join(sorted(TRANSITIONS[current])) or "nothing (terminal state)"
        raise IllegalTransition(
            f"illegal incident transition {current} -> {to_state}; allowed: {allowed}"
        )
    closed_at = db.now_iso() if to_state == "closed" else row["closed_at"]
    with db.tx() as c:
        c.execute("UPDATE incident SET state=?, closed_at=? WHERE id=?",
                  (to_state, closed_at, incident_id))
        audit.append(row["tenant_id"], incident_id, actor_id, actor_kind,
                     "incident.state_changed", incident_id,
                     {"from": current, "to": to_state, "reason": reason})
    return from_row(db.q1("SELECT * FROM incident WHERE id=?", incident_id))


def from_row(row: Any) -> Incident:
    return Incident(
        id=row["id"], title=row["title"], incident_class=row["incident_class"],
        severity=row["severity"], state=row["state"], opened_at=row["opened_at"],
        closed_at=row["closed_at"], geometry=db.jload(row["geometry"]),
        detector=row["detector"], evidence_ids=db.jload(row["evidence_ids"], []),
        asset_ids=db.jload(row["asset_ids"], []),
        first_observation_at=row["first_observation_at"],
    )


def attach_evidence(incident_id: str, evidence_ids: list[str], actor_id: str = "svc.detector") -> None:
    row = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
    if row is None:
        raise ValueError(f"unknown incident: {incident_id}")
    merged = list(dict.fromkeys(db.jload(row["evidence_ids"], []) + list(evidence_ids)))
    with db.tx() as c:
        c.execute("UPDATE incident SET evidence_ids=? WHERE id=?", (db.jdump(merged), incident_id))
        audit.append(row["tenant_id"], incident_id, actor_id, "service",
                     "incident.evidence_attached", incident_id, {"evidence_ids": evidence_ids})
