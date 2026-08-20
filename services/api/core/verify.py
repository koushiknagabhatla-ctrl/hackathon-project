"""The verification loop. An action is only closed after read-back.

SUCCESS    intended state observed
DIFFERENCE observed, but not what we intended -> reconciliation exception
FAILED     the read-back itself failed
UNKNOWN    we do not know. A tool timeout lands HERE, never on FAILED and
           never on assumed success (contract invariant 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.api.tools import registry, sandbox

from . import audit, db

NUMERIC_TOL = 1e-6

STATUS = {"SUCCESS": "verified", "DIFFERENCE": "difference",
          "FAILED": "failed", "UNKNOWN": "unknown"}


@dataclass
class VerifyResult:
    verification: str          # SUCCESS | DIFFERENCE | FAILED | UNKNOWN
    detail: str
    actual: dict = field(default_factory=dict)
    intended: dict = field(default_factory=dict)


def _load(action) -> dict:
    if isinstance(action, str):
        a = db.q1("SELECT * FROM action WHERE id=?", action)
        if a is None:
            raise ValueError(f"unknown action '{action}'")
        return dict(a)
    return dict(action)


def _same(want, got) -> bool:
    numeric = (isinstance(want, (int, float)) and isinstance(got, (int, float))
               and not isinstance(want, bool) and not isinstance(got, bool))
    if numeric:
        return abs(float(want) - float(got)) <= NUMERIC_TOL * max(1.0, abs(float(want)))
    return want == got


# ---------------------------------------------------------------- read-back
def _readback(action: dict, intended: dict) -> dict:
    """Observe the world through the manifest's declared method."""
    wo_id = intended.get("work_order_id")
    if wo_id:
        wo = db.q1("SELECT id, status FROM work_order WHERE id=?", wo_id)
        return {"work_order_id": wo["id"], "work_order_status": wo["status"]} if wo else {}
    if action.get("target_asset_id"):
        state = sandbox.read_state(action["target_asset_id"])
        return {k: state.get(k) for k in intended} or state
    return {}


def _human_confirmation(action: dict):
    """A human confirmation is a decision='confirmed' row against the action."""
    return db.q1(
        "SELECT approver_id, rationale, decided_at FROM approval"
        " WHERE action_id=? AND decision='confirmed' ORDER BY decided_at DESC LIMIT 1",
        action["id"])


def record_confirmation(action_id: str, principal_id: str, note: str = "") -> str:
    """Field PWA / operator console records that a human saw the effect."""
    a = db.q1("SELECT plan_id FROM action WHERE id=?", action_id)
    if a is None:
        raise ValueError(f"unknown action '{action_id}'")
    cid = db.new_id("apr")
    with db.tx() as c:
        c.execute(
            "INSERT INTO approval (id, action_id, plan_id, decision, approver_id, rationale,"
            " decided_at) VALUES (?,?,?,?,?,?,?)",
            (cid, action_id, a["plan_id"], "confirmed", principal_id, note, db.now_iso()))
    return cid


# ------------------------------------------------------------------ verify
def verify(action) -> VerifyResult:
    a = _load(action)
    intended = db.jload(a.get("intended_state"), {})
    prior = db.jload(a.get("actual_state"), {})
    manifest = registry.get(a["tool_id"])
    method = a.get("verification_method") or (manifest.verification_method if manifest else "none")

    # A timeout arrived here already flagged. Never resolve it either way.
    # Keyed on the timeout marker, not on status: a human_confirmation action
    # also parks on 'unknown' while it waits, and that one CAN still resolve.
    if prior.get("timeout"):
        return _close(a, VerifyResult(
            "UNKNOWN", "tool did not answer; effect state is unknown and must be "
                       "established out of band before this action is closed",
            prior, intended))

    if method == "none" or not intended:
        return _close(a, VerifyResult(
            "SUCCESS", "no state to read back for this tool class", prior, intended))

    if method == "human_confirmation":
        c = _human_confirmation(a)
        if c is None:
            return _close(a, VerifyResult(
                "UNKNOWN", "awaiting human confirmation of the published effect",
                prior, intended))
        return _close(a, VerifyResult(
            "SUCCESS", f"confirmed by {c['approver_id']} at {c['decided_at']}",
            {"confirmed_by": c["approver_id"], "confirmed_at": c["decided_at"]}, intended))

    try:
        actual = _readback(a, intended)
    except sandbox.ToolTimeout as exc:
        return _close(a, VerifyResult("UNKNOWN", f"read-back timed out: {exc}", prior, intended))
    except Exception as exc:  # the read-back itself broke
        return _close(a, VerifyResult("FAILED", f"read-back failed: {exc}", prior, intended))

    diffs = [k for k, want in intended.items() if not _same(want, actual.get(k))]
    if diffs:
        return _close(a, VerifyResult(
            "DIFFERENCE",
            "observed state differs on " + ", ".join(
                f"{k}: intended {intended[k]!r}, actual {actual.get(k)!r}" for k in diffs),
            actual, intended))
    return _close(a, VerifyResult("SUCCESS", "read-back matches intended state",
                                  actual, intended))


