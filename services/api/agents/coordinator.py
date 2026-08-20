"""Coordinator: assigns tasks, reconciles outputs, produces exactly TWO plans.

ARBITRATION RULE - the important part of this file:

    When specialists disagree, this module DOES NOT AVERAGE. There is no mean,
    no midpoint, no weighted blend and no "consensus value" anywhere below. A
    blended number is one no source ever reported and no one can defend at an
    inquiry. Instead every disagreement is enumerated with each position's own
    evidence attached, and then EITHER deterministic source precedence applies
    (statutory > certified > verified > crowdsourced > unknown, the same order
    core/evidence.py uses) OR - when the top tier is tied - it escalates to
    human review. Every disagreement is written to the hash-chained ledger as a
    first-class `agent.disagreement` event whichever way it goes.

The coordinator makes NO DIRECT EXTERNAL WRITES. It never imports
`core/gateway.py`, never calls a tool, and never causes an effect outside the
database. It writes draft plans and actions for humans to approve; execution is
`core/gateway.py`'s job and nothing here can shortcut it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.api.core import audit, db, policy, risk

from . import base, evidence_agent, forecast_agent, llm_gateway, planning, situation
from .base import RunContext, Snapshot

COORDINATOR_ID = "coordinator"
COORDINATOR_VERSION = "1.0.0"

# same order as core/evidence.py::PRECEDENCE. Index 0 wins.
PRECEDENCE = ["statutory", "certified", "verified", "crowdsourced", "unknown"]
PRECEDENCE_RULE = "rule.source_precedence.v1"
TIE_RULE = "rule.arbitration.tie_requires_human.v1"


# ---------------------------------------------------------- disagreements
@dataclass(frozen=True)
class Disagreement:
    subject: str
    positions: tuple[dict[str, Any], ...]
    resolution: str            # "source_precedence" | "escalate_human"
    rule: str
    winner_evidence_id: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "positions": [dict(p) for p in self.positions],
            "resolution": self.resolution,
            "rule": self.rule,
            "winner_evidence_id": self.winner_evidence_id,
            "note": self.note,
            "averaged": False,   # asserted in the ledger, verifiable forever
        }


def _tier_index(tier: str) -> int:
    return PRECEDENCE.index(tier) if tier in PRECEDENCE else len(PRECEDENCE)


def reconcile(results: list[base.AgentResult]) -> list[Disagreement]:
    """Enumerate every subject the specialists do not agree on.

    Positions are derived from the frozen snapshot by `base.positions`, one per
    SOURCE, so a disagreement is a fact about the evidence rather than a
    difference of opinion between models.
    """
    by_subject: dict[str, dict[str, dict[str, Any]]] = {}
    for res in results:
        for p in res.output.get("positions") or []:
            # de-duplicate on evidence id: three agents reading the same source
            # is one position, not three votes.
            by_subject.setdefault(str(p["subject"]), {})[str(p["evidence_id"])] = dict(
                p, agents=sorted({p.get("agent_id", ""), *(
                    by_subject.get(str(p["subject"]), {})
                    .get(str(p["evidence_id"]), {}).get("agents", [])
                )} - {""})
            )

    out: list[Disagreement] = []
    for subject, positions in sorted(by_subject.items()):
        items = sorted(positions.values(), key=lambda p: str(p["evidence_id"]))
        if len({round(float(p["value"]), 6) for p in items}) < 2:
            continue
        ranked = sorted(items, key=lambda p: _tier_index(str(p["trust_tier"])))
        top = _tier_index(str(ranked[0]["trust_tier"]))
        contenders = [p for p in ranked if _tier_index(str(p["trust_tier"])) == top]
        spread = max(float(p["value"]) for p in items) - min(
            float(p["value"]) for p in items)
        unit = items[0].get("unit", "")

        if len({round(float(p["value"]), 6) for p in contenders}) == 1:
            win = contenders[0]
            out.append(Disagreement(
                subject=subject, positions=tuple(items),
                resolution="source_precedence", rule=PRECEDENCE_RULE,
                winner_evidence_id=str(win["evidence_id"]),
                note=(
                    f"{len(items)} sources disagree about {subject} by "
                    f"{spread:g} {unit}. Deterministic source precedence applies: "
                    f"{win['source']} ({win['trust_tier']}) reports "
                    f"{float(win['value']):g} {unit} and wins on trust tier. The "
                    f"losing readings stay on the record and were not averaged in."
                ),
            ))
            continue

        out.append(Disagreement(
            subject=subject, positions=tuple(items),
            resolution="escalate_human", rule=TIE_RULE, winner_evidence_id=None,
            note=(
                f"{len(items)} sources disagree about {subject} by {spread:g} "
                f"{unit}, and the highest trust tier present "
                f"({contenders[0]['trust_tier']}) is held by "
                f"{len(contenders)} of them reporting different values. "
                f"Precedence cannot separate them, so this escalates to human "
                f"review. It was NOT averaged: "
                f"{sum(float(p['value']) for p in contenders) / len(contenders):g} "
                f"{unit} is a number no source reported."
            ),
        ))
    return out


# ----------------------------------------------------------------- assess
def _context(incident_id: str, principal: dict[str, Any],
             snapshot_id: str | None = None) -> RunContext:
    inc = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
    if inc is None:
        raise ValueError(f"unknown incident: {incident_id}")
    tenant_id = principal.get("tenant_id") or inc["tenant_id"]
    tenant = db.q1("SELECT * FROM tenant WHERE id=?", tenant_id)
    snapshot = (Snapshot.load(snapshot_id) if snapshot_id
                else Snapshot.take(incident_id))
    return RunContext(
        workflow_id=incident_id, tenant_id=tenant_id, incident_id=incident_id,
        snapshot=snapshot, principal_id=principal.get("id", "unknown"),
        jurisdiction=(tenant["jurisdiction"] if tenant else "unknown"),
        tool_catalogue=tool_catalogue(),
    )


def tool_catalogue() -> tuple[dict[str, Any], ...]:
    """Registered tools, as the planning agent is allowed to see them.

    Read straight from `tool_manifest`, which registration already guarantees
    has a sandbox twin (invariant 4). A tool absent from this table does not
    exist as far as planning is concerned.
    """
    rows = db.q("SELECT * FROM tool_manifest ORDER BY id")
    return tuple({
        "id": r["id"], "version": r["version"], "description": r["description"],
        "input_schema": db.jload(r["input_schema"], {}),
        "risk_class": r["risk_class"],
        "rollback_tool_id": r["rollback_tool_id"],
        "verification_method": r["verification_method"],
        "reversible": bool(r["rollback_tool_id"]),
    } for r in rows)


def assess(incident_id: str, principal: dict[str, Any],
           snapshot_id: str | None = None) -> dict[str, Any]:
    """Run the specialists, reconcile them, return the assessment.

    Deterministic path included: with no API key every agent still runs, still
    grounds every claim, and `degraded` says so.
    """
    ctx = _context(incident_id, principal, snapshot_id)
    results = [
        situation.SituationAgent().run(ctx),
        evidence_agent.EvidenceAgent().run(ctx),
        forecast_agent.ForecastAgent().run(ctx),
    ]
    disagreements = reconcile(results)
    for d in disagreements:
        audit.append(
            ctx.tenant_id, ctx.workflow_id, COORDINATOR_ID, "agent",
            base.KIND_DISAGREEMENT, ctx.incident_id,
            dict(d.to_dict(), snapshot_id=ctx.snapshot.id,
                 arbiter_version=COORDINATOR_VERSION),
        )

    by_id = {r.agent_id: r for r in results}
    ev_out = by_id["evidence-agent"].output
    findings = list(ev_out.get("findings") or [])
    escalations = [d.subject for d in disagreements if d.resolution == "escalate_human"]
    escalations += [f["subject"] for f in findings if f.get("severity") == "blocking"]

    claim_ids = [c for r in results for c in r.claim_ids]
    dropped = [d for r in results for d in r.dropped_claims]
    return {
        "incident_id": incident_id,
        "workflow_id": ctx.workflow_id,
        "snapshot_id": ctx.snapshot.id,
        "snapshot_hash": ctx.snapshot.hash,
        "taken_at": ctx.snapshot.taken_at,
        "degraded": any(r.degraded for r in results),
        "runs": [r.to_dict() for r in results],
        "claim_ids": claim_ids,
        "dropped_claims": dropped,
        "unsupported_claim_rate": base.unsupported_claim_rate(ctx.workflow_id),
        "summary": by_id["situation-agent"].output.get("summary", ""),
        "unknowns": by_id["situation-agent"].output.get("unknowns", []),
        "findings": findings,
        "blocking": bool(ev_out.get("blocking")),
        "forecast": by_id["forecast-agent"].output,
        "disagreements": [d.to_dict() for d in disagreements],
        "escalations": sorted(set(escalations)),
        "llm": llm_gateway.cost_report(ctx.workflow_id),
    }


# ------------------------------------------------------------------ plans
def _tradeoffs(plan: dict[str, Any]) -> dict[str, Any]:
    actions = plan["actions"]
    tiers = [a["risk_tier"] for a in actions] or ["R0"]
    return {
        "action_count": len(actions),
        "max_risk_tier": max(tiers, key=lambda t: risk.TIER_ORDER.index(t)),
        "irreversible_actions": sum(1 for a in actions if not a["reversible"]),
        "needs_approval": sum(
            1 for a in actions
            if (a.get("policy_effect") or "allow") != "allow"
        ),
        "blast_radius": sum(int(a.get("blast_radius") or 0) for a in actions),
        "actions_missing_inputs": sum(1 for a in actions if a.get("missing_args")),
    }


def build_candidate_plans(
    incident_id: str, principal: dict[str, Any], snapshot_id: str | None = None,
    assessment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Exactly two persisted draft plans with visible trade-offs."""
    ctx = _context(incident_id, principal, snapshot_id)
    assessment = assessment or assess(incident_id, principal, ctx.snapshot.id)

    agent = planning.PlanningAgent(
        situation={"summary": assessment.get("summary"),
                   "unknowns": assessment.get("unknowns"),
                   "findings": assessment.get("findings")},
        forecast=assessment.get("forecast") or {},
    )
    result = agent.run(ctx)
    candidates = list(result.output.get("candidates") or [])

    # EXACTLY two. Never one, never three - a single option is not a choice and
    # a long list is not a decision. "Monitor and re-assess" is always a valid
    # second posture because doing nothing yet is always available.
    while len(candidates) < 2:
        candidates.append({
            "title": "Monitor and re-assess",
            "posture": "monitor",
            "rationale": (
                "Take no action yet. Hold the current posture, keep the evidence "
                "under watch and re-assess when it changes. Costs exposure time; "
                "buys certainty and creates no irreversible effect."
            ),
            "evidence_ids": list(ctx.snapshot.evidence_ids),
            "actions": [],
        })
    candidates = candidates[:2]

    blocking = [f for f in (assessment.get("findings") or [])
                if f.get("severity") == "blocking"]
    escalations = list(assessment.get("escalations") or [])

    plans = [
        _persist_plan(ctx, principal, cand, result, assessment, blocking, escalations)
        for cand in candidates
    ]
    a, b = plans[0], plans[1]
    for this, other in ((a, b), (b, a)):
        this["trade_offs"] = _compare(this, other)
    return plans


