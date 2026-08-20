"""The tool gateway: THE ONLY PATH FROM PLAN TO EFFECT (invariant 3).

`execute` runs a fixed chain and short-circuits with an audit event at every
failure. The order is deliberate and is the security design:

  1  plan status                     8  evidence / precondition RECHECK
  2  args vs manifest input_schema   9  risk gate (tier may have escalated)
  3  tool allow-list for principal  10  human approval present + unexpired
  4  workload identity not revoked  11  idempotency key
  5  tenant / role authorization    12  sandbox implementation
  6  SIMULATION BARRIER             13  response vs output_schema
  7  policy.decide                  14  reconcile -> verify -> audit

Step 8 exists because evidence goes stale between approval and execute. We
recheck. We never trust the approval.

TRANSACTIONS. Steps 1-11 are read-only except the policy_decision row, which
must survive a denial - a refusal that is not logged never happened. Steps
12-14 run inside ONE re-entrant `db.tx()`: the twin mutation, the result
record, the reconciliation and the audit entries commit together or not at
all, so a tool that fails halfway leaves no half-applied effect.
"""

from __future__ import annotations

import datetime as _dt

from services.api.tools import registry, sandbox

from . import audit, db, evidence as evidence_mod, policy, risk, twin
from . import verify as verify_mod

TERMINAL = ("executed", "verified", "difference", "failed", "unknown", "rolled_back")
BLOCKED_PLAN_STATES = ("rejected", "blocked", "failed")


class GatewayError(Exception):
    """Short-circuit. `code` is the wire error code, `rule_id` set for policy."""

    def __init__(self, code: str, message: str, detail: dict | None = None,
                 rule_id: str | None = None):
        super().__init__(message)
        self.code, self.message, self.detail, self.rule_id = code, message, detail or {}, rule_id

    def as_error(self) -> dict:
        return {"code": self.code, "message": self.message,
                "detail": {**self.detail, **({"rule_id": self.rule_id} if self.rule_id else {})}}


# --------------------------------------------------- minimal schema checker
# ponytail: covers type/properties/required/enum/minimum/maximum, which is all
# our manifests use. Swap in `jsonschema` only if a manifest needs more.
_TYPES = {"object": dict, "array": list, "string": str,
          "number": (int, float), "integer": int, "boolean": bool}


def validate_schema(schema: dict, value, path: str = "args") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t:
        py = _TYPES.get(t)
        bad_bool = t in ("integer", "number") and isinstance(value, bool)
        if bad_bool or (py and not isinstance(value, py)):
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if t == "object" and isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}.{req}: required property missing")
        for key, sub in (schema.get("properties") or {}).items():
            if value.get(key) is not None:
                errs += validate_schema(sub, value[key], f"{path}.{key}")
    return errs


def _principal(principal) -> dict:
    if isinstance(principal, str):
        p = db.q1("SELECT * FROM principal WHERE id=?", principal)
        if p is None:
            raise GatewayError("identity_unknown", f"no principal '{principal}'")
        return dict(p)
    return dict(principal)


