"""The agent runtime contract: identity, budgets, forbidden zones, grounding.

Every specialist agent in this package is the same shape:

  * a unique id, a version, an owner, a scope, an allowed-domain list, an
    allowed-tool list, a wall-clock runtime budget and a tool-call budget;
  * ONE input - an IMMUTABLE `evidence_snapshot`, loaded once by id. An agent
    never re-reads live evidence mid-run, so what it concluded and what it saw
    can never drift apart;
  * schema-validated output (a pydantic model per agent);
  * an `agent_run` row carrying prompt version, model version, snapshot id and
    the ids of the claims it produced.

DETERMINISTIC REPLAY: on the deterministic path, output is a pure function of
(snapshot, prompt version, model version). Agents derive every time fact from
`snapshot.taken_at`, never from `now()`, so replaying an old snapshot tomorrow
reproduces today's answer exactly.

GROUNDING is enforced here and again in `core/claims.py`. An agent statement
reaches a human only if it cites evidence ids that are IN THE SNAPSHOT it ran
against. A statement citing nothing, or citing an id the agent made up, is
DROPPED and the drop is recorded - it is never surfaced, never softened, never
downgraded to a "low confidence" claim.
"""

from __future__ import annotations

import hashlib
import os
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from services.api.core import audit, claims, db

GROUNDED_CLASSES = ("fact", "forecast")

# audit kinds this lane owns. `claim.created` is written by core/claims.py.
KIND_CLAIM_DROPPED = "claim.dropped_unsupported"
KIND_AGENT_STARTED = "agent.started"
KIND_AGENT_FINISHED = "agent.finished"
KIND_FORBIDDEN_ZONE = "agent.forbidden_zone_blocked"
KIND_DISAGREEMENT = "agent.disagreement"
KIND_TOOL_DROPPED = "plan.action_dropped_out_of_catalogue"


class ForbiddenZone(PermissionError):
    """An agent reached outside its declared scope. Always an audit event."""


class BudgetExceeded(RuntimeError):
    """Runtime or tool-call budget spent. Terminates the run, keeps the record."""


# ------------------------------------------------------------------- spec
@dataclass(frozen=True)
class AgentSpec:
    id: str
    version: str
    owner: str
    scope: str
    forbidden: str                      # the zone, in words, for the audit trail
    template: str
    allowed_domains: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    runtime_budget_s: float = 20.0
    tool_call_budget: int = 0
    writes: bool = False                # may this agent cause an external effect

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.id, "version": self.version, "owner": self.owner,
            "scope": self.scope, "forbidden": self.forbidden,
            "allowed_domains": list(self.allowed_domains),
            "allowed_tools": list(self.allowed_tools),
            "runtime_budget_s": self.runtime_budget_s,
            "tool_call_budget": self.tool_call_budget, "writes": self.writes,
        }


def runtime_budget_for(spec_budget_s: float) -> float:
    """The budget actually enforced, scaled to the backend in play.

    The per-agent budgets assume a hosted model that answers in seconds. A
    local CPU model legitimately needs minutes, and discarding a run that
    FINISHED — throwing away good, grounded analysis — because it overran a
    hosted-model budget is a bug, not a safety control.

    The budget exists to stop a runaway loop, so it must stay finite and it
    must still bound the local path. It is derived here rather than edited into
    each AgentSpec so there is one rule, not four drifting copies.
    """
    override = os.environ.get("AURALIS_AGENT_RUNTIME_BUDGET_S", "").strip()
    if override:
        return float(override)

    backends = os.environ.get("AURALIS_LLM_BACKEND", "local,anthropic,deterministic")
    if "local" in [b.strip() for b in backends.split(",")]:
        # Bound by the model's own wall-clock timeout, plus headroom for
        # tokenisation and claim assembly around the generate() call.
        local_timeout = float(os.environ.get("AURALIS_LOCAL_MODEL_TIMEOUT_S", "300"))
        return max(spec_budget_s, local_timeout + 60.0)

    return spec_budget_s


