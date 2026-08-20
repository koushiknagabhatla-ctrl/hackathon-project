"""Sandbox twins: the only implementations any tool ever has.

These are not stubs that return a canned string. They are functionally
equivalent to a production tool against the SQLite twin: pump.setpoint really
writes a setpoint that a later read-back observes, workorder.create really
inserts a work_order row. Nothing here reaches a network.

Every write goes through `db.tx()`, which is re-entrant, so an implementation
called inside `gateway.execute`'s transaction joins it: if anything later in
the chain fails, the twin mutation rolls back with it.
"""

from __future__ import annotations

import os
import random
import time

from services.api.core import db, twin


class SandboxError(RuntimeError):
    """The tool ran and failed. Distinct from ToolTimeout on purpose."""


class ToolTimeout(TimeoutError):
    """The tool did not answer. Maps to UNKNOWN, never FAILED (invariant 7)."""


class ProhibitedTool(PermissionError):
    """The sandbox itself refuses. Belt to the policy engine's braces."""


# Realistic per-tool latency in milliseconds. Small enough for tests, big
# enough that the UI's pending states are real.
LATENCY_MS = {
    "twin.query": 12, "evidence.get": 6, "forecast.run": 45, "plan.draft": 30,
    "workorder.create": 25, "workorder.cancel": 15, "traffic.reroute_advisory": 35,
    "traffic.restore": 20, "pump.setpoint": 40, "alert.publish_cap": 60,
    "network.isolate_segment": 55, "network.restore_segment": 45,
}


def _env_set(name: str) -> set[str]:
    return {t for t in os.environ.get(name, "").split(",") if t}


# Deliberate failure injection so the timeout, DIFFERENCE and partial-failure
# paths are demonstrable rather than theoretical. Mutable sets: a test or the
# demo driver adds a tool id, exercises the path, removes it again.
TIMEOUT_TOOLS: set[str] = _env_set("AURALIS_TIMEOUT_TOOLS")
DRIFT_TOOLS: set[str] = _env_set("AURALIS_DRIFT_TOOLS")
FAIL_AFTER_WRITE_TOOLS: set[str] = _env_set("AURALIS_FAIL_AFTER_WRITE_TOOLS")


# ----------------------------------------------------------------- helpers
def _asset(asset_id: str):
    a = db.q1("SELECT * FROM asset WHERE id=?", asset_id)
    if a is None:
        raise SandboxError(f"unknown asset '{asset_id}'")
    return a


def _patch_state(asset_id: str, patch: dict) -> dict:
    """Merge into reported_state and mirror into current_state.

    reported_state is what the device says; current_state is the twin's belief.
    verify() reads reported_state back.
    """
    a = _asset(asset_id)
    reported = db.jload(a["reported_state"], {})
    current = db.jload(a["current_state"], {})
    reported.update(patch)
    current.update(patch)
    with db.tx() as c:
        c.execute("UPDATE asset SET reported_state=?, current_state=? WHERE id=?",
                  (db.jdump(reported), db.jdump(current), asset_id))
    return reported


def read_state(asset_id: str) -> dict:
    """Read-back primitive used by core/verify.py."""
    return db.jload(_asset(asset_id)["reported_state"], {})


# ------------------------------------------------------------ implementations
def _twin_query(args, ctx):
    r = twin.query(args["asset_id"], int(args.get("depth", 3)))
    return {"root": r.root, "nodes": [n.model_dump() for n in r.nodes],
            "edges": r.edges, "blast_radius": r.blast_radius}


def _evidence_get(args, ctx):
    e = db.q1("SELECT * FROM evidence WHERE id=?", args["evidence_id"])
    if e is None:
        raise SandboxError(f"unknown evidence '{args['evidence_id']}'")
    return {"id": e["id"], "statement": e["statement"], "observed_at": e["observed_at"],
            "expires_at": e["expires_at"], "trust_tier": e["trust_tier"],
            "evidence_class": e["evidence_class"], "status": e["status"],
            "value": db.jload(e["value_json"], {})}


