/**
 * Wire contracts. Verbatim TypeScript mirror of services/api/models.py.
 * snake_case on the wire — do not camelCase anything here.
 * If models.py changes, this file changes with it. Never diverge.
 */

// ------------------------------------------------------------------ enums
export type RiskTier = "R0" | "R1" | "R2" | "R3" | "R4" | "R5";
export type ClaimClass = "fact" | "forecast" | "recommendation";
export type EvidenceClass =
  | "observation"
  | "derived"
  | "synthetic"
  | "synthetic-corroboration";
export type TrustTier =
  | "statutory"
  | "certified"
  | "verified"
  | "crowdsourced"
  | "unknown";
export type Verification = "SUCCESS" | "DIFFERENCE" | "FAILED" | "UNKNOWN";
export type PolicyEffect = "allow" | "deny" | "require_approval";
export type IncidentState =
  | "detected"
  | "assessing"
  | "planning"
  | "awaiting_approval"
  | "acting"
  | "verifying"
  | "closed";
export type ActionStatus =
  | "proposed"
  | "blocked"
  | "approved"
  | "executing"
  | "executed"
  | "verified"
  | "difference"
  | "failed"
  | "unknown"
  | "rolled_back";
export type Role = "operator" | "approver" | "auditor" | "admin" | "agent" | "sim";

export type Severity = "info" | "minor" | "major" | "critical";

export type Json = Record<string, unknown>;

// --------------------------------------------------------------- evidence
export interface EvidenceRef {
  id: string;
  source: string;
  trust_tier: TrustTier;
  observed_at: string;
  age_s: number;
  fresh: boolean;
  evidence_class: EvidenceClass;
  status: string;
}

export interface Evidence extends EvidenceRef {
  connector_id: string;
  event_id: string | null;
  statement: string;
  value: Json;
  expires_at: string;
  integrity_hash: string;
  geometry: Json | null;
  prov_activity: string | null;
  prov_derived_from: string[];
}

export interface EvidenceConflict {
  id: string;
  subject: string;
  evidence_a: EvidenceRef;
  evidence_b: EvidenceRef;
  detected_at: string;
  resolution: "unresolved" | "precedence" | "superseded";
  resolved_by_rule: string | null;
  winner_evidence_id: string | null;
  impact: string | null;
}

export interface Uncertainty {
  lower: number;
  upper: number;
  unit: string;
}

// ------------------------------------------------------------------ claims
export interface Claim {
  id: string;
  incident_id: string | null;
  statement: string;
  subject: string;
  predicate: string;
  object: string;
  claim_class: ClaimClass;
  valid_from: string;
  valid_to: string;
  evidence_ids: string[];
  confidence_basis: string | null;
  uncertainty: Uncertainty | null;
  author: string;
  author_kind: "human" | "agent" | "model";
  status: "active" | "flagged" | "retracted";
}

// --------------------------------------------------------------- incidents
export interface Incident {
  id: string;
  title: string;
  incident_class: string;
  severity: Severity;
  state: IncidentState;
  opened_at: string;
  closed_at: string | null;
  geometry: Json | null;
  detector: string;
  evidence_ids: string[];
  asset_ids: string[];
  first_observation_at: string | null;
}

export interface Forecast {
  id: string;
  incident_id: string;
  model_version: string;
  horizon_min: number;
  produced_at: string;
  median: number;
  p10: number;
  p90: number;
  unit: string;
  series: Json[];
  in_envelope: boolean;
  envelope_note: string | null;
  evidence_ids: string[];
}

export interface IncidentDetail {
  incident: Incident;
  evidence: Evidence[];
  claims: Claim[];
  conflicts: EvidenceConflict[];
  forecasts: Forecast[];
  unknowns: string[];
  assets: Json[];
  degraded: boolean;
}

// ----------------------------------------------------------------- policy
export interface PolicyDecision {
  id: string;
  bundle_version: string;
  inputs_hash: string;
  inputs: Json;
  effect: PolicyEffect;
  rule_id: string;
  reason: string;
  decided_at: string;
  subject_action_id: string | null;
}

