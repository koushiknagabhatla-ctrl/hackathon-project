"""Planning agent: drafts candidate actions from a handed tool catalogue.

FORBIDDEN ZONE, enforced in code: an action naming a tool outside the catalogue
this agent was handed is DROPPED before it reaches a plan, and the drop is
logged as `plan.action_dropped_out_of_catalogue`.

The filter runs on the PARSED MODEL OUTPUT, unconditionally, after the model
has spoken. It does not consult the prompt, the sanitiser or any flag. That
ordering is the whole point: if the context firewall were removed entirely and
an injected citizen report talked the model into emitting
`publish_public_alert`, the tool id would still not be in the catalogue, the
action would still be dropped here, and the attempt would still be on the
hash-chained ledger. Prompt text asks; this function decides.

Nothing here executes. A draft action becomes an `action` row, is risk-tiered by
`core/risk.py`, evaluated by `core/policy.py`, approved by a human where
required, and only then executed by `core/gateway.py`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from services.api.core import audit

from . import base, llm_gateway
from .base import AgentSpec, ClaimDraft, RunContext

SPEC = AgentSpec(
    id="planning-agent",
    version="1.0.0",
    owner="ops.response-planning",
    scope="draft candidate response plans from the allowed tool catalogue",
    forbidden=(
        "may not execute anything; may not name a tool outside the catalogue "
        "it was handed; may not invent an asset id or an argument value"
    ),
    template="planning",
    allowed_domains=("plan", "action"),
    allowed_tools=(),          # it DRAFTS actions; it never calls a tool
    runtime_budget_s=25.0,
    tool_call_budget=0,
    writes=False,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "posture": {"type": "string"},
                    "rationale": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_id": {"type": "string"},
                                "intent": {"type": "string"},
                                "args": {"type": "object"},
                                "target_asset_id": {"type": "string"},
                            },
                            "required": ["tool_id", "intent", "args"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "posture", "rationale", "evidence_ids", "actions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

RISK_ORDER = ("R0", "R1", "R2", "R3", "R4", "R5")


class PlanningOutput(BaseModel):
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    dropped_actions: list[dict[str, Any]] = Field(default_factory=list)
    catalogue_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------- catalogue filter
def filter_candidates(
    ctx: RunContext, candidates: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop every action the catalogue does not authorise. Log every drop.

    This is a trust boundary, not a validation nicety. It runs whatever the
    model said, whatever the prompt said, and whatever any evidence field said.
    """
    catalogue = {str(t["id"]): t for t in ctx.tool_catalogue}
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    def log(reason: str, detail: dict[str, Any]) -> None:
        record = dict(detail, reason=reason, agent_id=SPEC.id)
        dropped.append(record)
        audit.append(
            ctx.tenant_id, ctx.workflow_id, SPEC.id, "agent",
            base.KIND_TOOL_DROPPED, ctx.incident_id,
            dict(record, catalogue=sorted(catalogue), snapshot_id=ctx.snapshot.id,
                 reached_plan=False),
        )

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        actions: list[dict[str, Any]] = []
        for raw in cand.get("actions") or []:
            if not isinstance(raw, dict):
                continue
            tool_id = str(raw.get("tool_id", ""))
            manifest = catalogue.get(tool_id)
            if manifest is None:
                log("tool_not_in_catalogue",
                    {"tool_id": tool_id, "candidate": str(cand.get("title", "")),
                     "intent": str(raw.get("intent", ""))[:200]})
                continue
            allowed_keys = set(
                (manifest.get("input_schema") or {}).get("properties", {})
            )
            args = {k: v for k, v in (raw.get("args") or {}).items()
                    if k in allowed_keys}
            stripped = sorted(set(raw.get("args") or {}) - allowed_keys)
            if stripped:
                log("args_not_in_tool_schema",
                    {"tool_id": tool_id, "stripped_args": stripped,
                     "candidate": str(cand.get("title", ""))})
            actions.append({
                "tool_id": tool_id,
                "intent": str(raw.get("intent", "")),
                "args": args,
                "target_asset_id": raw.get("target_asset_id") or _default_asset(ctx),
                "sequence": len(actions) + 1,
                "risk_class": manifest.get("risk_class", "R3"),
                "reversible": bool(manifest.get("rollback_tool_id")),
                "rollback_tool_id": manifest.get("rollback_tool_id"),
                "verification_method": manifest.get("verification_method", "read_back"),
                "missing_args": sorted(
                    set((manifest.get("input_schema") or {}).get("required", []))
                    - set(args)
                ),
            })
        kept.append(dict(cand, actions=actions))
    return kept, dropped


def _default_asset(ctx: RunContext) -> str | None:
    assets = list(ctx.snapshot.incident.get("asset_ids") or [])
    return str(assets[0]) if assets else None


# ------------------------------------------------------- deterministic path
def _rank(manifest: dict[str, Any]) -> tuple[int, str]:
    risk = str(manifest.get("risk_class", "R3"))
    idx = RISK_ORDER.index(risk) if risk in RISK_ORDER else len(RISK_ORDER)
    return idx, str(manifest.get("id"))