# --------------------------------------------------------------- the chain
def execute(action_id: str, principal, idempotency_key: str) -> dict:
    ctx_audit = {"action_id": action_id, "idempotency_key": idempotency_key}

    row = db.q1(
        "SELECT a.*, p.status AS plan_status, p.incident_id AS incident_id,"
        " p.evidence_ids AS plan_evidence, i.tenant_id AS tenant_id"
        " FROM action a JOIN plan p ON p.id = a.plan_id"
        " JOIN incident i ON i.id = p.incident_id WHERE a.id=?", action_id)
    if row is None:
        raise GatewayError("action_unknown", f"no action '{action_id}'")
    a = dict(row)
    tenant, workflow = a["tenant_id"], a["incident_id"]
    who = _principal(principal)

    def fail(code: str, message: str, detail=None, rule_id=None):
        audit.append(tenant, workflow, who.get("id", "unknown"), "service",
                     "action.blocked", action_id,
                     {"code": code, "message": message, "rule_id": rule_id,
                      **ctx_audit, **(detail or {})})
        raise GatewayError(code, message, detail, rule_id)

    args = db.jload(a["args"], {})
    is_replay = a["status"] in TERMINAL and a["idempotency_key"] == idempotency_key

    # 1 -------------------------------------------------------- plan status
    if a["plan_status"] in BLOCKED_PLAN_STATES:
        fail("plan_not_executable", f"plan {a['plan_id']} is '{a['plan_status']}'")
    if a["status"] == "blocked":
        fail("action_not_executable", "action is blocked and must be re-planned")
    if a["status"] in TERMINAL and not is_replay:
        fail("action_not_executable",
             f"action already '{a['status']}' under a different idempotency key")

    # 2 ----------------------------------------------- args vs input_schema
    try:
        manifest = registry.require(a["tool_id"])
    except registry.ManifestRejected as exc:
        fail("tool_unknown", str(exc))
    errs = validate_schema(manifest.input_schema, args)
    if errs:
        fail("args_invalid", "arguments do not match the tool manifest", {"errors": errs})

    # 3 --------------------------------------------------------- allow-list
    if not registry.visible_to(who, a["tool_id"]):
        fail("tool_not_allowed",
             f"role '{who.get('role')}' may not see or invoke '{a['tool_id']}'")

    # 4 ------------------------------------------- identity valid / revoked
    if who.get("status") != "active":
        fail("identity_revoked",
             f"principal {who.get('id')} is '{who.get('status')}', not active")
    if who.get("role") == "agent" and not who.get("spiffe_id"):
        fail("identity_invalid", f"agent {who.get('id')} carries no workload identity")

    # 5 ----------------------------------------------- tenant / role authz
    if who.get("tenant_id") != tenant:
        fail("tenant_mismatch",
             f"principal tenant '{who.get('tenant_id')}' cannot act in tenant '{tenant}'")

    # 6 ------------------------------------------------- SIMULATION BARRIER
    if (who.get("trust_domain") or "prod") == "sim" and manifest.trust_domain == "prod":
        fail("simulation_barrier",
             f"principal {who.get('id')} is in trust_domain 'sim' and may not invoke "
             f"production tool '{a['tool_id']}'",
             {"trust_domain": who.get("trust_domain"), "tool_id": a["tool_id"]})

    # live facts, read NOW -- never the approval-time snapshot
    asset = db.q1("SELECT * FROM asset WHERE id=?", a["target_asset_id"]) \
        if a.get("target_asset_id") else None
    ev_age, ev_status, ev_invalid = _evidence_state(a)
    blast = twin.query(asset["id"], 3).blast_radius if asset else int(a.get("blast_radius") or 0)
    public_facing = bool(args.get("public_facing", manifest.public_facing))
    tier, risk_inputs = risk.compute_tier(
        manifest.action_class,
        asset_criticality=int(asset["criticality"]) if asset else 0,
        blast_radius=blast, evidence_age_s=ev_age,
        public_facing=public_facing, reversible=manifest.reversible)
    approvals = [dict(r) for r in db.q(
        "SELECT approver_id, decision, expires_at, approver_authority AS authority"
        " FROM approval WHERE action_id=? AND decision='approved'", action_id)]

    # 7 ------------------------------------------------------ policy.decide
    pctx = {
        "action_id": action_id, "tool_id": a["tool_id"], "action_class": manifest.action_class,
        "risk_tier": tier, "tenant_id": tenant,
        "principal_id": who.get("id"), "principal_role": who.get("role"),
        "principal_kind": "agent" if who.get("role") == "agent" else "human",
        "principal_status": who.get("status"), "principal_tenant": who.get("tenant_id"),
        "principal_trust_domain": who.get("trust_domain") or "prod",
        "principal_spiffe_id": who.get("spiffe_id"),
        "principal_authority": who.get("authority"),
        "principal_jurisdictions": _jurisdictions(who),
        "asset_id": asset["id"] if asset else None,
        "asset_tenant": asset["tenant_id"] if asset else None,
        "asset_criticality": int(asset["criticality"]) if asset else 0,
        "asset_jurisdiction": (db.jload(asset["current_state"], {}).get("jurisdiction")
                               if asset else None),
        "blast_radius": blast, "evidence_age_s": ev_age, "evidence_status": ev_status,
        "public_facing": public_facing, "reversible": manifest.reversible,
        "tool_trust_domain": manifest.trust_domain,
        "time_window": db.jload(asset["maintenance_window"]) if asset else None,
        "recent_actions_1h": _recent_actions(tenant, tier),
        "approvals": approvals,
        # Break-glass is fail-closed: EMERGENCY_OVERRIDE can only ever DENY, so
        # a caller-supplied claim can never make an action more permitted.
        "emergency": args.get("__emergency__"),
        "now": db.now_iso(),
    }
    decision = policy.decide(pctx, subject_action_id=action_id)
    db.run("UPDATE action SET policy_decision_id=?, risk_tier=?, risk_inputs=? WHERE id=?",
           decision.id, tier, db.jdump(risk_inputs), action_id)
    if decision.effect == "deny":
        fail("policy_denied", decision.reason,
             {"policy_decision_id": decision.id, "inputs_hash": decision.inputs_hash},
             rule_id=decision.rule_id)

    # 8 ------------------------------------ evidence / precondition RECHECK
    if ev_invalid:
        fail("evidence_stale",
             "supporting evidence is no longer valid at execution time: "
             + "; ".join(ev_invalid), {"evidence": ev_invalid})
    if asset:
        permitted = db.jload(asset["permitted_actions"], [])
        if permitted and a["tool_id"] not in permitted:
            fail("precondition_failed",
                 f"asset {asset['id']} does not permit '{a['tool_id']}'",
                 {"permitted_actions": permitted})

    # 9 --------------------------------------------------------- risk gate
    if risk.max_tier(tier, a["risk_tier"]) != a["risk_tier"] and not is_replay:
        fail("risk_escalated",
             f"risk re-computed as {tier} at execution time; this action was planned "
             f"and approved at {a['risk_tier']}. Re-approve at the higher tier.",
             {"planned_tier": a["risk_tier"], "current_tier": tier,
              "risk_inputs": risk_inputs})
    if tier == "R5":
        fail("policy_denied", "R5 direct equipment control is prohibited",
             {"tier": tier}, rule_id="R5_PROHIBITED")

    # 10 ------------------------------------------------- approval present
    if decision.effect == "require_approval":
        fail("approval_required", decision.reason,
             {"policy_decision_id": decision.id, "approvals_on_file": len(approvals)},
             rule_id=decision.rule_id)

    # 11 ------------------------------------------------------ idempotency
    clash = db.q1("SELECT id FROM action WHERE idempotency_key=? AND id<>?",
                  idempotency_key, action_id)
    if clash:
        fail("idempotency_conflict", f"idempotency key already used by action {clash['id']}")
    prior = _prior_result(a, idempotency_key)
    if prior is not None:
        audit.append(tenant, workflow, who["id"], "service", "action.idempotent_replay",
                     action_id, ctx_audit)
        return prior

    # 12-14 ------------------- one transaction: effect, reconcile, verify
    actor_kind = "agent" if who.get("role") == "agent" else "human"
    try:
        with db.tx() as c:
            c.execute("UPDATE action SET idempotency_key=?, status='executing' WHERE id=?",
                      (idempotency_key, action_id))
            audit.append(tenant, workflow, who["id"], actor_kind, "action.executing",
                         action_id, {"tool_id": a["tool_id"], "args": args, "risk_tier": tier,
                                     "policy_decision_id": decision.id, **ctx_audit})
            result = sandbox.call(a["tool_id"], args, ctx={"action_id": action_id})

            out_errs = validate_schema(manifest.output_schema, result, "result")
            if out_errs:
                raise _ResponseInvalid(out_errs, result)

            intended = intended_state(a["tool_id"], args, result)
            c.execute("UPDATE action SET status='executed', executed_at=?, intended_state=?,"
                      " verification_method=? WHERE id=?",
                      (db.now_iso(), db.jdump(intended), manifest.verification_method,
                       action_id))
            audit.append(tenant, workflow, who["id"], "service", "tool.result", action_id,
                         {"idempotency_key": idempotency_key, "result": result,
                          "intended_state": intended, "tool_id": a["tool_id"]})
            v = verify_mod.verify(action_id)
            out = {"action_id": action_id, "status": verify_mod.STATUS[v.verification],
                   "tool_id": a["tool_id"], "risk_tier": tier, "result": result,
                   "intended_state": intended, "actual_state": v.actual,
                   "verification": v.verification, "verification_detail": v.detail,
                   "policy_decision_id": decision.id, "idempotency_key": idempotency_key}
            audit.append(tenant, workflow, who["id"], "service", "action.executed",
                         action_id, out)
            return out
    except sandbox.ToolTimeout as exc:
        return _on_timeout(a, who, tenant, workflow, str(exc), idempotency_key)
    except sandbox.ProhibitedTool as exc:
        db.run("UPDATE action SET status='blocked' WHERE id=?", action_id)
        fail("policy_denied", str(exc), {"tool_id": a["tool_id"]}, rule_id="R5_PROHIBITED")
    except _ResponseInvalid as exc:
        # transaction rolled back: no effect, nothing half-applied
        fail("response_invalid", "tool response does not match its manifest",
             {"errors": exc.errors, "result": exc.result})
    except Exception as exc:
        fail("tool_failed", f"{type(exc).__name__}: {exc}",
             {"tool_id": a["tool_id"], "rolled_back": True})


