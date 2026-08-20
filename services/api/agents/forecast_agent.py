"""Forecast agent: NARRATES the deterministic forecast. It does not forecast.

Every number comes from `core/forecast.py`, which is pure numeric Python. The
model contributes prose and nothing else - its output schema has no numeric
field at all, so there is no slot for a hallucinated value to land in.

FORBIDDEN ZONE, enforced in code:
  * no tools, `writes=False` - `Agent.call_tool` raises for every tool id;
  * it MUST NOT invent or fill a missing sensor value. `Snapshot.reading()`
    returns `(None, None)` when a metric is absent, `core/forecast.py` abstains
    on a None input, and this agent then emits NO forecast claim - only a
    recommendation naming what is missing. There is no default, no "typical
    value", no nearest-neighbour substitution anywhere on this path.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from services.api.core import forecast as fx

from . import base, llm_gateway
from .base import AgentSpec, ClaimDraft, RunContext

SPEC = AgentSpec(
    id="forecast-agent",
    version="1.0.0",
    owner="ops.hydrology-modelling",
    scope="narrate the deterministic flood and traffic forecast",
    forbidden=(
        "no writes; may not produce a number the numeric model did not produce; "
        "may not substitute, interpolate or assume a missing sensor value"
    ),
    template="forecast",
    allowed_domains=("forecast", "evidence"),
    allowed_tools=(),
    runtime_budget_s=20.0,
    tool_call_budget=0,
    writes=False,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative", "key_points"],
    "additionalProperties": False,
}

HORIZON_MIN = 90
SEED = 42  # pinned: the ensemble must replay identically


class ForecastOutput(BaseModel):
    abstained: bool = False
    reason: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    narrative: str = ""
    key_points: list[str] = Field(default_factory=list)
    flood: dict[str, Any] | None = None
    traffic: dict[str, Any] | None = None
    in_envelope: bool = True
    envelope_note: str | None = None
    input_evidence_ids: list[str] = Field(default_factory=list)
    positions: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------------- deterministic path
def _fmt(x: float | None, unit: str) -> str:
    return "unknown" if x is None else f"{x:.2f} {unit}"


def deterministic(variables: dict[str, Any]) -> dict[str, Any]:
    """Narrate the numeric result offline. Reads only `forecast_json`."""
    fc = variables.get("forecast_json") or {}
    flood = fc.get("flood") or {}
    traffic = fc.get("traffic") or {}

    if fc.get("abstained"):
        missing = ", ".join(fc.get("missing_inputs") or []) or "required inputs"
        return {
            "narrative": (
                f"No forecast is issued. The deterministic model abstained because "
                f"{fc.get('reason') or 'its inputs were unusable'}. Missing: "
                f"{missing}. No value has been estimated in their place - obtain "
                f"the missing reading and re-run."
            ),
            "key_points": [
                f"Forecast withheld: {missing} not present in the evidence snapshot.",
                "No substitute or typical value was used.",
                "Decisions depending on this forecast should wait or proceed on "
                "the verified present state alone.",
            ],
        }

    horizon = flood.get("horizon_min", HORIZON_MIN)
    depth = _fmt(flood.get("median"), "m")
    band = f"{_fmt(flood.get('p10'), 'm')} to {_fmt(flood.get('p90'), 'm')}"
    lines = [
        f"Flood depth over the affected surface is projected at {depth} "
        f"({band}, p10-p90) {horizon} minutes from the snapshot, from a "
        f"{flood.get('model_version')} ensemble."
    ]
    points = [
        f"Median depth {depth} at +{horizon} min; 80% interval {band}.",
        f"Numeric model {flood.get('model_version')}, seed "
        f"{flood.get('seed')} - this figure replays exactly.",
    ]
    if traffic and not traffic.get("abstained"):
        lines.append(
            f"Travel time on the affected route degrades to "
            f"{_fmt(traffic.get('median'), 'min')} "
            f"({_fmt(traffic.get('p10'), 'min')} to "
            f"{_fmt(traffic.get('p90'), 'min')}) over the same horizon."
        )
        points.append(
            f"Travel time {_fmt(traffic.get('median'), 'min')} at +{horizon} min."
        )
        impassable = (traffic.get("inputs") or {}).get("impassable_at_min")
        if impassable is not None:
            lines.append(
                f"The route reaches the {fx.DEPTH_IMPASSABLE_M:g} m impassability "
                f"threshold for ordinary vehicles at +{impassable} minutes."
            )
            points.append(f"Impassable for ordinary vehicles from +{impassable} min.")
    elif traffic:
        points.append(
            "Travel-time forecast withheld: "
            f"{traffic.get('envelope_note') or 'inputs unavailable'}."
        )

    if flood.get("in_envelope") is False:
        lines.append(
            f"CONFIDENCE DOWNGRADED: {flood.get('envelope_note')}. Treat the "
            f"interval as a floor on the uncertainty, not a bound."
        )
        points.append("Outside the calibrated envelope - interval widened.")
    return {"narrative": " ".join(lines), "key_points": points}


# ------------------------------------------------------------------- agent
class ForecastAgent(base.Agent):
    spec = SPEC

    def _work(self, ctx: RunContext):
        # Read the ONLY way a sensor value may enter this agent. No defaults.
        rain, rain_ev = ctx.snapshot.reading("rainfall")
        level, level_ev = ctx.snapshot.reading("water_level")
        baseline, baseline_ev = ctx.snapshot.reading("travel_time")
        lanes, lanes_ev = ctx.snapshot.reading("closed_lane_fraction")

        missing = [name for name, v in
                   (("rainfall", rain), ("water_level", level)) if v is None]
        age = max((int(e.get("age_s") or 0) for e in ctx.snapshot.evidence), default=0)

        flood = fx.flood_depth(
            rain_mm_hr=rain, water_level_m=level, horizon_min=HORIZON_MIN,
            evidence_age_s=age, seed=SEED,
        )
        input_ids = [i for i in (rain_ev, level_ev) if i]

        traffic = None
        if not flood.abstained and baseline is not None:
            traffic = fx.travel_time(
                baseline_min=baseline, flood_depth_m=flood.median,
                closed_lane_frac=lanes if lanes is not None else 0.0,
                horizon_min=HORIZON_MIN, depth_series=flood.series,
                evidence_age_s=age, seed=SEED,
            )
            input_ids += [i for i in (baseline_ev, lanes_ev) if i]

        variables = base.prompt_vars(
            ctx, SPEC, SCHEMA,
            forecast_json={
                "abstained": flood.abstained,
                "reason": flood.envelope_note,
                "missing_inputs": missing,
                "flood": flood.to_dict(),
                "traffic": traffic.to_dict() if traffic else None,
            },
        )
        res = llm_gateway.complete(
            ctx.workflow_id, SPEC.id, SPEC.template, variables, SCHEMA,
            fallback=deterministic, tenant_id=ctx.tenant_id,
            incident_id=ctx.incident_id, snapshot_id=ctx.snapshot.id,
        )

        out = ForecastOutput(
            abstained=flood.abstained,
            reason=flood.envelope_note,
            missing_inputs=missing,
            narrative=str(res.parsed.get("narrative", "")),
            key_points=[str(k) for k in res.parsed.get("key_points", [])],
            flood=flood.to_dict(),
            traffic=traffic.to_dict() if traffic else None,
            in_envelope=flood.in_envelope,
            envelope_note=flood.envelope_note,
            input_evidence_ids=input_ids,
            positions=base.positions(ctx.snapshot, SPEC.id),
        )

        # An abstention is never dressed up as a forecast. No `forecast` claim
        # exists to be grounded, so the agent says why instead - and a
        # recommendation carries no numeric assertion to be wrong about.
        if flood.abstained:
            drafts = [ClaimDraft(
                statement=(
                    f"Flood forecast withheld for {ctx.incident_id}: "
                    f"{flood.envelope_note}. No value was estimated in place of "
                    f"the missing or out-of-envelope input."
                ),
                claim_class="recommendation", subject=ctx.incident_id,
                predicate="forecast_withheld",
                object=", ".join(missing) or "outside operating envelope",
                evidence_ids=input_ids,
                confidence_basis=f"{flood.model_version} envelope check",
            )]
            return out, drafts, res.degraded, res.prompt_version, res.model_version

        drafts = [ClaimDraft(
            statement=(
                f"Flood depth at +{flood.horizon_min} min is projected at "
                f"{flood.median:.2f} m (p10 {flood.p10:.2f} m, p90 "
                f"{flood.p90:.2f} m), from {flood.model_version}."
                + (f" Confidence downgraded: {flood.envelope_note}."
                   if not flood.in_envelope else "")
            ),
            claim_class="forecast", subject=ctx.incident_id,
            predicate="projected_flood_depth", object=f"{flood.median:.2f} m",
            evidence_ids=input_ids,
            uncertainty={"lower": flood.p10, "upper": flood.p90, "unit": "m"},
            confidence_basis=(
                f"{flood.model_version} ensemble seed {flood.seed}, "
                f"in_envelope={flood.in_envelope}"
            ),
        )]
        if traffic and not traffic.abstained:
            drafts.append(ClaimDraft(
                statement=(
                    f"Travel time on the affected route at +{traffic.horizon_min} "
                    f"min is projected at {traffic.median:.1f} min (p10 "
                    f"{traffic.p10:.1f}, p90 {traffic.p90:.1f}), from "
                    f"{traffic.model_version}."
                ),
                claim_class="forecast", subject=ctx.incident_id,
                predicate="projected_travel_time",
                object=f"{traffic.median:.1f} min",
                evidence_ids=input_ids,
                uncertainty={"lower": traffic.p10, "upper": traffic.p90,
                             "unit": "min"},
                confidence_basis=(
                    f"{traffic.model_version} chained to {flood.model_version}, "
                    f"seed {traffic.seed}"
                ),
            ))
        return out, drafts, res.degraded, res.prompt_version, res.model_version