def _compare(this: dict[str, Any], other: dict[str, Any]) -> list[str]:
    ti, oi = this["objective_score"], other["objective_score"]
    lines = [
        f"{ti['action_count']} action(s) vs {oi['action_count']} in "
        f"'{other['title']}'.",
        f"Highest risk tier {ti['max_risk_tier']} vs {oi['max_risk_tier']}.",
        f"{ti['irreversible_actions']} irreversible action(s) vs "
        f"{oi['irreversible_actions']}.",
        f"{ti['needs_approval']} action(s) need human approval vs "
        f"{oi['needs_approval']}.",
    ]
    if ti["actions_missing_inputs"]:
        lines.append(
            f"{ti['actions_missing_inputs']} action(s) still need an argument "
            f"no evidence supplies - they will not execute until it is provided."
        )
    return lines


def _persist_plan(
    ctx: RunContext, principal: dict[str, Any], cand: dict[str, Any],
    result: base.AgentResult, assessment: dict[str, Any],
    blocking: list[dict[str, Any]], escalations: list[str],
) -> dict[str, Any]:
    """Write one draft plan and its actions.

    Database writes only. No external effect: every action lands as `proposed`,
    carrying its own policy decision as DATA for the plan view. Execution is
    core/gateway.py's job and is not reachable from here.
    """
    plan_id = db.new_id("pl")
    created_at = db.now_iso()
    asset_ids = list(ctx.snapshot.incident.get("asset_ids") or [])
    evidence_ids = [e for e in (cand.get("evidence_ids") or [])
                    if e in ctx.snapshot.evidence_ids]
    max_age = max((int(e.get("age_s") or 0) for e in ctx.snapshot.evidence), default=0)

    actions: list[dict[str, Any]] = []
    action_rows: list[tuple[Any, ...]] = []
    for seq, raw in enumerate(cand.get("actions") or [], 1):
        asset = db.q1("SELECT * FROM asset WHERE id=?",
                      raw.get("target_asset_id") or (asset_ids[0] if asset_ids else ""))
        blast = db.scalar(
            "SELECT COUNT(*) FROM asset_dependency WHERE depends_on_id=?",
            asset["id"] if asset else "", default=0,
        )
        public_facing = "alert" in raw["tool_id"] or "public" in raw["tool_id"]
        tier, inputs = risk.compute_tier(
            action_class=_action_class(raw["tool_id"]),
            asset_criticality=int(asset["criticality"]) if asset else 0,
            blast_radius=int(blast or 0), evidence_age_s=max_age,
            public_facing=public_facing, reversible=bool(raw.get("reversible")),
        )
        action_id = db.new_id("ac")
        decision = policy.decide({
            "tool_id": raw["tool_id"], "action_class": _action_class(raw["tool_id"]),
            "risk_tier": tier, "tenant_id": ctx.tenant_id,
            "principal_id": principal.get("id"), "principal_role": principal.get("role"),
            "principal_kind": "agent", "principal_status": principal.get("status"),
            "principal_tenant": principal.get("tenant_id"),
            "principal_trust_domain": principal.get("trust_domain"),
            "principal_authority": principal.get("authority"),
            "asset_id": asset["id"] if asset else None,
            "asset_tenant": asset["tenant_id"] if asset else None,
            "asset_criticality": int(asset["criticality"]) if asset else 0,
            "blast_radius": int(blast or 0), "evidence_age_s": max_age,
            "evidence_status": "valid", "public_facing": public_facing,
            "reversible": bool(raw.get("reversible")), "approvals": [],
            "now": created_at, "action_id": action_id,
        }, subject_action_id=action_id)

        action_rows.append((
            action_id, plan_id, raw["tool_id"], seq, db.jdump(raw.get("args") or {}),
            asset["id"] if asset else None, tier, db.jdump(inputs), int(blast or 0),
            int(bool(raw.get("reversible"))), raw.get("rollback_tool_id"),
            "blocked" if decision.effect == "deny" else "proposed",
            decision.id, db.jdump({"intent": raw.get("intent", "")}),
            raw.get("verification_method", "read_back"),
        ))
        actions.append({
            "id": action_id, "plan_id": plan_id, "tool_id": raw["tool_id"],
            "sequence": seq, "args": raw.get("args") or {},
            "target_asset_id": asset["id"] if asset else None,
            "risk_tier": tier, "risk_inputs": inputs, "blast_radius": int(blast or 0),
            "reversible": bool(raw.get("reversible")),
            "rollback_tool_id": raw.get("rollback_tool_id"),
            "status": "blocked" if decision.effect == "deny" else "proposed",
            "policy_decision": decision.model_dump(),
            "policy_effect": decision.effect,
            "intent": raw.get("intent", ""),
            "missing_args": raw.get("missing_args") or [],
            "verification_method": raw.get("verification_method", "read_back"),
        })

    plan = {
        "id": plan_id, "incident_id": ctx.incident_id,
        "title": str(cand.get("title", "Candidate plan")),
        "rationale": str(cand.get("rationale", "")),
        "created_at": created_at, "created_by": planning.SPEC.id,
        "status": "blocked" if blocking else "draft",
        "evidence_ids": evidence_ids, "claim_ids": list(result.claim_ids),
        "posture": str(cand.get("posture", "")),
        "actions": actions,
    }
    plan["objective_score"] = _tradeoffs(plan)
    plan["validation"] = {
        "degraded": bool(assessment.get("degraded")),
        "blocking_findings": [f["subject"] for f in blocking],
        "escalations": escalations,
        "dropped_actions": list(result.output.get("dropped_actions") or []),
        "unsupported_claim_rate": assessment.get("unsupported_claim_rate", 0.0),
        "note": (
            "Blocked pending human adjudication of the evidence findings above."
            if blocking else "Draft. Every action carries its own policy decision."
        ),
    }
    # The plan row goes in FIRST: action.plan_id is a foreign key, and the whole
    # thing is one transaction so a half-written plan cannot be observed.
    with db.tx() as c:
        c.execute(
            "INSERT INTO plan(id,tenant_id,incident_id,title,rationale,created_at,"
            "created_by,status,evidence_ids,claim_ids,validation,objective_score) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, ctx.tenant_id, ctx.incident_id, plan["title"],
             plan["rationale"], created_at, plan["created_by"], plan["status"],
             db.jdump(evidence_ids), db.jdump(list(result.claim_ids)),
             db.jdump(plan["validation"]), db.jdump(plan["objective_score"])),
        )
        for row in action_rows:
            c.execute(
                "INSERT INTO action(id,plan_id,tool_id,sequence,args,"
                "target_asset_id,risk_tier,risk_inputs,blast_radius,reversible,"
                "rollback_tool_id,status,policy_decision_id,intended_state,"
                "verification_method) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
    audit.append(
        ctx.tenant_id, ctx.workflow_id, COORDINATOR_ID, "agent",
        "plan.drafted", plan_id,
        {"title": plan["title"], "posture": plan["posture"],
         "status": plan["status"], "actions": [a["id"] for a in actions],
         "objective_score": plan["objective_score"],
         "snapshot_id": ctx.snapshot.id},
    )
    return plan


def _action_class(tool_id: str) -> str:
    """Map a tool id onto one of core/risk.py::ACTION_CLASS_BASE.

    A manifest may name its class outright (`tool_manifest.risk_class`); this is
    the fallback for ids that do not. An id matching nothing falls through to
    `actuate`, the conservative choice - unknown means treat it as an effect.
    """
    t = tool_id.lower()
    for needle, cls in (
        ("read", "read"), ("query", "read"), ("get_", "read"), ("inspect", "read"),
        ("forecast", "forecast"), ("simulate", "compute"),
        ("public", "notify_public"), ("alert", "notify_public"),
        ("broadcast", "notify_public"), ("siren", "notify_public"),
        ("work_order", "workorder"), ("dispatch", "workorder"), ("crew", "workorder"),
        ("advis", "advisory"), ("notify", "advisory"), ("message", "advisory"),
        ("isolate", "isolate"), ("close_road", "isolate"), ("cordon", "isolate"),
        ("valve", "physical_control"), ("pump", "physical_control"),
        ("gate", "physical_control"), ("sluice", "physical_control"),
    ):
        if needle in t:
            return cls
    return "actuate"
