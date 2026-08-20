"""Auralis policy bundle v3.0.7 - plain data + pure functions.

This file IS the policy. It is versioned, hashed (RULES_HASH) and never
imports anything under services/api/agents/**: no model output can change a
policy outcome, only the evidence and the action instance can (invariant 2).

A rule is a plain dict:
    {"id", "description", "applies_to", "check": (ctx) -> (effect, reason)}

`effect` is one of "allow" | "deny" | "require_approval". "allow" from a
single rule means only "this rule has no objection".

`ctx` is a flat JSON-serialisable dict so a decision is hashable, loggable
and replayable verbatim. Keys are documented in CTX_KEYS below.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import pathlib

VERSION = "3.0.7"

# ------------------------------------------------------------------ tables
TIER_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
ALL_TIERS = ("R0", "R1", "R2", "R3", "R4", "R5")
ACTING_TIERS = ("R3", "R4", "R5")
HIGH_TIERS = ("R4", "R5")

# The "never build direct equipment control" line. Registered tools that land
# here are refused visibly by the policy engine rather than quietly omitted.
PROHIBITED_TOOLS = frozenset({"scada.direct_control"})
PROHIBITED_ACTION_CLASSES = frozenset({"physical_control"})

# Tier a role may execute unassisted, and the tier it may never exceed even
# with approvals. Nobody is granted R5 - see PROHIBITED_TOOLS.
ROLE_MAX_TIER = {
    "public": "R0", "auditor": "R0", "sim": "R1", "agent": "R2",
    "operator": "R3", "approver": "R4", "admin": "R4",
}
ROLE_HARD_MAX = {
    "public": "R0", "auditor": "R0", "sim": "R1", "agent": "R2",
    "operator": "R4", "approver": "R4", "admin": "R4",
}

# An R3 "routine reversible op" may not touch a criticality-5 asset; that
# needs an escalated R4 change with named approvers.
CRITICALITY_CEILING = {"R0": 5, "R1": 5, "R2": 5, "R3": 4, "R4": 5, "R5": 0}
CRITICALITY_APPROVAL_AT = 4

BLAST_CEILING = {"R0": 10**9, "R1": 10**9, "R2": 10**9, "R3": 25, "R4": 250, "R5": 0}
BLAST_APPROVAL_AT = {"R0": 10**9, "R1": 10**9, "R2": 10**9, "R3": 10, "R4": 50, "R5": 0}

MAX_EVIDENCE_AGE_S = {"R0": 10**9, "R1": 86400, "R2": 3600, "R3": 900, "R4": 300, "R5": 60}
DEFAULT_RATE_LIMIT_PER_H = {"R0": 10**9, "R1": 10**9, "R2": 200, "R3": 60, "R4": 12, "R5": 0}

REVERSIBILITY_REQUIRED_ABOVE = "R3"  # R4 and up must be reversible or approved
DUAL_CONTROL_TIERS = HIGH_TIERS

CTX_KEYS = (
    "tool_id", "action_class", "risk_tier", "tenant_id",
    "principal_id", "principal_role", "principal_kind", "principal_status",
    "principal_tenant", "principal_trust_domain", "principal_spiffe_id",
    "principal_authority", "principal_jurisdictions",
    "asset_id", "asset_tenant", "asset_criticality", "asset_jurisdiction",
    "blast_radius", "evidence_age_s", "evidence_status", "evidence_max_age_s",
    "public_facing", "reversible", "tool_trust_domain", "time_window",
    "recent_actions_1h", "rate_limit_per_h", "approvals", "emergency", "now",
)


# ----------------------------------------------------------------- helpers
def _tier(ctx) -> str:
    return ctx.get("risk_tier") or "R0"


def _rank(tier: str) -> int:
    return TIER_ORDER.get(tier, 0)


def _parse_ts(raw: str) -> _dt.datetime:
    t = _dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _now(ctx) -> _dt.datetime:
    return _parse_ts(ctx.get("now") or "1970-01-01T00:00:00Z")


def valid_approvals(ctx) -> list[str]:
    """Distinct approver ids holding an unexpired 'approved' decision."""
    now = _now(ctx)
    seen: list[str] = []
    for a in ctx.get("approvals") or []:
        if a.get("decision") != "approved":
            continue
        exp = a.get("expires_at")
        if exp and _parse_ts(exp) <= now:
            continue
        who = a.get("approver_id")
        if who and who not in seen:
            seen.append(who)
    return seen


def role_permits(role: str, risk_class: str) -> bool:
    """Used by the tool registry: manifest visibility is a policy decision."""
    cap = ROLE_HARD_MAX.get(role)
    return cap is not None and _rank(risk_class) <= _rank(cap)


# ------------------------------------------------------------------- rules
def _c_prohibited(ctx):
    tool = ctx.get("tool_id") or ""
    if (
        tool in PROHIBITED_TOOLS
        or ctx.get("action_class") in PROHIBITED_ACTION_CLASSES
        or _tier(ctx) == "R5"
    ):
        # Wording of the request cannot reach this decision: it reads the tool
        # id, action class and computed tier only, never the args.
        return ("deny", (
            "prohibited action: "
            + (tool or str(ctx.get("action_class")))
            + " is R5 direct equipment control. Auralis never issues direct"
            " equipment control. Raise a work order for a qualified operator"
            " instead."
        ))
    return ("allow", "not on the prohibited-action registry")


def _c_identity(ctx):
    pid = ctx.get("principal_id")
    if not pid:
        return ("deny", "no workload identity presented")
    status = ctx.get("principal_status")
    if status != "active":
        return ("deny", f"principal {pid} identity status is '{status}', not 'active'")
    if ctx.get("principal_kind") == "agent" and not ctx.get("principal_spiffe_id"):
        return ("deny", f"agent principal {pid} carries no workload identity (spiffe_id)")
    return ("allow", "identity valid and not revoked")


def _c_tenant(ctx):
    tenant, owner = ctx.get("tenant_id"), ctx.get("principal_tenant")
    if not tenant or owner != tenant:
        return ("deny", f"principal tenant '{owner}' does not match resource tenant '{tenant}'")
    asset_tenant = ctx.get("asset_tenant")
    if asset_tenant and asset_tenant != tenant:
        return ("deny", f"target asset belongs to tenant '{asset_tenant}', not '{tenant}'")
    return ("allow", "tenant matches")


def _c_sim_barrier(ctx):
    if (ctx.get("principal_trust_domain") or "prod") == "sim" and (
        ctx.get("tool_trust_domain") or "prod"
    ) == "prod":
        return ("deny", (
            f"simulation barrier: principal {ctx.get('principal_id')} is in trust_domain "
            f"'sim' and may not invoke production tool '{ctx.get('tool_id')}'"
        ))
    return ("allow", "trust domains compatible")


def _c_role_tier(ctx):
    role = ctx.get("principal_role") or ""
    tier = _tier(ctx)
    hard = ROLE_HARD_MAX.get(role)
    if hard is None:
        return ("deny", f"unknown role '{role}' holds no tier grant")
    if _rank(tier) > _rank(hard):
        return ("deny", f"role '{role}' may never exceed {hard}; this action instance is {tier}")
    if _rank(tier) > _rank(ROLE_MAX_TIER[role]):
        if valid_approvals(ctx):
            return ("allow", f"{tier} above the unassisted cap for '{role}', approval on file")
        return ("require_approval",
                f"role '{role}' acts unassisted up to {ROLE_MAX_TIER[role]}; this instance is {tier}")
    return ("allow", f"role '{role}' permitted for {tier}")


def _c_criticality(ctx):
    crit = int(ctx.get("asset_criticality") or 0)
    tier = _tier(ctx)
    ceiling = CRITICALITY_CEILING.get(tier, 5)
    if crit > ceiling:
        return ("deny", (
            f"asset criticality {crit} exceeds the {tier} ceiling of {ceiling}; "
            "escalate to a higher-tier change with named approvers"
        ))
    if crit >= CRITICALITY_APPROVAL_AT and _rank(tier) >= 3 and not valid_approvals(ctx):
        return ("require_approval", f"criticality-{crit} asset at {tier} needs a named approver")
    return ("allow", f"criticality {crit} within the {tier} ceiling")


def _c_evidence_freshness(ctx):
    tier = _tier(ctx)
    status = ctx.get("evidence_status", "valid")
    if status != "valid":
        return ("deny", f"supporting evidence status is '{status}'; re-observe before acting")
    age = ctx.get("evidence_age_s")
    if age is None:
        if _rank(tier) >= 3:
            return ("deny", f"{tier} action carries no dated evidence")
        return ("allow", "no evidence required below R3")
    limit = int(ctx.get("evidence_max_age_s") or MAX_EVIDENCE_AGE_S[tier])
    if int(age) > limit:
        return ("deny", (
            f"supporting evidence is {int(age)}s old; {tier} requires <= {limit}s. "
            "Re-observe before acting."
        ))
    return ("allow", f"evidence {int(age)}s old, within the {limit}s {tier} window")


def _c_geofence(ctx):
    allowed = ctx.get("principal_jurisdictions") or []
    where = ctx.get("asset_jurisdiction")
    if not allowed:
        return ("allow", "principal holds no jurisdiction restriction")
    if where and where not in allowed:
        return ("deny", f"target is in jurisdiction '{where}'; principal is scoped to {sorted(allowed)}")
    return ("allow", "target inside the principal geofence")


def _c_time_window(ctx):
    win = ctx.get("time_window")
    if not win or _rank(_tier(ctx)) < 3:
        return ("allow", "no time-window restriction applies")
    hhmm = _now(ctx).strftime("%H:%M")
    start, end = win.get("start", "00:00"), win.get("end", "23:59")
    inside = (start <= hhmm <= end) if start <= end else (hhmm >= start or hhmm <= end)
    if not inside:
        return ("require_approval", f"now {hhmm} is outside the permitted window {start}-{end}")
    return ("allow", f"now {hhmm} inside the permitted window {start}-{end}")


def _c_rate_limit(ctx):
    tier = _tier(ctx)
    limit = ctx.get("rate_limit_per_h")
    limit = DEFAULT_RATE_LIMIT_PER_H[tier] if limit is None else int(limit)
    used = int(ctx.get("recent_actions_1h") or 0)
    if used >= limit:
        return ("deny", f"rate limit reached: {used} {tier} actions in the last hour, limit {limit}")
    return ("allow", f"{used}/{limit} {tier} actions used this hour")


def _c_blast_radius(ctx):
    tier = _tier(ctx)
    blast = int(ctx.get("blast_radius") or 0)
    ceiling = BLAST_CEILING.get(tier, 10**9)
    if blast > ceiling:
        return ("deny", f"blast radius {blast} assets exceeds the {tier} ceiling of {ceiling}")
    if blast > BLAST_APPROVAL_AT.get(tier, 10**9) and not valid_approvals(ctx):
        return ("require_approval", f"blast radius {blast} assets at {tier} needs a named approver")
    return ("allow", f"blast radius {blast} within the {tier} ceiling of {ceiling}")


def _c_reversibility(ctx):
    tier = _tier(ctx)
    if _rank(tier) <= _rank(REVERSIBILITY_REQUIRED_ABOVE):
        return ("allow", f"reversibility not mandated at {tier}")
    if ctx.get("reversible"):
        return ("allow", f"{tier} action is reversible")
    if valid_approvals(ctx):
        return ("allow", f"irreversible {tier} action accepted under a named approval")
    return ("require_approval", (
        f"{tier} action is not automatically reversible; a named human must accept "
        "the irreversible effect"
    ))


def _c_dual_control(ctx):
    tier = _tier(ctx)
    if tier not in DUAL_CONTROL_TIERS:
        return ("allow", f"dual control not required at {tier}")
    approvers = valid_approvals(ctx)
    if len(approvers) < 2:
        return ("require_approval",
                f"{tier} requires dual control: 2 distinct unexpired approvals, have {len(approvers)}")
    return ("allow", f"dual control satisfied by {approvers[0]} and {approvers[1]}")


def _c_emergency_override(ctx):
    em = ctx.get("emergency")
    if not em:
        return ("allow", "no break-glass claimed")
    if not em.get("reason_code"):
        return ("deny", "break-glass override requires a reason code")
    if _tier(ctx) in HIGH_TIERS:
        second = em.get("second_approver")
        if not second:
            return ("deny", f"break-glass at {_tier(ctx)} requires a second approver")
        if second == ctx.get("principal_id"):
            return ("deny", "break-glass second approver must differ from the requesting principal")
    return ("allow", f"break-glass accepted, reason code {em.get('reason_code')}")


# Order matters. The prohibited registry is first so nothing can pre-empt it.
RULES = [
    {"id": "R5_PROHIBITED", "applies_to": ALL_TIERS, "check": _c_prohibited,
     "description": "R5 direct physical control is always denied. Auralis never builds direct equipment control."},
    {"id": "IDENTITY_VALID", "applies_to": ALL_TIERS, "check": _c_identity,
     "description": "Principal exists, is active, and if a workload carries a SPIFFE identity."},
    {"id": "TENANT_MATCH", "applies_to": ALL_TIERS, "check": _c_tenant,
     "description": "Principal tenant matches the resource tenant and the target asset tenant."},
    {"id": "SIMULATION_BARRIER", "applies_to": ALL_TIERS, "check": _c_sim_barrier,
     "description": "A trust_domain='sim' principal may never invoke a production tool."},
    {"id": "ROLE_TIER", "applies_to": ALL_TIERS, "check": _c_role_tier,
     "description": "Role is granted the computed risk tier; above its unassisted cap requires approval."},
    {"id": "ASSET_CRITICALITY_CEILING", "applies_to": ALL_TIERS, "check": _c_criticality,
     "description": "Target asset criticality is within the ceiling for the tier."},
    {"id": "EVIDENCE_FRESHNESS", "applies_to": ALL_TIERS, "check": _c_evidence_freshness,
     "description": "Supporting evidence is valid and inside the freshness window for the tier."},
    {"id": "GEOFENCE", "applies_to": ALL_TIERS, "check": _c_geofence,
     "description": "Target lies inside the principal's authorised jurisdictions."},
    {"id": "TIME_WINDOW", "applies_to": ACTING_TIERS, "check": _c_time_window,
     "description": "Acting tiers respect the permitted operating window."},
    {"id": "RATE_LIMIT", "applies_to": ALL_TIERS, "check": _c_rate_limit,
     "description": "Actions per hour at this tier are within budget."},
    {"id": "BLAST_RADIUS_CEILING", "applies_to": ALL_TIERS, "check": _c_blast_radius,
     "description": "Dependent-asset count is within the ceiling for the tier."},
    {"id": "REVERSIBILITY_REQUIRED", "applies_to": ALL_TIERS, "check": _c_reversibility,
     "description": "Above R3 an action is reversible or a named human accepts the irreversibility."},
    {"id": "DUAL_CONTROL", "applies_to": HIGH_TIERS, "check": _c_dual_control,
     "description": "R4/R5 need two distinct unexpired approvals."},
    {"id": "EMERGENCY_OVERRIDE", "applies_to": ALL_TIERS, "check": _c_emergency_override,
     "description": "Break-glass needs a reason code, plus a distinct second approver at R4/R5."},
]

RULE_IDS = tuple(r["id"] for r in RULES)


def evaluate(ctx: dict) -> tuple[str, str, str]:
    """Pure. Returns (effect, rule_id, reason).

    First deny wins, then the first require_approval, else allow.
    """
    tier = _tier(ctx)
    pending: tuple[str, str] | None = None
    for rule in RULES:
        if tier not in rule["applies_to"]:
            continue
        effect, reason = rule["check"](ctx)
        if effect == "deny":
            return ("deny", rule["id"], reason)
        if effect == "require_approval" and pending is None:
            pending = (rule["id"], reason)
    if pending:
        return ("require_approval", pending[0], pending[1])
    return ("allow", "ALLOW_DEFAULT", f"all {len(RULES)} checks in bundle v{VERSION} passed")


# The bundle names itself: a decision can point at the exact source that
# produced it. Newlines are normalised so the hash is stable across platforms.
RULES_SOURCE = pathlib.Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
RULES_HASH = hashlib.sha256(RULES_SOURCE.encode("utf-8")).hexdigest()