def _args_from_context(manifest: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    """Fill required args from CONTEXT WE ACTUALLY HAVE. Never invents a value:
    an argument with no source is left out and surfaces as `missing_args`."""
    known = {
        "incident_id": variables.get("incident_id"),
        "asset_id": variables.get("asset_id"),
        "target_asset_id": variables.get("asset_id"),
        "evidence_ids": variables.get("evidence_ids"),
        "reason": variables.get("reason"),
        "rationale": variables.get("reason"),
        "message": variables.get("reason"),
        "note": variables.get("reason"),
    }
    schema = (manifest.get("input_schema") or {}).get("properties", {})
    return {k: known[k] for k in schema if known.get(k) is not None}


def deterministic(variables: dict[str, Any]) -> dict[str, Any]:
    """Two genuinely different postures, built from the catalogue offline."""
    catalogue = sorted(
        (dict(t) for t in (variables.get("tools_json") or [])), key=_rank
    )
    fc = (variables.get("forecast_json") or {})
    depth = ((fc.get("flood") or {}).get("median"))
    horizon = ((fc.get("flood") or {}).get("horizon_min"))
    evidence_ids = [e["id"] for e in (variables.get("evidence_json") or [])]
    ctxvals = {
        "incident_id": variables.get("incident_id"),
        "asset_id": variables.get("asset_id"),
        "evidence_ids": evidence_ids,
        "reason": (
            f"Incident {variables.get('incident_id')}: projected flood depth "
            f"{depth:.2f} m at +{horizon} min." if isinstance(depth, (int, float))
            else f"Incident {variables.get('incident_id')}: forecast unavailable, "
                 f"acting on verified present state only."
        ),
    }

    def act(m: dict[str, Any], intent: str) -> dict[str, Any]:
        return {"tool_id": m["id"], "intent": intent,
                "args": _args_from_context(m, ctxvals)}

    if not catalogue:
        empty = (
            "No tool in this jurisdiction's catalogue can affect this incident, "
            "so no action can be drafted. Escalate to a human with authority to "
            "register or authorise one."
        )
        return {"candidates": [
            {"title": "No authorised action available", "posture": "escalate",
             "rationale": empty, "evidence_ids": evidence_ids, "actions": []},
            {"title": "Monitor and re-assess", "posture": "monitor",
             "rationale": empty + " Continue to observe and re-assess when the "
                                  "evidence set changes.",
             "evidence_ids": evidence_ids, "actions": []},
        ]}

    containment = catalogue[:3]
    minimal = catalogue[:1]
    depth_txt = (f"{depth:.2f} m at +{horizon} min" if isinstance(depth, (int, float))
                 else "an unavailable forecast")

    return {"candidates": [
        {
            "title": "Contain early",
            "posture": "containment",
            "rationale": (
                f"Acts now on {depth_txt}, accepting a wider blast radius to cut "
                f"exposure time. Uses {len(containment)} action(s), lowest risk "
                f"class first ({', '.join(m['id'] for m in containment)}), so the "
                f"reversible steps land before anything needing approval. Costs "
                f"more disruption than waiting, and commits before the next "
                f"observation could contradict the forecast."
            ),
            "evidence_ids": evidence_ids,
            "actions": [
                act(m, f"Containment step {i}: {m.get('description', m['id'])}")
                for i, m in enumerate(containment, 1)
            ],
        },
        {
            "title": "Minimal intervention",
            "posture": "minimal-intervention",
            "rationale": (
                f"Takes the single lowest-risk reversible step "
                f"({minimal[0]['id']}) and waits for the next observation before "
                f"committing further. Keeps disruption and approval burden at a "
                f"minimum and preserves optionality if {depth_txt} proves "
                f"pessimistic. Costs exposure time if it proves optimistic."
            ),
            "evidence_ids": evidence_ids,
            "actions": [
                act(minimal[0], f"Minimal step: {minimal[0].get('description', '')}")
            ],
        },
    ]}


# ------------------------------------------------------------------- agent
class PlanningAgent(base.Agent):
    spec = SPEC

    def __init__(self, situation: dict[str, Any] | None = None,
                 forecast: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.situation = dict(situation or {})
        self.forecast = dict(forecast or {})

    def _work(self, ctx: RunContext):
        variables = base.prompt_vars(
            ctx, SPEC, SCHEMA,
            asset_id=_default_asset(ctx),
            situation_json=self.situation,
            forecast_json=self.forecast,
        )
        res = llm_gateway.complete(
            ctx.workflow_id, SPEC.id, SPEC.template, variables, SCHEMA,
            fallback=deterministic, tenant_id=ctx.tenant_id,
            incident_id=ctx.incident_id, snapshot_id=ctx.snapshot.id,
            max_tokens=2000,
        )

        raw = [c for c in res.parsed.get("candidates", []) if isinstance(c, dict)]
        candidates, dropped = filter_candidates(ctx, raw)

        out = PlanningOutput(
            candidates=candidates, dropped_actions=dropped,
            catalogue_ids=list(ctx.tool_ids),
        )
        drafts = [
            ClaimDraft(
                statement=(
                    f"Candidate plan '{c.get('title')}' ({c.get('posture')}): "
                    f"{c.get('rationale')}"
                ),
                claim_class="recommendation", subject=ctx.incident_id,
                predicate="proposes_plan", object=str(c.get("title", ""))[:120],
                evidence_ids=[
                    e for e in (c.get("evidence_ids") or [])
                    if e in ctx.snapshot.evidence_ids
                ],
                confidence_basis=(
                    f"drafted from tool catalogue {sorted(ctx.tool_ids)}; "
                    f"{len(dropped)} action(s) dropped as unauthorised"
                ),
            )
            for c in candidates
        ]
        return out, drafts, res.degraded, res.prompt_version, res.model_version