# --------------------------------------------------------------- snapshot
@dataclass(frozen=True)
class Snapshot:
    """An immutable view of the evidence at one instant. Agents get the id."""

    id: str
    incident_id: str
    taken_at: str
    hash: str
    evidence: tuple[Mapping[str, Any], ...]
    unknowns: tuple[str, ...] = ()
    incident: Mapping[str, Any] = field(default_factory=dict)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(str(e["id"]) for e in self.evidence)

    def get(self, evidence_id: str) -> Mapping[str, Any] | None:
        return next((e for e in self.evidence if e["id"] == evidence_id), None)

    def by_metric(self, metric: str) -> tuple[Mapping[str, Any], ...]:
        """Every valid item measuring `metric`, per the core/evidence.py
        value_json convention {"subject","metric","value","unit","ref"}."""
        return tuple(
            e for e in self.evidence
            if (e.get("value") or {}).get("metric") == metric
            and e.get("status") == "valid"
        )

    def reading(self, metric: str) -> tuple[float | None, str | None]:
        """The single best numeric reading for `metric`, or (None, None).

        Highest trust tier wins, then most recently observed. Values are NEVER
        averaged - a losing measurement stays on the record, it just does not
        win. Returning (None, None) is a correct answer and the caller must
        treat it as "unknown", never as a reason to pick a default.
        """
        order = ["statutory", "certified", "verified", "crowdsourced", "unknown"]
        cands = [
            e for e in self.by_metric(metric)
            if isinstance((e.get("value") or {}).get("value"), (int, float))
        ]
        if not cands:
            return None, None
        best = min(cands, key=lambda e: (
            order.index(e["trust_tier"]) if e["trust_tier"] in order else len(order),
            -_epoch(e.get("observed_at", "")),
        ))
        return float(best["value"]["value"]), str(best["id"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "incident_id": self.incident_id,
            "taken_at": self.taken_at, "snapshot_hash": self.hash,
            "evidence": [dict(e) for e in self.evidence],
            "unknowns": list(self.unknowns), "incident": dict(self.incident),
        }

    # ------------------------------------------------------------- loading
    @classmethod
    def load(cls, snapshot_id: str) -> Snapshot:
        row = db.q1("SELECT * FROM evidence_snapshot WHERE id=?", snapshot_id)
        if row is None:
            raise ValueError(f"unknown evidence snapshot: {snapshot_id}")
        body = db.jload(row["body"], {}) or {}
        if isinstance(body, list):
            body = {"evidence": body}
        return cls(
            id=row["id"], incident_id=row["incident_id"], taken_at=row["taken_at"],
            hash=row["snapshot_hash"],
            evidence=tuple(MappingProxyType(dict(e)) for e in body.get("evidence", [])),
            unknowns=tuple(body.get("unknowns", [])),
            incident=MappingProxyType(dict(body.get("incident", {}))),
        )

    @classmethod
    def take(cls, incident_id: str) -> Snapshot:
        """Freeze the incident's current evidence into an `evidence_snapshot` row.

        LANE SEAM: `evidence_snapshot` is Lane A's table. If `core/evidence.py`
        grows a `take_snapshot`, it is used instead and this body goes away. The
        invariant that matters either way is that an agent reads a frozen row,
        never live evidence.
        """
        from services.api.core import evidence as ev_mod

        if hasattr(ev_mod, "take_snapshot"):
            return cls.load(ev_mod.take_snapshot(incident_id).id)

        inc = db.q1("SELECT * FROM incident WHERE id=?", incident_id)
        if inc is None:
            raise ValueError(f"unknown incident: {incident_id}")
        taken_at = db.now_iso()
        items = []
        for ev_id in db.jload(inc["evidence_ids"], []) or []:
            row = db.q1("SELECT * FROM evidence WHERE id=?", ev_id)
            if row is not None:
                items.append(json.loads(ev_mod.as_full(row, at=taken_at).model_dump_json()))
        body = {
            "incident_id": incident_id,
            "taken_at": taken_at,
            "evidence": items,
            "unknowns": [],
            "incident": {
                "id": inc["id"], "title": inc["title"], "severity": inc["severity"],
                "incident_class": inc["incident_class"], "state": inc["state"],
                "opened_at": inc["opened_at"], "detector": inc["detector"],
                "asset_ids": db.jload(inc["asset_ids"], []),
            },
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        snap_id = db.new_id("snap")
        db.run(
            "INSERT INTO evidence_snapshot(id,incident_id,taken_at,evidence_ids,"
            "snapshot_hash,body) VALUES(?,?,?,?,?,?)",
            snap_id, incident_id, taken_at,
            db.jdump([i["id"] for i in items]),
            hashlib.sha256(canonical.encode()).hexdigest(), canonical,
        )
        return cls.load(snap_id)


def _epoch(iso: str) -> float:
    try:
        return db.parse_iso(iso).timestamp()
    except (ValueError, AttributeError):
        return 0.0


# ------------------------------------------------------------- run context
@dataclass(frozen=True)
class RunContext:
    workflow_id: str
    tenant_id: str
    incident_id: str
    snapshot: Snapshot
    principal_id: str = "agent"
    jurisdiction: str = "unknown"
    tool_catalogue: tuple[Mapping[str, Any], ...] = ()

    @property
    def tool_ids(self) -> tuple[str, ...]:
        return tuple(str(t["id"]) for t in self.tool_catalogue)


# ------------------------------------------------------------------ claims
class ClaimDraft(BaseModel):
    """What an agent proposes to say. Not yet a claim - it must pass the gate."""

    statement: str
    claim_class: str
    subject: str = ""
    predicate: str = ""
    object: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence_basis: str | None = None
    uncertainty: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentResult:
    agent_id: str
    agent_version: str
    run_id: str
    status: str
    output: dict[str, Any]
    claim_ids: tuple[str, ...]
    dropped_claims: tuple[Mapping[str, Any], ...]
    degraded: bool
    prompt_version: str
    model_version: str
    snapshot_id: str
    elapsed_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id, "agent_version": self.agent_version,
            "run_id": self.run_id, "status": self.status, "output": self.output,
            "claim_ids": list(self.claim_ids),
            "dropped_claims": [dict(d) for d in self.dropped_claims],
            "degraded": self.degraded, "prompt_version": self.prompt_version,
            "model_version": self.model_version, "snapshot_id": self.snapshot_id,
        }

    def replayable(self) -> dict[str, Any]:
        """The part that must be identical across two replays of one snapshot."""
        return {
            "agent_id": self.agent_id, "agent_version": self.agent_version,
            "status": self.status, "output": self.output,
            "dropped_claims": [dict(d) for d in self.dropped_claims],
            "degraded": self.degraded, "prompt_version": self.prompt_version,
            "model_version": self.model_version,
        }


# --------------------------------------------------------------- the agent
class Agent:
    """Base runtime. Subclasses implement `_work` and nothing else."""

    spec: ClassVar[AgentSpec]

    def __init__(self) -> None:
        self._tool_calls = 0

    # ---- subclass hook ----------------------------------------------------
    def _work(self, ctx: RunContext) -> tuple[BaseModel, list[ClaimDraft], bool, str, str]:
        """Return (output_model, claim_drafts, degraded, prompt_version, model_version)."""
        raise NotImplementedError

    # ---- forbidden zone ---------------------------------------------------
    def call_tool(self, ctx: RunContext, tool_id: str, args: Mapping[str, Any]) -> Any:
        """The only door from an agent to an external effect - and it is shut.

        Every agent in this system is declared `writes=False` with an empty
        `allowed_tools`, so this refuses every tool id. The refusal is written
        to the audit ledger before it is raised: a blocked attempt is evidence,
        not a silent no-op.
        """
        if not self.spec.writes or tool_id not in self.spec.allowed_tools:
            audit.append(
                ctx.tenant_id, ctx.workflow_id, self.spec.id, "agent",
                KIND_FORBIDDEN_ZONE, ctx.incident_id,
                {"agent_id": self.spec.id, "tool_id": tool_id,
                 "allowed_tools": list(self.spec.allowed_tools),
                 "forbidden_zone": self.spec.forbidden},
            )
            raise ForbiddenZone(
                f"{self.spec.id} may not call {tool_id!r}: {self.spec.forbidden}"
            )
        if self._tool_calls >= self.spec.tool_call_budget:
            raise BudgetExceeded(
                f"{self.spec.id} exhausted its tool-call budget "
                f"({self.spec.tool_call_budget})"
            )
        self._tool_calls += 1
        # Unreachable while every agent is read-only. It used to call
        # `gateway.execute_for_agent`, which does not exist - so the day an
        # agent was given a tool, this would have died with AttributeError
        # instead of refusing cleanly. Lane B executes PERSISTED actions
        # (`gateway.execute(action_id, ...)`); wiring an agent to it means
        # drafting an action row first, which is a deliberate design decision,
        # not something to improvise here.
        raise ForbiddenZone(
            f"{self.spec.id} is allowed {tool_id!r}, but no agent-side path to "
            f"Lane B is implemented; actions must be drafted and executed via "
            f"the gateway"
        )

    # ---- the run ----------------------------------------------------------
    def run(self, ctx: RunContext) -> AgentResult:
        started_at = db.now_iso()
        t0 = time.monotonic()
        self._tool_calls = 0
        audit.append(
            ctx.tenant_id, ctx.workflow_id, self.spec.id, "agent",
            KIND_AGENT_STARTED, ctx.incident_id,
            dict(self.spec.to_dict(), snapshot_id=ctx.snapshot.id,
                 snapshot_hash=ctx.snapshot.hash),
        )

        status, degraded = "ok", False
        prompt_version = model_version = ""
        drafts: list[ClaimDraft] = []
        output: dict[str, Any] = {}
        try:
            model, drafts, degraded, prompt_version, model_version = self._work(ctx)
            output = model.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - a failed agent must not fail the incident
            status = "error"
            output = {"error": f"{type(exc).__name__}: {exc}"}

        elapsed = time.monotonic() - t0
        # ponytail: cooperative budget check after the fact - Python cannot
        # preempt `_work`. Ceiling: a hung agent still blocks its caller.
        # Upgrade path: run `_work` in a thread with a join timeout if an
        # external tool ever makes the body genuinely unbounded.
        budget = runtime_budget_for(self.spec.runtime_budget_s)
        if elapsed > budget:
            status = "budget_exceeded"
            drafts = []
            output = dict(output, budget_note=(
                f"runtime {elapsed:.1f}s exceeded the {budget}s "
                f"budget; claims from this run were discarded"
            ))

        claim_ids, dropped = emit_claims(ctx, self.spec, drafts)
        run_id = _log_agent_run(
            ctx, self.spec, started_at, status, prompt_version, model_version,
            degraded, output, claim_ids,
        )
        audit.append(
            ctx.tenant_id, ctx.workflow_id, self.spec.id, "agent",
            KIND_AGENT_FINISHED, run_id,
            {"agent_id": self.spec.id, "status": status, "degraded": degraded,
             "claims_emitted": len(claim_ids), "claims_dropped": len(dropped),
             "prompt_version": prompt_version, "model_version": model_version,
             "snapshot_id": ctx.snapshot.id, "elapsed_s": round(elapsed, 3)},
        )
        return AgentResult(
            agent_id=self.spec.id, agent_version=self.spec.version, run_id=run_id,
            status=status, output=output, claim_ids=tuple(claim_ids),
            dropped_claims=tuple(dropped), degraded=degraded,
            prompt_version=prompt_version, model_version=model_version,
            snapshot_id=ctx.snapshot.id, elapsed_s=elapsed,
        )


# ------------------------------------------------------- grounding gate
def check_grounding(draft: ClaimDraft, snapshot: Snapshot) -> str | None:
    """Return a drop reason, or None if the draft may become a claim."""
    if draft.claim_class in GROUNDED_CLASSES and not draft.evidence_ids:
        return "ungrounded: a fact or forecast with no evidence id (invariant 1)"
    unknown = [e for e in draft.evidence_ids if e not in snapshot.evidence_ids]
    if unknown:
        return (f"cites evidence not in snapshot {snapshot.id}: "
                f"{', '.join(sorted(unknown))} - id was invented or is stale")
    if not draft.statement.strip():
        return "empty statement"
    return None


def emit_claims(
    ctx: RunContext, spec: AgentSpec, drafts: Sequence[ClaimDraft]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Push drafts through the gate. Survivors become claims; the rest are
    dropped and recorded. A dropped statement is NEVER returned to a caller,
    so it cannot reach a UI by accident."""
    kept: list[str] = []
    dropped: list[dict[str, Any]] = []

    def drop(draft: ClaimDraft, reason: str) -> None:
        record = {"agent_id": spec.id, "reason": reason,
                  "claim_class": draft.claim_class,
                  "evidence_ids": list(draft.evidence_ids),
                  "statement_hash": hashlib.sha256(
                      draft.statement.encode("utf-8")).hexdigest()[:16]}
        dropped.append(record)
        audit.append(
            ctx.tenant_id, ctx.workflow_id, spec.id, "agent",
            KIND_CLAIM_DROPPED, ctx.incident_id,
            dict(record, snapshot_id=ctx.snapshot.id, surfaced=False),
        )

    for draft in drafts:
        reason = check_grounding(draft, ctx.snapshot)
        if reason:
            drop(draft, reason)
            continue
        try:
            claim = claims.create_claim(
                tenant_id=ctx.tenant_id, statement=draft.statement,
                subject=draft.subject or spec.scope,
                predicate=draft.predicate or "asserts",
                object=draft.object, claim_class=draft.claim_class,
                evidence_ids=list(draft.evidence_ids), author=spec.id,
                author_kind="agent", incident_id=ctx.incident_id,
                confidence_basis=draft.confidence_basis,
                uncertainty=draft.uncertainty, workflow_id=ctx.workflow_id,
            )
        except ValueError as exc:
            # core/claims.py is the server-side authority and it said no.
            drop(draft, f"rejected by core/claims.py: {exc}")
            continue
        kept.append(claim.id)
    return kept, dropped


def unsupported_claim_rate(workflow_id: str | None = None) -> float:
    """Measured, not aspirational. Feeds `/v1/metrics/ops`.

    dropped / (created + dropped) over the hash-chained audit ledger. Zero here
    means zero ungrounded statements reached a surface, and the ledger proves it.
    """
    where, args = ("AND workflow_id=?", (workflow_id,)) if workflow_id else ("", ())
    rows = db.q(
        "SELECT kind, COUNT(*) AS n FROM audit_event "
        f"WHERE kind IN ('claim.created', ?) {where} GROUP BY kind",
        KIND_CLAIM_DROPPED, *args,
    )
    counts = {r["kind"]: int(r["n"]) for r in rows}
    created = counts.get("claim.created", 0)
    dropped = counts.get(KIND_CLAIM_DROPPED, 0)
    total = created + dropped
    return round(dropped / total, 6) if total else 0.0


# ------------------------------------------------------- shared prompt bits
# Fields worth putting in front of a model. `integrity_hash`, geometry and
# provenance chains are deliberately left out: they are noise in a prompt and
# hex digests trip the PII redactor.
_PROMPT_EVIDENCE_FIELDS = (
    "id", "source", "trust_tier", "observed_at", "age_s", "fresh",
    "evidence_class", "status", "statement", "value", "expires_at",
)


def prompt_evidence(snapshot: Snapshot) -> list[dict[str, Any]]:
    return [
        {k: e[k] for k in _PROMPT_EVIDENCE_FIELDS if k in e}
        for e in snapshot.evidence
    ]


def positions(snapshot: Snapshot, agent_id: str) -> list[dict[str, Any]]:
    """Every numeric reading in the snapshot, one entry per SOURCE.

    This is the coordinator's arbitration input, and it is derived from the
    snapshot by code - never from model text - so two sources disagreeing about
    one subject always surfaces as two positions, never as one blended number.
    """
    out: list[dict[str, Any]] = []
    for e in snapshot.evidence:
        val = (e.get("value") or {})
        if not isinstance(val.get("value"), (int, float)) or e.get("status") != "valid":
            continue
        out.append({
            "agent_id": agent_id,
            "subject": val.get("subject") or val.get("metric", "unknown"),
            "metric": val.get("metric", "unknown"),
            "value": float(val["value"]),
            "unit": val.get("unit", ""),
            "evidence_id": e["id"],
            "source": e.get("source", "unknown"),
            "trust_tier": e.get("trust_tier", "unknown"),
            "observed_at": e.get("observed_at", ""),
        })
    return sorted(out, key=lambda p: (p["subject"], p["evidence_id"]))


def prompt_vars(ctx: RunContext, spec: AgentSpec, schema: Mapping[str, Any],
                **extra: Any) -> dict[str, Any]:
    """The twelve-requirement context block, filled from the frozen snapshot.

    `now` is the SNAPSHOT time, not wall clock: an agent must reason about the
    instant it was given, and replaying tomorrow must not change the answer.
    """
    from services.api.core import policy

    return {
        "task_id": f"{ctx.workflow_id}:{spec.id}",
        "jurisdiction": ctx.jurisdiction,
        "incident_id": ctx.incident_id,
        "snapshot_id": ctx.snapshot.id,
        "snapshot_hash": ctx.snapshot.hash,
        "now": ctx.snapshot.taken_at,
        "evidence_json": prompt_evidence(ctx.snapshot),
        "unknowns_json": list(ctx.snapshot.unknowns),
        "tools_json": [dict(t) for t in ctx.tool_catalogue],
        "output_schema": dict(schema),
        "policy_reference": getattr(policy, "ACTIVE_VERSION", "unknown"),
        **extra,
    }


def _log_agent_run(
    ctx: RunContext, spec: AgentSpec, started_at: str, status: str,
    prompt_version: str, model_version: str, degraded: bool,
    output: Mapping[str, Any], claim_ids: Sequence[str],
) -> str:
    """The agent's own run row. Token and cost columns stay zero here: LLM spend
    is attributed to the gateway's rows, so summing a workflow never double
    counts."""
    run_id = db.new_id("ar")
    db.run(
        "INSERT INTO agent_run(id,tenant_id,workflow_id,agent_id,incident_id,"
        "prompt_template,prompt_version,model_version,evidence_snapshot_id,"
        "started_at,ended_at,status,tokens_in,tokens_out,cost_usd,degraded,"
        "output,claim_ids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?,?)",
        run_id, ctx.tenant_id, ctx.workflow_id, spec.id, ctx.incident_id,
        spec.template, prompt_version, model_version or "n/a", ctx.snapshot.id,
        started_at, db.now_iso(), status, int(degraded),
        db.jdump(dict(output)), db.jdump(list(claim_ids)),
    )
    return run_id