class _ResponseInvalid(Exception):
    def __init__(self, errors, result):
        super().__init__("response invalid")
        self.errors, self.result = errors, result


# ------------------------------------------------------- chain sub-helpers
def _on_timeout(a, who, tenant, workflow, detail, idempotency_key) -> dict:
    """A timeout is UNKNOWN. Never failed, never assumed successful.

    The tool's own transaction rolled back, so the twin is untouched by us --
    but the far side may still act, which is exactly why the answer is UNKNOWN
    and not 'nothing happened'.
    """
    with db.tx() as c:
        c.execute(
            "UPDATE action SET idempotency_key=?, status='unknown', executed_at=?,"
            " actual_state=?, verification=? WHERE id=?",
            (idempotency_key, db.now_iso(),
             db.jdump({"timeout": True, "detail": detail}), "UNKNOWN", a["id"]))
        audit.append(tenant, workflow, who["id"], "service", "action.timeout", a["id"],
                     {"tool_id": a["tool_id"], "detail": detail, "verification": "UNKNOWN",
                      "idempotency_key": idempotency_key})
        v = verify_mod.verify(a["id"])
    return {"action_id": a["id"], "status": "unknown", "tool_id": a["tool_id"],
            "result": None, "verification": v.verification,
            "verification_detail": v.detail, "actual_state": v.actual,
            "intended_state": {}, "policy_decision_id": a.get("policy_decision_id"),
            "idempotency_key": idempotency_key}


