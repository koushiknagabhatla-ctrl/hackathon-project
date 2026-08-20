"""Wire contracts. Coordinator-owned: lanes A-F consume, never edit.

Every field name here is the JSON wire format and is mirrored verbatim in
apps/web/src/lib/types.ts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ------------------------------------------------------------------ enums
RiskTier = Literal["R0", "R1", "R2", "R3", "R4", "R5"]
ClaimClass = Literal["fact", "forecast", "recommendation"]
EvidenceClass = Literal["observation", "derived", "synthetic", "synthetic-corroboration"]
TrustTier = Literal["statutory", "certified", "verified", "crowdsourced", "unknown"]
Verification = Literal["SUCCESS", "DIFFERENCE", "FAILED", "UNKNOWN"]
PolicyEffect = Literal["allow", "deny", "require_approval"]
IncidentState = Literal[
    "detected", "assessing", "planning", "awaiting_approval",
    "acting", "verifying", "closed",
]
ActionStatus = Literal[
    "proposed", "blocked", "approved", "executing", "executed",
    "verified", "difference", "failed", "unknown", "rolled_back",
]
Role = Literal["operator", "approver", "auditor", "admin", "agent", "sim"]

# --------------------------------------------------------------- evidence
class EvidenceRef(BaseModel):
    """The shape the UI renders as an evidence chip. Used everywhere."""

    id: str
    source: str
    trust_tier: TrustTier
    observed_at: str
    age_s: int
    fresh: bool
    evidence_class: EvidenceClass
    status: str = "valid"


class Evidence(EvidenceRef):
    connector_id: str
    event_id: str | None = None
    statement: str
    value: dict[str, Any] = Field(default_factory=dict)
    expires_at: str
    integrity_hash: str
    geometry: dict[str, Any] | None = None
    prov_activity: str | None = None
    prov_derived_from: list[str] = Field(default_factory=list)


class EvidenceConflict(BaseModel):
    id: str
    subject: str
    evidence_a: EvidenceRef
    evidence_b: EvidenceRef
    detected_at: str
    resolution: Literal["unresolved", "precedence", "superseded"] = "unresolved"
    resolved_by_rule: str | None = None
    winner_evidence_id: str | None = None
    impact: str | None = None  # human-readable effect on dependent plans


class Uncertainty(BaseModel):
    lower: float
    upper: float
    unit: str


# ------------------------------------------------------------------ claims
class Claim(BaseModel):
    id: str
    incident_id: str | None = None
    statement: str
    subject: str
    predicate: str
    object: str
    claim_class: ClaimClass
    valid_from: str
    valid_to: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence_basis: str | None = None
    uncertainty: Uncertainty | None = None
    author: str
    author_kind: Literal["human", "agent", "model"]
    status: Literal["active", "flagged", "retracted"] = "active"

    @model_validator(mode="after")
    def _grounded(self) -> "Claim":
        # Invariant 1. A fact or forecast without evidence cannot exist.
        if self.claim_class in ("fact", "forecast") and not self.evidence_ids:
            raise ValueError(
                f"ungrounded {self.claim_class} claim: evidence_ids is empty"
            )
        return self


# --------------------------------------------------------------- incidents
class Incident(BaseModel):
    id: str
    title: str
    incident_class: str
    severity: Literal["info", "minor", "major", "critical"]
    state: IncidentState
    opened_at: str
    closed_at: str | None = None
    geometry: dict[str, Any] | None = None
    detector: str
    evidence_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    first_observation_at: str | None = None


class Forecast(BaseModel):
    id: str
    incident_id: str
    model_version: str
    horizon_min: int
    produced_at: str
    median: float
    p10: float
    p90: float
    unit: str
    series: list[dict[str, Any]] = Field(default_factory=list)
    in_envelope: bool = True
    envelope_note: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class IncidentDetail(BaseModel):
    incident: Incident
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    forecasts: list[Forecast] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False


# ----------------------------------------------------------------- policy
class PolicyDecision(BaseModel):
    id: str
    bundle_version: str
    inputs_hash: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    effect: PolicyEffect
    rule_id: str
    reason: str
    decided_at: str
    subject_action_id: str | None = None


# ------------------------------------------------------- plans and actions
class Action(BaseModel):
    id: str
    plan_id: str
    tool_id: str
    sequence: int
    args: dict[str, Any] = Field(default_factory=dict)
    target_asset_id: str | None = None
    risk_tier: RiskTier
    risk_inputs: dict[str, Any] = Field(default_factory=dict)
    blast_radius: int = 0
    reversible: bool = True
    rollback_tool_id: str | None = None
    status: ActionStatus
    idempotency_key: str | None = None
    policy_decision: PolicyDecision | None = None
    executed_at: str | None = None
    intended_state: dict[str, Any] | None = None
    actual_state: dict[str, Any] | None = None
    verification: Verification | None = None
    verification_method: str | None = None


class Plan(BaseModel):
    id: str
    incident_id: str
    title: str
    rationale: str
    created_at: str
    created_by: str
    status: Literal[
        "draft", "validated", "blocked", "approved",
        "rejected", "executing", "verified", "failed",
    ]
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    objective_score: dict[str, Any] = Field(default_factory=dict)
    actions: list[Action] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    action_id: str
    decision: Literal["approved", "denied"]
    rationale: str | None = None


class ExecuteRequest(BaseModel):
    idempotency_key: str


# ------------------------------------------------------------------ audit
class AuditEvent(BaseModel):
    id: str
    seq: int
    workflow_id: str
    at: str
    actor_id: str
    actor_kind: Literal["human", "agent", "service", "model"]
    kind: str
    subject_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    entry_hash: str


class AuditChainReport(BaseModel):
    ok: bool
    checked: int
    first_break_seq: int | None = None
    detail: str | None = None


# ------------------------------------------------------------------- twin
class TwinNode(BaseModel):
    id: str
    kind: str
    name: str
    criticality: int
    depth: int
    relation: str | None = None
    geometry: dict[str, Any] | None = None
    current_state: dict[str, Any] = Field(default_factory=dict)


class TwinQueryResult(BaseModel):
    root: str
    depth: int
    nodes: list[TwinNode] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    blast_radius: int
    traversal_ms: float


# ------------------------------------------------------------- data health
class ConnectorHealth(BaseModel):
    id: str
    name: str
    trust_tier: TrustTier
    contract_version: str
    freshness_sla_s: int
    last_seen_at: str | None = None
    age_s: int | None = None
    fresh: bool
    quality_score: float
    dpia_status: str
    events_24h: int = 0
    quarantined_24h: int = 0
    open_conflicts: int = 0


# ------------------------------------------------------------------ events
class EventIn(BaseModel):
    connector_id: str
    source_event_id: str | None = None
    kind: str
    event_time: str
    payload: dict[str, Any]
    geometry: dict[str, Any] | None = None
    schema_version: str = "1.0.0"


class EventAccepted(BaseModel):
    id: str | None
    accepted: bool
    deduplicated: bool = False
    quarantined: bool = False
    reason: str | None = None
    evidence_id: str | None = None
    incident_id: str | None = None


# ------------------------------------------------------------- simulation
class SimulationRequest(BaseModel):
    scenario: str
    seed: int = 42
    overrides: dict[str, Any] = Field(default_factory=dict)
    base_workflow_id: str | None = None


class SimulationResult(BaseModel):
    id: str
    scenario: str
    seed: int
    overrides: dict[str, Any] = Field(default_factory=dict)
    trust_domain: Literal["sim"] = "sim"
    evidence_class: Literal["synthetic"] = "synthetic"
    baseline: dict[str, Any] = Field(default_factory=dict)
    counterfactual: dict[str, Any] = Field(default_factory=dict)
    deltas: list[dict[str, Any]] = Field(default_factory=list)
    policy_changes: list[dict[str, Any]] = Field(default_factory=list)
    results_hash: str | None = None


# --------------------------------------------------------------- ops/metrics
class OpsMetrics(BaseModel):
    time_to_detect_s: float | None = None
    time_to_plan_s: float | None = None
    unsupported_claim_rate: float = 0.0
    unauthorized_action_rate: float = 0.0
    tool_success_rate: float = 1.0
    policy_blocks_24h: int = 0
    tool_errors_24h: int = 0
    audit_events: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    llm_cost_usd: float = 0.0
    cost_per_incident_usd: float = 0.0
    degraded: bool = False
    source_health: list[ConnectorHealth] = Field(default_factory=list)
