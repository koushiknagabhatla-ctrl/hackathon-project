"""Risk tier is computed per action INSTANCE, never static per tool.

The same tool is R3 against a small reversible target and R4 when the target
is public-facing or the blast radius crosses the threshold. Pure, no I/O, no
imports from services/api/agents/**: a model cannot talk its way into a lower tier.
"""

from __future__ import annotations

TIER_ORDER = ("R0", "R1", "R2", "R3", "R4", "R5")

# Floor tier implied by what the action fundamentally is.
ACTION_CLASS_BASE = {
    "read": "R0",
    "compute": "R1",
    "forecast": "R1",
    "plan": "R2",
    "draft": "R2",
    "advisory": "R3",
    "advise": "R3",
    "workorder": "R3",
    "actuate": "R3",
    "notify_public": "R4",
    "isolate": "R4",
    "physical_control": "R5",
}

CRITICALITY_ESCALATE_AT = 4     # criticality >= this adds a tier
BLAST_ESCALATE_AT = 25          # dependent assets above this adds a tier
EVIDENCE_STALE_S = 900          # evidence older than this adds a tier

# Escalation can lift an action to R4 but never manufacture an R5. R5 is
# reserved for action classes that ARE direct physical control, and those are
# denied outright by the R5_PROHIBITED rule.
ESCALATION_CAP = "R4"


def _idx(tier: str) -> int:
    return TIER_ORDER.index(tier)


def compute_tier(
    action_class: str,
    asset_criticality: int = 0,
    blast_radius: int = 0,
    evidence_age_s: int | None = None,
    public_facing: bool = False,
    reversible: bool = True,
) -> tuple[str, dict]:
    """Return (RiskTier, inputs_dict).

    The inputs dict carries every input, the base tier and each escalation
    that fired, so the decision is explainable in the UI and replayable in
    the simulator without re-deriving anything.
    """
    base = ACTION_CLASS_BASE.get(action_class, "R3")  # unknown => treat as acting
    crit = int(asset_criticality or 0)
    blast = int(blast_radius or 0)
    age = None if evidence_age_s is None else int(evidence_age_s)

    escalations: list[dict] = []
    if crit >= CRITICALITY_ESCALATE_AT:
        escalations.append({"reason": "asset_criticality",
                            "detail": f"criticality {crit} >= {CRITICALITY_ESCALATE_AT}"})
    if blast > BLAST_ESCALATE_AT:
        escalations.append({"reason": "blast_radius",
                            "detail": f"{blast} dependent assets > {BLAST_ESCALATE_AT}"})
    if public_facing:
        escalations.append({"reason": "public_facing",
                            "detail": "effect is visible to the public"})
    if not reversible:
        escalations.append({"reason": "irreversible",
                            "detail": "no automatic rollback path"})
    if age is not None and age > EVIDENCE_STALE_S:
        escalations.append({"reason": "stale_evidence",
                            "detail": f"evidence {age}s old > {EVIDENCE_STALE_S}s"})

    if base == "R5":
        tier = "R5"  # physical control never de-escalates and never escalates
    else:
        raised = min(_idx(base) + len(escalations), _idx(ESCALATION_CAP))
        tier = TIER_ORDER[max(raised, _idx(base))]

    inputs = {
        "action_class": action_class,
        "asset_criticality": crit,
        "blast_radius": blast,
        "evidence_age_s": age,
        "public_facing": bool(public_facing),
        "reversible": bool(reversible),
        "base_tier": base,
        "escalations": escalations,
        "escalation_cap": ESCALATION_CAP,
        "risk_tier": tier,
    }
    return tier, inputs


def max_tier(a: str, b: str) -> str:
    return a if _idx(a) >= _idx(b) else b