def _forecast_run(args, ctx):
    """Seeded and deterministic: same seed and asset => same numbers."""
    level = float(db.jload(_asset(args["asset_id"])["current_state"], {}).get("level_m", 1.0))
    rng = random.Random(f"{args.get('seed', 42)}:{args['asset_id']}")
    horizon = int(args["horizon_min"])
    drift = level + horizon / 60.0 * (0.18 + rng.random() * 0.06)
    spread = 0.12 + horizon / 600.0
    return {"median": round(drift, 3), "p10": round(drift - spread, 3),
            "p90": round(drift + spread, 3), "unit": "m", "horizon_min": horizon,
            "series": [{"t": m, "v": round(level + m / 60.0 * 0.2, 3)}
                       for m in range(0, horizon + 1, max(horizon // 6, 1))]}


def _plan_draft(args, ctx):
    return {"title": f"Response to {args['incident_id']}: {args['objective']}",
            "steps": [{"seq": 1, "tool_id": "twin.query", "why": "establish blast radius"},
                      {"seq": 2, "tool_id": "workorder.create", "why": "put a human on site"}]}


def _workorder_create(args, ctx):
    a = _asset(args["asset_id"])
    wid = db.new_id("wo")
    with db.tx() as c:
        c.execute(
            "INSERT INTO work_order (id, tenant_id, incident_id, action_id, title,"
            " instructions, asset_id, priority, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (wid, a["tenant_id"], args.get("incident_id"), ctx.get("action_id"),
             args["title"], args["instructions"], args["asset_id"],
             int(args.get("priority", 3)), "open", db.now_iso()))
    return {"work_order_id": wid, "status": "open"}


def _workorder_cancel(args, ctx):
    with db.tx() as c:
        c.execute("UPDATE work_order SET status='cancelled', closed_at=? WHERE id=?",
                  (db.now_iso(), args["work_order_id"]))
    return {"ok": True, "work_order_id": args["work_order_id"], "status": "cancelled"}


def _traffic_advisory(args, ctx):
    advisory = args["advisory"]
    if "traffic.reroute_advisory" in DRIFT_TOOLS:
        advisory += " (partial rollout)"
    _patch_state(args["asset_id"], {"advisory": advisory, "advisory_active": True})
    return {"asset_id": args["asset_id"], "advisory": advisory}


def _traffic_restore(args, ctx):
    _patch_state(args["asset_id"], {"advisory": None, "advisory_active": False})
    return {"ok": True, "asset_id": args["asset_id"]}


def _pump_setpoint(args, ctx):
    want = float(args["setpoint"])
    # A real actuator lands where it lands. DRIFT_TOOLS makes that observable.
    got = round(want * 0.8, 3) if "pump.setpoint" in DRIFT_TOOLS else want
    _patch_state(args["asset_id"], {"setpoint": got, "unit": args.get("unit", "pct"),
                                    "setpoint_at": db.now_iso()})
    return {"asset_id": args["asset_id"], "setpoint": got, "unit": args.get("unit", "pct")}


def _alert_publish_cap(args, ctx):
    pid = db.new_id("alert")
    cap = ("<alert><identifier>{i}</identifier><sender>{a}</sender><info>"
           "<severity>{s}</severity><headline>{h}</headline></info></alert>").format(
        i=pid, a=args["authority"], s=args["severity"], h=args["headline"])
    with db.tx() as c:
        c.execute(
            "INSERT INTO alert_publication (id, incident_id, cap_xml, authority, channel,"
            " version, status, published_at, disclosure_delay_s) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, args["incident_id"], cap, args["authority"],
             args.get("channel", "public-web"), 1, "published", db.now_iso(), 300))
    return {"publication_id": pid, "status": "published"}


def _network_isolate(args, ctx):
    _patch_state(args["asset_id"], {"isolated": True, "isolation_reason": args["reason"]})
    return {"asset_id": args["asset_id"], "isolated": True}


def _network_restore(args, ctx):
    _patch_state(args["asset_id"], {"isolated": False, "isolation_reason": None})
    return {"asset_id": args["asset_id"], "isolated": False}


def _scada_direct(args, ctx):
    raise ProhibitedTool(
        "scada.direct_control has no implementation and never will: Auralis does not "
        "build direct equipment control. Raise a work order instead."
    )


IMPLS = {
    "twin.query": _twin_query,
    "evidence.get": _evidence_get,
    "forecast.run": _forecast_run,
    "plan.draft": _plan_draft,
    "workorder.create": _workorder_create,
    "workorder.cancel": _workorder_cancel,
    "traffic.reroute_advisory": _traffic_advisory,
    "traffic.restore": _traffic_restore,
    "pump.setpoint": _pump_setpoint,
    "alert.publish_cap": _alert_publish_cap,
    "network.isolate_segment": _network_isolate,
    "network.restore_segment": _network_restore,
    "scada.direct_control": _scada_direct,
}


def call(tool_id: str, args: dict, ctx: dict | None = None) -> dict:
    """Invoke a sandbox twin. Only core/gateway.py may call this."""
    impl = IMPLS.get(tool_id)
    if impl is None:
        raise SandboxError(f"tool '{tool_id}' has no sandbox implementation")
    time.sleep(LATENCY_MS.get(tool_id, 5) / 1000.0)
    if tool_id in TIMEOUT_TOOLS:
        raise ToolTimeout(f"tool '{tool_id}' did not respond within its budget")
    result = impl(args, ctx or {})
    if tool_id in FAIL_AFTER_WRITE_TOOLS:
        # Failure injection AFTER the twin write: proves the caller's
        # transaction rolls the mutation back rather than half-applying it.
        raise SandboxError(f"tool '{tool_id}' failed after mutating twin state")
    return result
