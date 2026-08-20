"""Situation agent: summarise VERIFIED state, list what is still unknown.

FORBIDDEN ZONE, enforced in code: this agent has no tools and `writes=False`,
so `Agent.call_tool` raises `ForbiddenZone` for every tool id, including one the
model was persuaded to ask for. It reads the frozen snapshot and returns text.
It cannot mutate an asset, publish anything, or reach the network.

The model writes PROSE. Every claim comes from a `verified_state` entry that
cites evidence ids, and every entry is checked against the snapshot before it
becomes a claim - so a fluent sentence with no citation is dropped, not shown.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from . import base, llm_gateway
from .base import AgentSpec, ClaimDraft, RunContext

SPEC = AgentSpec(
    id="situation-agent",
    version="1.0.0",
    owner="ops.situational-awareness",
    scope="verified incident state and explicit unknowns",
    forbidden="no writes: no tools, no external effect, no action proposals",
    template="situation",
    allowed_domains=("incident", "evidence"),
    allowed_tools=(),
    runtime_budget_s=20.0,
    tool_call_budget=0,
    writes=False,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "verified_state": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["statement", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "verified_state", "unknowns"],
    "additionalProperties": False,
}


class SituationOutput(BaseModel):
    summary: str
    verified_state: list[dict[str, Any]] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    positions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


# ------------------------------------------------------- deterministic path
def _describe(item: dict[str, Any]) -> str:
    val = item.get("value") or {}
    v, unit = val.get("value"), val.get("unit", "")
    metric = (val.get("metric") or "state").replace("_", " ")
    where = val.get("ref") or item.get("source", "unknown source")
    amount = f"{v:g} {unit}".strip() if isinstance(v, (int, float)) else str(
        item.get("statement", "reported")
    )
    tag = " (SYNTHETIC, simulated)" if item.get("evidence_class") == "synthetic" else ""
    return (
        f"{metric.capitalize()} at {where} is {amount}, per {item.get('source')} "
        f"({item.get('trust_tier')} tier, observed {item.get('observed_at')}, "
        f"{item.get('age_s', 0)}s before this snapshot){tag}."
    )


def deterministic(variables: dict[str, Any]) -> dict[str, Any]:
    """The offline generator. This is the demo's primary path, so it has to read
    like something a duty officer would accept, not like a placeholder."""
    items = list(variables.get("evidence_json") or [])
    valid = [e for e in items if e.get("status") == "valid"]
    stale = [e for e in valid if e.get("fresh") is False]
    synthetic = [e for e in valid if e.get("evidence_class") == "synthetic"]
    sources = sorted({str(e.get("source")) for e in valid})
    tiers = sorted({str(e.get("trust_tier")) for e in valid})

    verified = [
        {"statement": _describe(e), "evidence_ids": [e["id"]]} for e in valid
    ]

    if valid:
        oldest = max(int(e.get("age_s") or 0) for e in valid)
        summary = (
            f"{len(valid)} verified observation(s) from {len(sources)} source(s) "
            f"({', '.join(sources)}; trust tiers: {', '.join(tiers)}). "
            f"The oldest input is {oldest}s old at snapshot time "
            f"{variables.get('now')}. "
        )
        if stale:
            summary += (
                f"{len(stale)} item(s) are past their freshness SLA and should be "
                f"treated as indicative only. "
            )
        if synthetic:
            summary += (
                f"{len(synthetic)} item(s) are SYNTHETIC and are labelled as "
                f"simulated wherever they appear. "
            )
        summary += "Nothing outside this list is established state."
    else:
        summary = (
            "No valid evidence is attached to this incident at snapshot time "
            f"{variables.get('now')}. Nothing can be stated about current state."
        )

    unknowns = list(variables.get("unknowns_json") or [])
    if not valid:
        unknowns.append("Every aspect of current state: the snapshot is empty.")
    metrics = {(e.get("value") or {}).get("metric") for e in valid}
    for needed, why in (
        ("rainfall", "rainfall rate, needed by the flood forecast"),
        ("water_level", "water level, needed by the flood forecast"),
    ):
        if needed not in metrics:
            unknowns.append(f"No evidence for {why}.")
    for e in stale:
        unknowns.append(
            f"Whether {e.get('source')} is still reporting: its last observation "
            f"({e['id']}) is {e.get('age_s')}s old and past its SLA."
        )
    singles = sorted({
        m for m in metrics if m and
        len([e for e in valid if (e.get("value") or {}).get("metric") == m]) == 1
    })
    for m in singles:
        unknowns.append(f"No corroborating second source for {m}.")

    return {"summary": summary, "verified_state": verified, "unknowns": unknowns}


class SituationAgent(base.Agent):
    spec = SPEC

    def _work(self, ctx: RunContext):
        variables = base.prompt_vars(ctx, SPEC, SCHEMA)
        res = llm_gateway.complete(
            ctx.workflow_id, SPEC.id, SPEC.template, variables, SCHEMA,
            fallback=deterministic, tenant_id=ctx.tenant_id,
            incident_id=ctx.incident_id, snapshot_id=ctx.snapshot.id,
        )
        parsed = res.parsed
        entries = [e for e in parsed.get("verified_state", []) if isinstance(e, dict)]
        drafts = [
            ClaimDraft(
                statement=str(e.get("statement", "")),
                claim_class="fact",
                subject=_subject_for(ctx, e.get("evidence_ids") or []),
                predicate="observed_state",
                object=str(e.get("statement", ""))[:120],
                evidence_ids=[str(i) for i in (e.get("evidence_ids") or [])],
                confidence_basis=(
                    f"verified evidence in snapshot {ctx.snapshot.id}"
                ),
            )
            for e in entries
        ]
        out = SituationOutput(
            summary=str(parsed.get("summary", "")),
            verified_state=entries,
            unknowns=[str(u) for u in parsed.get("unknowns", [])],
            positions=base.positions(ctx.snapshot, SPEC.id),
            evidence_ids=list(ctx.snapshot.evidence_ids),
        )
        return out, drafts, res.degraded, res.prompt_version, res.model_version


def _subject_for(ctx: RunContext, evidence_ids: list[Any]) -> str:
    for ev_id in evidence_ids:
        item = ctx.snapshot.get(str(ev_id))
        if item:
            val = item.get("value") or {}
            if val.get("subject"):
                return str(val["subject"])
    return ctx.incident_id
