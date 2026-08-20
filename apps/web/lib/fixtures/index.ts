/**
 * Bundled demo snapshot — Vijayawada, Andhra Pradesh.
 *
 * WHY THIS EXISTS: the web app deploys to Vercel where the Python API is not
 * reachable. Without a fallback the whole product is a dead grey box in front
 * of judges. With it, every screen renders real-shaped data.
 *
 * HARD RULE: this data is NEVER presented as live. lib/api.ts flips the global
 * data mode to "fixture" the moment it serves any of this, and the shell shows
 * a permanent "Demo data — API not connected" indicator. Showing fixture data
 * as observed would be exactly the synthetic-as-live failure the product is
 * built to prevent.
 *
 * Timestamps are generated relative to now so freshness reads honestly.
 */

import type {
  Action,
  AuditChainReport,
  AuditEvent,
  Claim,
  ConnectorHealth,
  Evidence,
  EvidenceConflict,
  Forecast,
  Incident,
  IncidentDetail,
  OpsMetrics,
  Plan,
  PolicyDecision,
  TwinQueryResult,
} from "../types";

export const CITY = {
  name: "Vijayawada",
  region: "Andhra Pradesh, India",
  centre: [80.648, 16.5062] as [number, number],
  zoom: 11.6,
};

const now = () => Date.now();
const ago = (s: number) => new Date(now() - s * 1000).toISOString();
const ahead = (s: number) => new Date(now() + s * 1000).toISOString();

function ev(
  id: string,
  source: string,
  connector_id: string,
  statement: string,
  opts: Partial<Evidence> & { age: number },
): Evidence {
  const { age, ...rest } = opts;
  return {
    id,
    source,
    connector_id,
    trust_tier: "certified",
    observed_at: ago(age),
    age_s: age,
    fresh: age <= 300,
    evidence_class: "observation",
    status: "valid",
    event_id: `evt_${id.slice(3)}`,
    statement,
    value: {},
    expires_at: ahead(1800),
    integrity_hash: `sha256:${id}`,
    geometry: null,
    prov_activity: "ingest",
    prov_derived_from: [],
    ...rest,
  };
}

export const EVIDENCE: Evidence[] = [
  ev("ev_bud_level", "Budameru SCADA · Gauge BD-04", "conn_hydro_scada", "Budameru rivulet stage 4.82 m, rising 0.31 m/h.", {
    age: 96,
    trust_tier: "statutory",
    value: { stage_m: 4.82, rate_m_per_h: 0.31 },
    geometry: { type: "Point", coordinates: [80.6113, 16.5498] },
  }),
  ev("ev_krishna_flow", "Krishna Barrage Telemetry", "conn_hydro_scada", "Prakasam Barrage outflow 386,000 cusecs.", {
    age: 172,
    trust_tier: "statutory",
    value: { cusecs: 386000 },
    geometry: { type: "Point", coordinates: [80.6019, 16.4972] },
  }),
  ev("ev_imd_rain", "IMD Nowcast · Krishna District", "conn_imd", "68 mm rainfall in 3 h over the upper catchment.", {
    age: 420,
    trust_tier: "certified",
    evidence_class: "derived",
    fresh: false,
    value: { mm_3h: 68 },
  }),
  ev("ev_pump_state", "Ajit Singh Nagar Pump House", "conn_scada_pumps", "Pump station P-12 running 2 of 4 units.", {
    age: 61,
    trust_tier: "certified",
    value: { units_running: 2, units_total: 4 },
    geometry: { type: "Point", coordinates: [80.6338, 16.5261] },
  }),
  ev("ev_citizen_report", "Citizen report · WhatsApp channel", "conn_citizen", "Water entering homes near Payakapuram, knee height.", {
    age: 240,
    trust_tier: "crowdsourced",
    value: { depth_cm: 45 },
    geometry: { type: "Point", coordinates: [80.6231, 16.5324] },
  }),
  ev("ev_cctv_frame", "Traffic CCTV · Ramavarappadu Ring", "conn_cctv", "Carriageway standing water, two lanes impassable.", {
    age: 310,
    trust_tier: "verified",
    fresh: false,
    status: "conflict",
    value: { lanes_blocked: 2 },
  }),
  ev("ev_sat_extent", "Sentinel-1 derived flood extent", "conn_sat", "Inundation polygon 4.1 km² north of the rivulet.", {
    age: 1840,
    trust_tier: "certified",
    evidence_class: "derived",
    fresh: false,
    value: { area_km2: 4.1 },
  }),
];

