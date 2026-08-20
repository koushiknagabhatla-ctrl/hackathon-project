"""Thin typed query helpers for the routers. Functions, not a class hierarchy.

Tenant scoping is a REQUIRED argument on every list function. There is no
default tenant - a missing tenant must be a TypeError at the call site, not a
silent cross-tenant read.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from services.api.models import (
    Action,
    AuditEvent,
    Claim,
    ConnectorHealth,
    Evidence,
    EvidenceConflict,
    Incident,
    IncidentDetail,
    OpsMetrics,
    Plan,
    PolicyDecision,
)

from . import audit as audit_mod
from . import claims as claims_mod
from . import db
from . import evidence as evidence_mod
from . import incident as incident_mod


# --------------------------------------------------------------- identity
def get_principal(principal_id: str) -> Any:
    return db.q1("SELECT * FROM principal WHERE id=?", principal_id)


def tenant_of(principal_id: str) -> str:
    row = get_principal(principal_id)
    if row is None:
        raise PermissionError(f"unknown principal: {principal_id}")
    return row["tenant_id"]


def get_tenant(tenant_id: str) -> Any:
    return db.q1("SELECT * FROM tenant WHERE id=?", tenant_id)


# --------------------------------------------------------------- incidents
def list_incidents(tenant_id: str, state: str | None = None, limit: int = 200) -> list[Incident]:
    sql = "SELECT * FROM incident WHERE tenant_id=?"
    args: list[Any] = [tenant_id]
    if state:
        sql += " AND state=?"
        args.append(state)
    sql += " ORDER BY opened_at DESC LIMIT ?"
    args.append(limit)
    return [incident_mod.from_row(r) for r in db.q(sql, *args)]


def get_incident(incident_id: str) -> Incident | None:
    row = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
    return incident_mod.from_row(row) if row else None


def incident_detail(incident_id: str, degraded: bool = False) -> IncidentDetail | None:
    inc = get_incident(incident_id)
    if inc is None:
        return None
    evidence = get_evidence_many(inc.evidence_ids)
    subjects = {e.value.get("subject") for e in evidence if e.value.get("subject")}
    conflicts = [
        c for c in list_conflicts(_tenant_of_incident(incident_id)) if c.subject in subjects
    ]
    assets = [dict(a) for a in db.q(
        "SELECT * FROM asset WHERE id IN (%s)" % ",".join("?" * len(inc.asset_ids)),
        *inc.asset_ids,
    )] if inc.asset_ids else []
    return IncidentDetail(
        incident=inc, evidence=evidence, claims=list_claims_for_incident(incident_id),
        conflicts=conflicts, forecasts=[], assets=assets,
        unknowns=[c.subject for c in conflicts if c.resolution == "unresolved"],
        degraded=degraded,
    )


def _tenant_of_incident(incident_id: str) -> str:
    return db.scalar("SELECT tenant_id FROM incident WHERE id=?", incident_id)


# ---------------------------------------------------------------- evidence
def get_evidence(evidence_id: str) -> Evidence | None:
    row = db.q1("SELECT * FROM evidence WHERE id=?", evidence_id)
    return evidence_mod.as_full(row) if row else None


def get_evidence_many(evidence_ids: list[str]) -> list[Evidence]:
    if not evidence_ids:
        return []
    rows = db.q(
        "SELECT * FROM evidence WHERE id IN (%s)" % ",".join("?" * len(evidence_ids)),
        *evidence_ids,
    )
    by_id = {r["id"]: r for r in rows}
    return [evidence_mod.as_full(by_id[i]) for i in evidence_ids if i in by_id]


def list_evidence(
    tenant_id: str, subject: str | None = None, status: str | None = None, limit: int = 200
) -> list[Evidence]:
    sql = "SELECT * FROM evidence WHERE tenant_id=?"
    args: list[Any] = [tenant_id]
    if subject:
        sql += " AND json_extract(value_json,'$.subject')=?"
        args.append(subject)
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY observed_at DESC LIMIT ?"
    args.append(limit)
    return [evidence_mod.as_full(r) for r in db.q(sql, *args)]


def list_conflicts(tenant_id: str, resolution: str | None = None) -> list[EvidenceConflict]:
    sql = "SELECT * FROM evidence_conflict WHERE tenant_id=?"
    args: list[Any] = [tenant_id]
    if resolution:
        sql += " AND resolution=?"
        args.append(resolution)
    return [evidence_mod.conflict_model(r) for r in db.q(sql + " ORDER BY detected_at DESC", *args)]


# ------------------------------------------------------------------ claims
def list_claims(tenant_id: str, incident_id: str | None = None, status: str | None = None) -> list[Claim]:
    sql = "SELECT * FROM claim WHERE tenant_id=?"
    args: list[Any] = [tenant_id]
    if incident_id:
        sql += " AND incident_id=?"
        args.append(incident_id)
    if status:
        sql += " AND status=?"
        args.append(status)
    return [claims_mod.from_row(r) for r in db.q(sql + " ORDER BY valid_from DESC", *args)]


def list_claims_for_incident(incident_id: str) -> list[Claim]:
    return [claims_mod.from_row(r) for r in db.q(
        "SELECT * FROM claim WHERE incident_id=? ORDER BY valid_from DESC", incident_id)]


# ------------------------------------------------------------------ events
def list_events(
    tenant_id: str, quarantined: bool | None = None, connector_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM event WHERE tenant_id=?"
    args: list[Any] = [tenant_id]
    if quarantined is not None:
        sql += " AND quarantined=?"
        args.append(1 if quarantined else 0)
    if connector_id:
        sql += " AND connector_id=?"
        args.append(connector_id)
    sql += " ORDER BY event_time DESC LIMIT ?"
    args.append(limit)
    return [dict(r, payload=db.jload(r["payload"], {}), geometry=db.jload(r["geometry"]))
            for r in db.q(sql, *args)]


def get_event(event_id: str) -> Any:
    return db.q1("SELECT * FROM event WHERE id=?", event_id)


def raw_payload(content_hash: str) -> Any:
    return db.q1("SELECT * FROM raw_payload WHERE content_hash=?", content_hash)


# ------------------------------------------------------------------ assets
def list_assets(tenant_id: str) -> list[dict[str, Any]]:
    return [dict(r, geometry=db.jload(r["geometry"])) for r in
            db.q("SELECT * FROM asset WHERE tenant_id=? ORDER BY name", tenant_id)]


def get_asset(asset_id: str) -> Any:
    return db.q1("SELECT * FROM asset WHERE id=?", asset_id)


# ------------------------------------------------------------ plans/actions
def action_from_row(row: Any) -> Action:
    pd = None
    if row["policy_decision_id"]:
        p = db.q1("SELECT * FROM policy_decision WHERE id=?", row["policy_decision_id"])
        pd = policy_decision_from_row(p) if p else None
    return Action(
        id=row["id"], plan_id=row["plan_id"], tool_id=row["tool_id"], sequence=row["sequence"],
        args=db.jload(row["args"], {}), target_asset_id=row["target_asset_id"],
        risk_tier=row["risk_tier"], risk_inputs=db.jload(row["risk_inputs"], {}),
        blast_radius=row["blast_radius"], reversible=bool(row["reversible"]),
        rollback_tool_id=row["rollback_tool_id"], status=row["status"],
        idempotency_key=row["idempotency_key"], policy_decision=pd,
        executed_at=row["executed_at"], intended_state=db.jload(row["intended_state"]),
        actual_state=db.jload(row["actual_state"]), verification=row["verification"],
        verification_method=row["verification_method"],
    )


def plan_from_row(row: Any) -> Plan:
    return Plan(
        id=row["id"], incident_id=row["incident_id"], title=row["title"],
        rationale=row["rationale"], created_at=row["created_at"], created_by=row["created_by"],
        status=row["status"], evidence_ids=db.jload(row["evidence_ids"], []),
        claim_ids=db.jload(row["claim_ids"], []), validation=db.jload(row["validation"], {}),
        objective_score=db.jload(row["objective_score"], {}),
        actions=list_actions(row["id"]),
    )


def list_actions(plan_id: str) -> list[Action]:
    return [action_from_row(r) for r in
            db.q("SELECT * FROM action WHERE plan_id=? ORDER BY sequence", plan_id)]


def get_action(action_id: str) -> Action | None:
    row = db.q1("SELECT * FROM action WHERE id=?", action_id)
    return action_from_row(row) if row else None


def list_plans(tenant_id: str, incident_id: str | None = None) -> list[Plan]:
    sql = "SELECT * FROM plan WHERE tenant_id=?"
    args: list[Any] = [tenant_id]
    if incident_id:
        sql += " AND incident_id=?"
        args.append(incident_id)
    return [plan_from_row(r) for r in db.q(sql + " ORDER BY created_at DESC", *args)]


def get_plan(plan_id: str) -> Plan | None:
    row = db.q1("SELECT * FROM plan WHERE id=?", plan_id)
    return plan_from_row(row) if row else None


# ------------------------------------------------------------------ policy
def policy_decision_from_row(row: Any) -> PolicyDecision:
    return PolicyDecision(
        id=row["id"], bundle_version=row["bundle_version"], inputs_hash=row["inputs_hash"],
        inputs=db.jload(row["inputs"], {}), effect=row["effect"], rule_id=row["rule_id"],
        reason=row["reason"], decided_at=row["decided_at"],
        subject_action_id=row["subject_action_id"],
    )


def list_policy_decisions(tenant_id: str, limit: int = 200) -> list[PolicyDecision]:
    return [policy_decision_from_row(r) for r in db.q(
        "SELECT * FROM policy_decision WHERE tenant_id=? ORDER BY decided_at DESC LIMIT ?",
        tenant_id, limit)]


# ------------------------------------------------------------------- audit
def list_audit(workflow_id: str) -> list[AuditEvent]:
    return audit_mod.workflow(workflow_id)


def list_audit_for_tenant(tenant_id: str, limit: int = 200) -> list[AuditEvent]:
    rows = db.q("SELECT * FROM audit_event WHERE tenant_id=? ORDER BY seq DESC LIMIT ?",
                tenant_id, limit)
    return [AuditEvent(**audit_mod._entry(r), prev_hash=r["prev_hash"],
                       entry_hash=r["entry_hash"]) for r in rows]


# ------------------------------------------------------------- data health
def _day_ago() -> str:
    """24h ago in the same ISO8601-Z format the columns are stored in, so plain
    string comparison is a correct time comparison."""
    return db.iso(db.parse_iso(db.now_iso()) - timedelta(days=1))


def connector_health(tenant_id: str) -> list[ConnectorHealth]:
    day_ago = _day_ago()
    out = []
    for c in db.q("SELECT * FROM connector WHERE tenant_id=? ORDER BY name", tenant_id):
        age = db.age_s(c["last_seen_at"]) if c["last_seen_at"] else None
        out.append(ConnectorHealth(
            id=c["id"], name=c["name"], trust_tier=c["trust_tier"],
            contract_version=c["contract_version"], freshness_sla_s=c["freshness_sla_s"],
            last_seen_at=c["last_seen_at"], age_s=age,
            fresh=age is not None and age <= c["freshness_sla_s"],
            quality_score=c["quality_score"], dpia_status=c["dpia_status"],
            events_24h=db.scalar(
                "SELECT COUNT(*) FROM event WHERE connector_id=? AND ingest_time>=?",
                c["id"], day_ago, default=0),
            quarantined_24h=db.scalar(
                "SELECT COUNT(*) FROM event WHERE connector_id=? AND ingest_time>=? "
                "AND quarantined=1", c["id"], day_ago, default=0),
            open_conflicts=db.scalar(
                "SELECT COUNT(*) FROM evidence_conflict k, evidence e WHERE "
                "(k.evidence_a=e.id OR k.evidence_b=e.id) AND e.connector_id=? "
                "AND k.resolution='unresolved'", c["id"], default=0),
        ))
    return out


# ------------------------------------------------------------------- metrics
def ops_metrics(tenant_id: str) -> OpsMetrics:
    day_ago = _day_ago()
    ttd = db.scalar(
        "SELECT AVG(strftime('%s', opened_at) - strftime('%s', first_observation_at)) "
        "FROM incident WHERE tenant_id=? AND first_observation_at IS NOT NULL", tenant_id)
    runs = db.q1(
        "SELECT COUNT(*) n, COALESCE(SUM(tokens_in+tokens_out),0) t, "
        "COALESCE(SUM(cost_usd),0) c, COALESCE(MAX(degraded),0) d "
        "FROM agent_run WHERE tenant_id=?", tenant_id)
    total_claims = db.scalar("SELECT COUNT(*) FROM claim WHERE tenant_id=?", tenant_id, default=0)
    unsupported = db.scalar(
        "SELECT COUNT(*) FROM claim WHERE tenant_id=? AND status='flagged'", tenant_id, default=0)
    incidents = db.scalar("SELECT COUNT(*) FROM incident WHERE tenant_id=?", tenant_id, default=0)
    executed = db.scalar(
        "SELECT COUNT(*) FROM action a JOIN plan p ON p.id=a.plan_id "
        "WHERE p.tenant_id=? AND a.status IN ('executed','verified','difference','failed')",
        tenant_id, default=0)
    ok = db.scalar(
        "SELECT COUNT(*) FROM action a JOIN plan p ON p.id=a.plan_id "
        "WHERE p.tenant_id=? AND a.status IN ('executed','verified')", tenant_id, default=0)
    return OpsMetrics(
        time_to_detect_s=float(ttd) if ttd is not None else None,
        unsupported_claim_rate=(unsupported / total_claims) if total_claims else 0.0,
        tool_success_rate=(ok / executed) if executed else 1.0,
        policy_blocks_24h=db.scalar(
            "SELECT COUNT(*) FROM policy_decision WHERE tenant_id=? AND effect='deny' "
            "AND decided_at>=?", tenant_id, day_ago, default=0),
        tool_errors_24h=db.scalar(
            "SELECT COUNT(*) FROM action a JOIN plan p ON p.id=a.plan_id "
            "WHERE p.tenant_id=? AND a.status='failed'", tenant_id, default=0),
        audit_events=db.scalar(
            "SELECT COUNT(*) FROM audit_event WHERE tenant_id=?", tenant_id, default=0),
        llm_calls=runs["n"], llm_tokens=runs["t"], llm_cost_usd=float(runs["c"]),
        cost_per_incident_usd=(float(runs["c"]) / incidents) if incidents else 0.0,
        degraded=bool(runs["d"]),
        source_health=connector_health(tenant_id),
    )
