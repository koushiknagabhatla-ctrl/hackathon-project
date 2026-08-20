"""The policy engine. Deterministic Python, outside the model (invariant 2).

`decide(ctx)` evaluates the active versioned bundle and ALWAYS writes a
policy_decision row carrying bundle_version, the full inputs and their hash,
so "what would policy say?" is replayable months later.

Nothing here imports from services/api/agents/**. Enforced by a test.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import pathlib

from services.api.models import PolicyDecision

from . import db

ACTIVE_VERSION = "3.0.7"

_POLICIES_DIR = pathlib.Path(
    os.environ.get("AURALIS_POLICIES_DIR")
    or pathlib.Path(__file__).resolve().parents[3] / "policies"
)


def canonical_json(obj) -> str:
    """The one canonical form. Used for inputs_hash and manifest signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def inputs_hash(inputs: dict) -> str:
    return hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=8)
def load_bundle(version: str = ACTIVE_VERSION):
    """Load policies/bundle_v<version>.py by path (the filename has dots)."""
    path = _POLICIES_DIR / f"bundle_v{version}.py"
    if not path.exists():
        raise FileNotFoundError(f"policy bundle v{version} not found at {path}")
    name = "auralis_policy_bundle_" + version.replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(ctx: dict) -> dict:
    """Keep only documented ctx keys, in canonical order.

    Args are deliberately excluded: no wording of a request can reach a rule.
    """
    bundle = load_bundle()
    return {k: ctx.get(k) for k in bundle.CTX_KEYS}


# ---------------------------------------------------------------- deciding
def _evaluate(inputs: dict, version: str) -> tuple[str, str, str]:
    return load_bundle(version).evaluate(inputs)


def decide(ctx: dict, *, subject_action_id: str | None = None,
           version: str = ACTIVE_VERSION) -> PolicyDecision:
    """Evaluate the active bundle and persist the decision. The only I/O."""
    inputs = normalize(ctx)
    effect, rule_id, reason = _evaluate(inputs, version)
    decision = PolicyDecision(
        id=db.new_id("pd"),
        bundle_version=version,
        inputs_hash=inputs_hash(inputs),
        inputs=inputs,
        effect=effect,
        rule_id=rule_id,
        reason=reason,
        decided_at=db.now_iso(),
        subject_action_id=subject_action_id or ctx.get("action_id"),
    )
    _persist(decision, ctx.get("tenant_id"), version)
    return decision


def replay(inputs: dict, bundle_version: str = ACTIVE_VERSION) -> PolicyDecision:
    """Counterfactual re-evaluation. Pure: writes nothing.

    Lane F's simulator calls this to answer "what would policy have said under
    bundle X / these inputs?" without polluting the decision log.
    """
    inputs = {k: inputs.get(k) for k in load_bundle(bundle_version).CTX_KEYS}
    effect, rule_id, reason = _evaluate(inputs, bundle_version)
    return PolicyDecision(
        id="pd_replay_" + inputs_hash(inputs)[:12],
        bundle_version=bundle_version,
        inputs_hash=inputs_hash(inputs),
        inputs=inputs,
        effect=effect,
        rule_id=rule_id,
        reason=reason,
        decided_at=db.now_iso(),
        subject_action_id=None,
    )


def explain(version: str = ACTIVE_VERSION) -> list[dict]:
    """The rule catalogue for the /governance screen."""
    b = load_bundle(version)
    return [{"id": r["id"], "description": r["description"],
             "applies_to": list(r["applies_to"])} for r in b.RULES]


# --------------------------------------------------------------- persistence
def _persist(d: PolicyDecision, tenant_id: str | None, version: str) -> None:
    if not tenant_id:
        raise ValueError("policy.decide requires ctx['tenant_id'] to log the decision")
    b = load_bundle(version)
    with db.tx() as c:  # re-entrant: joins the gateway's transaction when nested
        c.execute(
            "INSERT OR IGNORE INTO policy_bundle (id, version, rules_hash, activated_at,"
            " active, source) VALUES (?,?,?,?,?,?)",
            (f"pb_{version}", version, b.RULES_HASH, db.now_iso(),
             1 if version == ACTIVE_VERSION else 0, b.RULES_SOURCE))
        c.execute(
            "INSERT INTO policy_decision (id, tenant_id, bundle_version, inputs_hash, inputs,"
            " effect, rule_id, reason, decided_at, subject_action_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (d.id, tenant_id, d.bundle_version, d.inputs_hash, canonical_json(d.inputs),
             d.effect, d.rule_id, d.reason, d.decided_at, d.subject_action_id))