const evRef = (id: string) => EVIDENCE.find((e) => e.id === id)!;

export const INCIDENTS: Incident[] = [
  {
    id: "inc_budameru_01",
    title: "Budameru rivulet overtopping at Payakapuram",
    incident_class: "flood.urban",
    severity: "critical",
    state: "awaiting_approval",
    opened_at: ago(1420),
    closed_at: null,
    geometry: { type: "Point", coordinates: [80.6231, 16.5324] },
    detector: "hydro-threshold-detector",
    evidence_ids: ["ev_bud_level", "ev_imd_rain", "ev_citizen_report", "ev_sat_extent"],
    asset_ids: ["ast_pump_p12", "ast_gate_bd04", "ast_sub_pk3"],
    first_observation_at: ago(1600),
  },
  {
    id: "inc_ring_road_02",
    title: "Standing water blocking Ramavarappadu Ring carriageway",
    incident_class: "transport.obstruction",
    severity: "major",
    state: "planning",
    opened_at: ago(2960),
    closed_at: null,
    geometry: { type: "Point", coordinates: [80.6702, 16.5195] },
    detector: "cctv-vision-detector",
    evidence_ids: ["ev_cctv_frame", "ev_imd_rain"],
    asset_ids: ["ast_road_rr1"],
    first_observation_at: ago(3100),
  },
  {
    id: "inc_substation_03",
    title: "Payakapuram substation approaching flood cut-off level",
    incident_class: "power.risk",
    severity: "major",
    state: "assessing",
    opened_at: ago(760),
    closed_at: null,
    geometry: { type: "Point", coordinates: [80.6189, 16.5361] },
    detector: "asset-exposure-detector",
    evidence_ids: ["ev_bud_level", "ev_sat_extent"],
    asset_ids: ["ast_sub_pk3"],
    first_observation_at: ago(820),
  },
];

export const CLAIMS: Claim[] = [
  {
    id: "cl_stage_now",
    incident_id: "inc_budameru_01",
    statement:
      "Budameru stage at gauge BD-04 is 4.82 m, 0.42 m above the overtopping threshold.",
    subject: "gauge:BD-04",
    predicate: "stage_m",
    object: "4.82",
    claim_class: "fact",
    valid_from: ago(96),
    valid_to: ahead(900),
    evidence_ids: ["ev_bud_level"],
    confidence_basis: "statutory gauge, 60 s cadence",
    uncertainty: null,
    author: "evidence-compiler",
    author_kind: "agent",
    status: "active",
  },
  {
    id: "cl_peak_forecast",
    incident_id: "inc_budameru_01",
    statement:
      "Stage is forecast to peak between 5.3 m and 6.1 m within 180 minutes.",
    subject: "gauge:BD-04",
    predicate: "peak_stage_m",
    object: "5.7",
    claim_class: "forecast",
    valid_from: ago(60),
    valid_to: ahead(10800),
    evidence_ids: ["ev_bud_level", "ev_imd_rain", "ev_krishna_flow"],
    confidence_basis: "routing model v3.2, p10-p90 envelope",
    uncertainty: { lower: 5.3, upper: 6.1, unit: "m" },
    author: "forecast-agent",
    author_kind: "model",
    status: "active",
  },
  {
    id: "cl_recommend_pumps",
    incident_id: "inc_budameru_01",
    statement:
      "Bring pump station P-12 to full capacity and pre-close gate BD-04 before the forecast peak.",
    subject: "plan:pln_budameru_a",
    predicate: "recommends",
    object: "pump_capacity_full",
    claim_class: "recommendation",
    valid_from: ago(50),
    valid_to: ahead(7200),
    evidence_ids: ["ev_pump_state", "ev_bud_level"],
    confidence_basis: "objective: minimise premises inundated",
    uncertainty: null,
    author: "planner-agent",
    author_kind: "agent",
    status: "active",
  },
];