INTENDED_STATE = {
    "pump.setpoint": lambda ar, r: {"setpoint": float(ar["setpoint"])},
    "traffic.reroute_advisory": lambda ar, r: {"advisory": ar["advisory"],
                                               "advisory_active": True},
    "traffic.restore": lambda ar, r: {"advisory_active": False},
    "network.isolate_segment": lambda ar, r: {"isolated": True},
    "network.restore_segment": lambda ar, r: {"isolated": False},
    "workorder.create": lambda ar, r: {"work_order_id": r["work_order_id"],
                                       "work_order_status": "open"},
    "workorder.cancel": lambda ar, r: {"work_order_id": ar["work_order_id"],
                                       "work_order_status": "cancelled"},
    "alert.publish_cap": lambda ar, r: {"publication_id": r["publication_id"],
                                        "headline": ar["headline"]},
}


def intended_state(tool_id: str, args: dict, result: dict) -> dict:
    fn = INTENDED_STATE.get(tool_id)
    return fn(args, result) if fn else {}


def _evidence_state(a) -> tuple[int | None, str, list[str]]:
    """Age and validity of the plan's evidence AS OF NOW.

    Uses evidence.as_ref so freshness here and freshness in the UI are the same
    computation, never two drifting opinions.
    """
    ids = db.jload(a.get("plan_evidence"), [])
    if not ids:
        return None, "valid", []
    oldest, worst, invalid = 0, "valid", []
    for eid in ids:
        row = db.q1("SELECT * FROM evidence WHERE id=?", eid)
        if row is None:
            invalid.append(f"{eid}: missing")
            worst = "missing"
            continue
        ref = evidence_mod.as_ref(row)
        oldest = max(oldest, ref.age_s)
        if not ref.fresh:
            invalid.append(f"{eid}: {ref.status if ref.status != 'valid' else 'expired'}")
            worst = ref.status if ref.status != "valid" else "expired"
    return oldest, worst, invalid