def _close(a: dict, res: VerifyResult) -> VerifyResult:
    tenant, workflow = _tenant_of(a), _workflow_of(a)
    with db.tx() as c:
        c.execute("UPDATE action SET verification=?, actual_state=?, status=? WHERE id=?",
                  (res.verification, db.jdump(res.actual), STATUS[res.verification], a["id"]))
        audit.append(tenant, workflow, "core.verify", "service", "action.verified", a["id"],
                     {"verification": res.verification, "detail": res.detail,
                      "intended": res.intended, "actual": res.actual})
        if res.verification == "DIFFERENCE":
            # A difference is an exception someone owns, not a log line.
            audit.append(tenant, workflow, "core.verify", "service",
                         "reconciliation_exception", a["id"],
                         {"detail": res.detail, "intended": res.intended,
                          "actual": res.actual, "owner": "duty_operator"})
    return res


def _incident_of(a: dict):
    return db.q1("SELECT i.* FROM incident i JOIN plan p ON p.incident_id = i.id WHERE p.id=?",
                 a["plan_id"])


def _tenant_of(a: dict) -> str:
    inc = _incident_of(a)
    return inc["tenant_id"] if inc else "unknown"


def _workflow_of(a: dict) -> str:
    inc = _incident_of(a)
    return inc["id"] if inc else a["plan_id"]


# ---------------------------------------------------------------- rollback
def rollback(action, principal, idempotency_key: str | None = None) -> dict:
    """Invoke the manifest's rollback tool through the gateway.

    A compensating effect is an action like any other: same chain, same policy,
    same audit trail. Nothing bypasses core/gateway.py::execute.
    """
    from . import gateway  # deferred: gateway imports verify

    a = _load(action)
    manifest = registry.require(a["tool_id"])
    rb_id = a.get("rollback_tool_id") or manifest.rollback_tool_id
    if not rb_id:
        raise ValueError(f"tool '{a['tool_id']}' declares no rollback path; it is not reversible")
    rb = registry.require(rb_id)

    # Build the compensating args from what we know about the original effect.
    known = {**db.jload(a.get("args"), {}), **db.jload(a.get("intended_state"), {}),
             **db.jload(a.get("actual_state"), {})}
    props = (rb.input_schema.get("properties") or {}).keys()
    rb_args = {k: known[k] for k in props if known.get(k) is not None}

    new_id = db.new_id("act")
    with db.tx() as c:
        seq = c.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM action WHERE plan_id=?",
                        (a["plan_id"],)).fetchone()[0]
        c.execute(
            "INSERT INTO action (id, plan_id, tool_id, sequence, args, target_asset_id,"
            " risk_tier, risk_inputs, blast_radius, reversible, status, verification_method)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id, a["plan_id"], rb_id, seq, db.jdump(rb_args), a.get("target_asset_id"),
             a["risk_tier"], a.get("risk_inputs") or "{}", a.get("blast_radius") or 0, 1,
             "approved", rb.verification_method))
    return gateway.execute(new_id, principal, idempotency_key or f"rollback:{a['id']}")