export const CONFLICTS: EvidenceConflict[] = [
  {
    id: "cfl_lane_status",
    subject: "road:ramavarappadu-ring lane availability",
    evidence_a: evRef("ev_cctv_frame"),
    evidence_b: evRef("ev_citizen_report"),
    detected_at: ago(280),
    resolution: "unresolved",
    resolved_by_rule: null,
    winner_evidence_id: null,
    impact:
      "Diversion plan for the ring road is held until lane availability is settled.",
  },
];

export const FORECASTS: Forecast[] = [
  {
    id: "fc_stage_180",
    incident_id: "inc_budameru_01",
    model_version: "routing-3.2.1",
    horizon_min: 180,
    produced_at: ago(60),
    median: 5.7,
    p10: 5.3,
    p90: 6.1,
    unit: "m",
    series: [
      { t: 0, median: 4.82, p10: 4.82, p90: 4.82 },
      { t: 60, median: 5.21, p10: 5.05, p90: 5.4 },
      { t: 120, median: 5.52, p10: 5.2, p90: 5.83 },
      { t: 180, median: 5.7, p10: 5.3, p90: 6.1 },
    ],
    in_envelope: true,
    envelope_note: null,
    evidence_ids: ["ev_bud_level", "ev_imd_rain"],
  },
];

const POLICY_ALLOW: PolicyDecision = {
  id: "pd_pump_capacity",
  bundle_version: "2026.08.3",
  inputs_hash: "sha256:9f2c...a41",
  inputs: { risk_tier: "R2", asset_criticality: 3, evidence_age_s: 61 },
  effect: "allow",
  rule_id: "RULE.PUMP.CAPACITY.R2",
  reason: "Reversible pump capacity change within the operator's standing authority.",
  decided_at: ago(48),
  subject_action_id: "act_pump_full",
};

const POLICY_APPROVAL: PolicyDecision = {
  id: "pd_gate_close",
  bundle_version: "2026.08.3",
  inputs_hash: "sha256:31be...77d",
  inputs: {
    risk_tier: "R4",
    asset_criticality: 5,
    blast_radius: 1240,
    public_facing: true,
    evidence_age_s: 96,
  },
  effect: "require_approval",
  rule_id: "RULE.GATE.CLOSE.R4",
  reason:
    "Closing BD-04 affects 1,240 premises downstream and is public-facing. Named approver required.",
  decided_at: ago(44),
  subject_action_id: "act_gate_close",
};

const POLICY_DENY: PolicyDecision = {
  id: "pd_siren",
  bundle_version: "2026.08.3",
  inputs_hash: "sha256:c07a...12f",
  inputs: { risk_tier: "R5", public_facing: true, evidence_age_s: 1840 },
  effect: "deny",
  rule_id: "RULE.PUBLIC.SIREN.EVIDENCE_AGE",
  reason:
    "Mass public alerting requires corroborating observation newer than 600 s. Newest corroboration is 1,840 s old.",
  decided_at: ago(40),
  subject_action_id: "act_siren",
};

export const POLICY_DECISIONS: PolicyDecision[] = [
  POLICY_ALLOW,
  POLICY_APPROVAL,
  POLICY_DENY,
];

