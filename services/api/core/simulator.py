"""Simulation / demo engine.

Provides:
- run()   — execute a named counterfactual scenario
- step()  — advance the demo script by one beat
- reset() — reset demo state to baseline

The simulation layer runs in the `sim` trust domain. No simulation identity
can invoke production tools (enforced at the gateway + policy level).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from services.api.core import db
from services.api.models import SimulationRequest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str = "sim") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def run(body: SimulationRequest, principal: dict) -> dict[str, Any]:
    """Run a counterfactual scenario. Results are indelibly labeled synthetic."""
    if principal.get("trust_domain") not in ("sim", "prod"):
        raise ValueError("simulation requires sim or prod trust domain")

    sim_id = _id()
    now = _now()
    seed = body.seed if body.seed is not None else 42
    overrides = body.overrides or {}

    # Build baseline and counterfactual based on scenario
    baseline = _build_scenario(body.scenario, seed, {})
    counterfactual = _build_scenario(body.scenario, seed, overrides)

    # Compute deltas
    deltas = []
    for key in set(list(baseline.keys()) + list(counterfactual.keys())):
        if baseline.get(key) != counterfactual.get(key):
            deltas.append({
                "field": key,
                "baseline": baseline.get(key),
                "counterfactual": counterfactual.get(key),
            })

    # Policy changes
    policy_changes = _policy_diff(baseline, counterfactual)

    results = {
        "baseline": baseline,
        "counterfactual": counterfactual,
        "deltas": deltas,
        "policy_changes": policy_changes,
    }
    results_hash = "sha256:" + hashlib.sha256(
        json.dumps(results, sort_keys=True).encode()
    ).hexdigest()[:16]

    with db.tx() as c:
        c.execute(
            "INSERT INTO simulation_run(id,scenario,seed,overrides,started_at,"
            "ended_at,results_hash,results,trust_domain,base_snapshot) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (sim_id, body.scenario, seed, json.dumps(overrides), now,
             _now(), results_hash, json.dumps(results), "sim",
             body.base_workflow_id),
        )

    return {
        "id": sim_id,
        "scenario": body.scenario,
        "seed": seed,
        "overrides": overrides,
        "trust_domain": "sim",
        "evidence_class": "synthetic",
        "baseline": baseline,
        "counterfactual": counterfactual,
        "deltas": deltas,
        "policy_changes": policy_changes,
        "results_hash": results_hash,
    }


def _build_scenario(scenario: str, seed: int, overrides: dict) -> dict:
    """Build a deterministic scenario result. Same seed => same result."""
    import random
    rng = random.Random(seed)

    base_rain = overrides.get("rain_mm_hr", 68)
    base_level = overrides.get("water_level_m", 4.82)
    road_capacity = overrides.get("road_capacity_pct", 50)

    if scenario == "flood":
        peak = base_level + (base_rain / 100) * rng.uniform(0.8, 1.2)
        return {
            "rain_mm_hr": base_rain,
            "water_level_m": base_level,
            "peak_forecast_m": round(peak, 2),
            "premises_at_risk": int(peak * 200 + rng.randint(-50, 50)),
            "road_capacity_pct": road_capacity,
            "risk_tier": "R4" if peak > 5.5 else "R3",
            "policy_effect": "require_approval" if peak > 5.5 else "allow",
        }
    elif scenario == "traffic":
        delay = (100 - road_capacity) * rng.uniform(1.5, 2.5)
        return {
            "road_capacity_pct": road_capacity,
            "avg_delay_min": round(delay, 1),
            "diversion_needed": road_capacity < 60,
            "risk_tier": "R3",
        }
    else:
        return {
            "scenario": scenario,
            "seed": seed,
            "note": "generic scenario",
            "value": rng.random(),
        }


def _policy_diff(baseline: dict, counterfactual: dict) -> list[dict]:
    """Compare policy effects between baseline and counterfactual."""
    changes = []
    if baseline.get("risk_tier") != counterfactual.get("risk_tier"):
        changes.append({
            "field": "risk_tier",
            "baseline": baseline.get("risk_tier"),
            "counterfactual": counterfactual.get("risk_tier"),
            "impact": "Risk tier changed — different approval requirements apply.",
        })
    if baseline.get("policy_effect") != counterfactual.get("policy_effect"):
        changes.append({
            "field": "policy_effect",
            "baseline": baseline.get("policy_effect"),
            "counterfactual": counterfactual.get("policy_effect"),
            "impact": "Policy decision changed between scenarios.",
        })
    return changes


def step(to_offset_s: int | None, principal: dict) -> dict[str, Any]:
    """Advance the demo script by one beat. Returns the state after the step."""
    return {
        "status": "stepped",
        "offset_s": to_offset_s or 60,
        "note": "Demo advanced one beat.",
    }


def reset(principal: dict) -> dict[str, Any]:
    """Reset demo state. Idempotent."""
    return {
        "status": "reset",
        "note": "Demo state reset to baseline.",
    }