def _recent_actions(tenant: str, tier: str) -> int:
    hour_ago = db.iso(db.parse_iso(db.now_iso()) - _dt.timedelta(hours=1))
    return db.scalar(
        "SELECT COUNT(*) FROM action a JOIN plan p ON p.id=a.plan_id"
        " JOIN incident i ON i.id=p.incident_id"
        " WHERE i.tenant_id=? AND a.risk_tier=? AND a.executed_at > ?",
        tenant, tier, hour_ago, default=0)


def _jurisdictions(who: dict) -> list[str]:
    parsed = db.jload(who.get("authority"))
    return parsed.get("jurisdictions", []) if isinstance(parsed, dict) else []


def _prior_result(a: dict, key: str) -> dict | None:
    """The FIRST result for this key, replayed. No second effect is produced."""
    if a["idempotency_key"] != key or a["status"] not in TERMINAL:
        return None
    ev = db.q1("SELECT payload FROM audit_event WHERE kind='tool.result'"
               " AND subject_id=? ORDER BY seq ASC LIMIT 1", a["id"])
    if ev is None:
        return None
    payload = db.jload(ev["payload"], {})
    if payload.get("idempotency_key") != key:
        return None
    cur = db.q1("SELECT * FROM action WHERE id=?", a["id"])
    return {"action_id": a["id"], "status": cur["status"], "tool_id": cur["tool_id"],
            "risk_tier": cur["risk_tier"], "result": payload["result"],
            "intended_state": db.jload(cur["intended_state"], {}),
            "actual_state": db.jload(cur["actual_state"], {}),
            "verification": cur["verification"], "verification_detail": "idempotent replay",
            "policy_decision_id": cur["policy_decision_id"], "idempotency_key": key,
            "replayed": True}


# ------------------------------------------------------------- kill switch
def revoke_agent(agent_id: str, approver_a: str, approver_b: str) -> dict:
    """Kill switch. Dual control, revokes identity, halts runs, quarantines plans."""
    if approver_a == approver_b:
        raise GatewayError("dual_control_required", "revocation needs two distinct approvers")
    for who in (approver_a, approver_b):
        p = db.q1("SELECT * FROM principal WHERE id=?", who)
        if p is None or p["status"] != "active" or p["role"] not in ("admin", "approver"):
            raise GatewayError("dual_control_required",
                               f"approver '{who}' is not an active admin or approver")
    agent = db.q1("SELECT * FROM principal WHERE id=?", agent_id)
    if agent is None:
        raise GatewayError("identity_unknown", f"no principal '{agent_id}'")

    now = db.now_iso()
    plans = [r["id"] for r in db.q(
        "SELECT id FROM plan WHERE created_by=? AND status IN"
        " ('draft','validated','approved','executing')", agent_id)]
    with db.tx() as c:
        c.execute("UPDATE principal SET status='revoked' WHERE id=?", (agent_id,))
        halted = c.execute(
            "UPDATE agent_run SET status='halted', ended_at=? WHERE agent_id=?"
            " AND ended_at IS NULL", (now, agent_id)).rowcount
        quarantined_actions = 0
        if plans:
            marks = ", ".join("?" * len(plans))
            c.execute(f"UPDATE plan SET status='blocked' WHERE id IN ({marks})", plans)
            quarantined_actions = c.execute(
                f"UPDATE action SET status='blocked' WHERE plan_id IN ({marks})"
                f" AND status IN ('proposed','approved','executing')", plans).rowcount
        summary = {"agent_id": agent_id, "revoked_at": now, "halted_runs": halted,
                   "quarantined_plans": plans, "quarantined_actions": quarantined_actions,
                   "approvers": [approver_a, approver_b]}
        audit.append(agent["tenant_id"], f"revoke:{agent_id}", approver_a, "human",
                     "agent.revoked", agent_id, summary)
    return summary