export const ACTIONS: Action[] = [
  {
    id: "act_pump_full",
    plan_id: "pln_budameru_a",
    tool_id: "tool.pump.set_capacity",
    sequence: 1,
    args: { asset_id: "ast_pump_p12", units: 4 },
    target_asset_id: "ast_pump_p12",
    risk_tier: "R2",
    risk_inputs: { asset_criticality: 3, blast_radius: 18, public_facing: false },
    blast_radius: 18,
    reversible: true,
    rollback_tool_id: "tool.pump.set_capacity",
    status: "verified",
    idempotency_key: "web_9c1f2a",
    policy_decision: POLICY_ALLOW,
    executed_at: ago(300),
    intended_state: { units_running: 4 },
    actual_state: { units_running: 4 },
    verification: "SUCCESS",
    verification_method: "read-back after 60 s",
  },
  {
    id: "act_gate_close",
    plan_id: "pln_budameru_a",
    tool_id: "tool.gate.set_position",
    sequence: 2,
    args: { asset_id: "ast_gate_bd04", position_pct: 0 },
    target_asset_id: "ast_gate_bd04",
    risk_tier: "R4",
    risk_inputs: {
      asset_criticality: 5,
      blast_radius: 1240,
      public_facing: true,
      evidence_age_s: 96,
    },
    blast_radius: 1240,
    reversible: true,
    rollback_tool_id: "tool.gate.set_position",
    status: "proposed",
    idempotency_key: null,
    policy_decision: POLICY_APPROVAL,
    executed_at: null,
    intended_state: { position_pct: 0 },
    actual_state: null,
    verification: null,
    verification_method: "read-back within 120 s",
  },
  {
    id: "act_siren",
    plan_id: "pln_budameru_a",
    tool_id: "tool.public.siren",
    sequence: 3,
    args: { zone: "payakapuram", message_id: "flood_evac_01" },
    target_asset_id: null,
    risk_tier: "R5",
    risk_inputs: { public_facing: true, evidence_age_s: 1840 },
    blast_radius: 24000,
    reversible: false,
    rollback_tool_id: null,
    status: "blocked",
    idempotency_key: null,
    policy_decision: POLICY_DENY,
    executed_at: null,
    intended_state: null,
    actual_state: null,
    verification: null,
    verification_method: null,
  },
];

export const PLANS: Plan[] = [
  {
    id: "pln_budameru_a",
    incident_id: "inc_budameru_01",
    title: "Hold the Payakapuram line before the 180-minute peak",
    rationale:
      "Maximise drainage capacity while the stage is still below the bund crest, then isolate the rivulet ahead of the forecast peak. Public alerting is held until corroboration is fresh.",
    created_at: ago(600),
    created_by: "planner-agent",
    status: "blocked",
    evidence_ids: ["ev_bud_level", "ev_imd_rain", "ev_pump_state"],
    claim_ids: ["cl_stage_now", "cl_peak_forecast", "cl_recommend_pumps"],
    validation: { grounded: true, sandbox_pass: true, conflicts: 1 },
    objective_score: { premises_protected: 1240, cost_index: 0.34, time_to_effect_min: 22 },
    actions: ACTIONS,
  },
];

export const INCIDENT_DETAIL: IncidentDetail = {
  incident: INCIDENTS[0],
  evidence: EVIDENCE.filter((e) => INCIDENTS[0].evidence_ids.includes(e.id)),
  claims: CLAIMS,
  conflicts: CONFLICTS,
  forecasts: FORECASTS,
  unknowns: [
    "Bund crest condition east of the BD-04 gate has no observation newer than 6 h.",
    "Ward-level population presence is modelled, not observed.",
  ],
  assets: [
    { id: "ast_pump_p12", name: "Ajit Singh Nagar pump house", kind: "pump_station" },
    { id: "ast_gate_bd04", name: "Budameru gate BD-04", kind: "gate" },
    { id: "ast_sub_pk3", name: "Payakapuram substation", kind: "substation" },
  ],
  degraded: false,
};