// ------------------------------------------------------- plans and actions
export interface Action {
  id: string;
  plan_id: string;
  tool_id: string;
  sequence: number;
  args: Json;
  target_asset_id: string | null;
  risk_tier: RiskTier;
  risk_inputs: Json;
  blast_radius: number;
  reversible: boolean;
  rollback_tool_id: string | null;
  status: ActionStatus;
  idempotency_key: string | null;
  policy_decision: PolicyDecision | null;
  executed_at: string | null;
  intended_state: Json | null;
  actual_state: Json | null;
  verification: Verification | null;
  verification_method: string | null;
}

export type PlanStatus =
  | "draft"
  | "validated"
  | "blocked"
  | "approved"
  | "rejected"
  | "executing"
  | "verified"
  | "failed";

export interface Plan {
  id: string;
  incident_id: string;
  title: string;
  rationale: string;
  created_at: string;
  created_by: string;
  status: PlanStatus;
  evidence_ids: string[];
  claim_ids: string[];
  validation: Json;
  objective_score: Json;
  actions: Action[];
}

export interface ApprovalRequest {
  action_id: string;
  decision: "approved" | "denied";
  rationale?: string | null;
}

export interface ExecuteRequest {
  idempotency_key: string;
}

// ------------------------------------------------------------------ audit
export interface AuditEvent {
  id: string;
  seq: number;
  workflow_id: string;
  at: string;
  actor_id: string;
  actor_kind: "human" | "agent" | "service" | "model";
  kind: string;
  subject_id: string | null;
  payload: Json;
  prev_hash: string;
  entry_hash: string;
}

export interface AuditChainReport {
  ok: boolean;
  checked: number;
  first_break_seq: number | null;
  detail: string | null;
}

// ------------------------------------------------------------------- twin
export interface TwinNode {
  id: string;
  kind: string;
  name: string;
  criticality: number;
  depth: number;
  relation: string | null;
  geometry: Json | null;
  current_state: Json;
}

export interface TwinQueryResult {
  root: string;
  depth: number;
  nodes: TwinNode[];
  edges: Record<string, string>[];
  blast_radius: number;
  traversal_ms: number;
}

// ------------------------------------------------------------- data health
export interface ConnectorHealth {
  id: string;
  name: string;
  trust_tier: TrustTier;
  contract_version: string;
  freshness_sla_s: number;
  last_seen_at: string | null;
  age_s: number | null;
  fresh: boolean;
  quality_score: number;
  dpia_status: string;
  events_24h: number;
  quarantined_24h: number;
  open_conflicts: number;
}

// ------------------------------------------------------------------ events
export interface EventIn {
  connector_id: string;
  source_event_id?: string | null;
  kind: string;
  event_time: string;
  payload: Json;
  geometry?: Json | null;
  schema_version?: string;
}

export interface EventAccepted {
  id: string | null;
  accepted: boolean;
  deduplicated: boolean;
  quarantined: boolean;
  reason: string | null;
  evidence_id: string | null;
  incident_id: string | null;
}

// ------------------------------------------------------------- simulation
export interface SimulationRequest {
  scenario: string;
  seed?: number;
  overrides?: Json;
  base_workflow_id?: string | null;
}

export interface SimulationResult {
  id: string;
  scenario: string;
  seed: number;
  overrides: Json;
  trust_domain: "sim";
  evidence_class: "synthetic";
  baseline: Json;
  counterfactual: Json;
  deltas: Json[];
  policy_changes: Json[];
  results_hash: string | null;
}

// --------------------------------------------------------------- ops/metrics
export interface OpsMetrics {
  time_to_detect_s: number | null;
  time_to_plan_s: number | null;
  unsupported_claim_rate: number;
  unauthorized_action_rate: number;
  tool_success_rate: number;
  policy_blocks_24h: number;
  tool_errors_24h: number;
  audit_events: number;
  llm_calls: number;
  llm_tokens: number;
  llm_cost_usd: number;
  cost_per_incident_usd: number;
  degraded: boolean;
  source_health: ConnectorHealth[];
}

// ------------------------------------------------------------------ errors
/** Error envelope: {"error":{"code","message","detail","correlation_id"}} */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    detail?: unknown;
    correlation_id?: string;
    /** present on 403 policy_denied */
    rule_id?: string;
    reason?: string;
  };
}

// ------------------------------------------------------------------ stream
/** SSE frames on /v1/stream. `type` is the SSE event name. */
export type StreamEventType =
  | "incident"
  | "action"
  | "evidence"
  | "health"
  | "audit"
  | "ping";

export interface StreamEvent<T = unknown> {
  type: StreamEventType;
  data: T;
  received_at: string;
}