export const CONNECTORS: ConnectorHealth[] = [
  {
    id: "conn_hydro_scada",
    name: "Hydrology SCADA",
    trust_tier: "statutory",
    contract_version: "2.1.0",
    freshness_sla_s: 120,
    last_seen_at: ago(96),
    age_s: 96,
    fresh: true,
    quality_score: 0.99,
    dpia_status: "approved",
    events_24h: 14320,
    quarantined_24h: 4,
    open_conflicts: 0,
  },
  {
    id: "conn_imd",
    name: "IMD nowcast feed",
    trust_tier: "certified",
    contract_version: "1.4.2",
    freshness_sla_s: 300,
    last_seen_at: ago(420),
    age_s: 420,
    fresh: false,
    quality_score: 0.94,
    dpia_status: "approved",
    events_24h: 288,
    quarantined_24h: 0,
    open_conflicts: 0,
  },
  {
    id: "conn_scada_pumps",
    name: "Pump station SCADA",
    trust_tier: "certified",
    contract_version: "3.0.1",
    freshness_sla_s: 120,
    last_seen_at: ago(61),
    age_s: 61,
    fresh: true,
    quality_score: 0.98,
    dpia_status: "approved",
    events_24h: 8640,
    quarantined_24h: 1,
    open_conflicts: 0,
  },
  {
    id: "conn_cctv",
    name: "Traffic CCTV vision",
    trust_tier: "verified",
    contract_version: "0.9.4",
    freshness_sla_s: 180,
    last_seen_at: ago(310),
    age_s: 310,
    fresh: false,
    quality_score: 0.81,
    dpia_status: "review_due",
    events_24h: 2140,
    quarantined_24h: 37,
    open_conflicts: 1,
  },
  {
    id: "conn_citizen",
    name: "Citizen reports",
    trust_tier: "crowdsourced",
    contract_version: "1.0.0",
    freshness_sla_s: 900,
    last_seen_at: ago(240),
    age_s: 240,
    fresh: true,
    quality_score: 0.62,
    dpia_status: "approved",
    events_24h: 412,
    quarantined_24h: 63,
    open_conflicts: 1,
  },
  {
    id: "conn_sat",
    name: "Sentinel-1 flood extent",
    trust_tier: "certified",
    contract_version: "2.0.0",
    freshness_sla_s: 3600,
    last_seen_at: ago(1840),
    age_s: 1840,
    fresh: true,
    quality_score: 0.9,
    dpia_status: "approved",
    events_24h: 12,
    quarantined_24h: 0,
    open_conflicts: 0,
  },
];

export const OPS: OpsMetrics = {
  time_to_detect_s: 42,
  time_to_plan_s: 186,
  unsupported_claim_rate: 0,
  unauthorized_action_rate: 0,
  tool_success_rate: 0.98,
  policy_blocks_24h: 3,
  tool_errors_24h: 2,
  audit_events: 1284,
  llm_calls: 46,
  llm_tokens: 128400,
  llm_cost_usd: 0.42,
  cost_per_incident_usd: 0.14,
  degraded: false,
  source_health: CONNECTORS,
};

export const AUDIT: AuditEvent[] = [
  "incident.detected",
  "evidence.compiled",
  "claim.asserted",
  "forecast.produced",
  "plan.generated",
  "policy.evaluated",
  "action.executed",
  "action.verified",
  "policy.denied",
].map((kind, i) => ({
  id: `aud_${String(i + 1).padStart(4, "0")}`,
  seq: i + 1,
  workflow_id: "wf_budameru_01",
  at: ago(1400 - i * 120),
  actor_id: i > 5 ? "p_operator" : "svc_pipeline",
  actor_kind: i > 5 ? ("human" as const) : ("service" as const),
  kind,
  subject_id: "inc_budameru_01",
  payload: { note: "demo snapshot entry" },
  prev_hash: i === 0 ? "0".repeat(64) : `sha256:chain_${i}`,
  entry_hash: `sha256:chain_${i + 1}`,
}));

export const CHAIN: AuditChainReport = {
  ok: true,
  checked: AUDIT.length,
  first_break_seq: null,
  detail: "Hash chain intact across the demo snapshot.",
};

export const TWIN: TwinQueryResult = {
  root: "ast_gate_bd04",
  depth: 2,
  nodes: [
    {
      id: "ast_gate_bd04",
      kind: "gate",
      name: "Budameru gate BD-04",
      criticality: 5,
      depth: 0,
      relation: null,
      geometry: { type: "Point", coordinates: [80.6113, 16.5498] },
      current_state: { position_pct: 100 },
    },
    {
      id: "ast_pump_p12",
      kind: "pump_station",
      name: "Ajit Singh Nagar pump house",
      criticality: 3,
      depth: 1,
      relation: "drains_to",
      geometry: { type: "Point", coordinates: [80.6338, 16.5261] },
      current_state: { units_running: 4 },
    },
    {
      id: "ast_sub_pk3",
      kind: "substation",
      name: "Payakapuram substation",
      criticality: 5,
      depth: 1,
      relation: "powers",
      geometry: { type: "Point", coordinates: [80.6189, 16.5361] },
      current_state: { energised: true },
    },
    {
      id: "ast_road_rr1",
      kind: "road",
      name: "Ramavarappadu Ring",
      criticality: 4,
      depth: 2,
      relation: "affected_by",
      geometry: { type: "Point", coordinates: [80.6702, 16.5195] },
      current_state: { lanes_open: 2 },
    },
  ],
  edges: [
    { from: "ast_gate_bd04", to: "ast_pump_p12", relation: "drains_to" },
    { from: "ast_gate_bd04", to: "ast_sub_pk3", relation: "floods" },
    { from: "ast_sub_pk3", to: "ast_road_rr1", relation: "powers" },
  ],
  blast_radius: 1240,
  traversal_ms: 3.4,
};

export const PUBLIC_STATUS = {
  city: CITY.name,
  updated_at: ago(300),
  disclosure_delay_s: 300,
  advisories: [
    {
      id: "adv_01",
      area: "Payakapuram, Ajit Singh Nagar",
      status: "Flooding response active",
      guidance: "Avoid low-lying streets. Follow instructions from field teams.",
      severity: "critical",
    },
    {
      id: "adv_02",
      area: "Ramavarappadu Ring",
      status: "Two lanes closed",
      guidance: "Use the NH-16 service road for through traffic.",
      severity: "major",
    },
  ],
  redactions: ["Asset-level state and exact gauge readings are withheld for 5 minutes."],
};

export const WORK_ORDERS = [
  {
    id: "wo_101",
    title: "Verify gate BD-04 seal after closure",
    asset_id: "ast_gate_bd04",
    priority: "high",
    status: "queued",
    assigned_to: "field_team_2",
    created_at: ago(500),
    geometry: { type: "Point", coordinates: [80.6113, 16.5498] },
  },
  {
    id: "wo_102",
    title: "Sandbag substation perimeter, Payakapuram",
    asset_id: "ast_sub_pk3",
    priority: "high",
    status: "in_progress",
    assigned_to: "field_team_1",
    created_at: ago(900),
    geometry: { type: "Point", coordinates: [80.6189, 16.5361] },
  },
];

/**
 * Path -> fixture. Returns undefined when nothing matches, in which case the
 * caller surfaces a real error instead of inventing data.
 */
export function fixtureFor(path: string): unknown {
  const p = path.split("?")[0];

  if (p === "/v1/health") return { ok: true, degraded: false, source: "fixture" };
  if (p === "/v1/incidents") return INCIDENTS;
  if (p === "/v1/metrics/ops") return OPS;
  if (p === "/v1/data-health") return CONNECTORS;
  if (p === "/v1/policies/decisions") return POLICY_DECISIONS;
  if (p === "/v1/audit/verify") return CHAIN;
  if (p === "/v1/public/status") return PUBLIC_STATUS;
  if (p === "/v1/field/work-orders") return WORK_ORDERS;
  if (p === "/v1/claims") return CLAIMS;
  if (p.startsWith("/v1/twin/")) return TWIN;
  if (p.startsWith("/v1/audit/")) return AUDIT;

  const plan = p.match(/^\/v1\/plans\/([^/]+)$/);
  if (plan) return { ...PLANS[0], id: plan[1] };

  if (/^\/v1\/incidents\/[^/]+\/plans$/.test(p)) return PLANS;

  const incident = p.match(/^\/v1\/incidents\/([^/]+)$/);
  if (incident) {
    const found = INCIDENTS.find((i) => i.id === incident[1]);
    return found ? { ...INCIDENT_DETAIL, incident: found } : INCIDENT_DETAIL;
  }

  const evidence = p.match(/^\/v1\/evidence\/([^/]+)$/);
  if (evidence) return EVIDENCE.find((e) => e.id === evidence[1]) ?? EVIDENCE[0];

  return undefined;
}
