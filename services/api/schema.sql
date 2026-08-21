-- Auralis vertical slice schema (SQLite).
-- Storage engine is SQLite; ALL geometry math runs through Shapely/GEOS (the
-- same engine PostGIS uses). Geometry is stored as GeoJSON text in EPSG:4326.
-- ponytail: SQLite + repository layer; swap to PostgreSQL/PostGIS by
-- reimplementing core/repo.py only when multi-writer concurrency is needed.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ---------------------------------------------------------------- tenancy
CREATE TABLE IF NOT EXISTS tenant (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  jurisdiction  TEXT NOT NULL,
  data_region   TEXT NOT NULL DEFAULT 'eu-west',
  created_at    TEXT NOT NULL
);

-- humans and workloads share one identity model
CREATE TABLE IF NOT EXISTS principal (
  id            TEXT PRIMARY KEY,
  tenant_id     TEXT NOT NULL REFERENCES tenant(id),
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL,
  authority     TEXT,
  spiffe_id     TEXT,
  trust_domain  TEXT NOT NULL DEFAULT 'prod',
  status        TEXT NOT NULL DEFAULT 'active'
);

-- ------------------------------------------------------------ connectors
CREATE TABLE IF NOT EXISTS connector (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenant(id),
  name             TEXT NOT NULL,
  trust_tier       TEXT NOT NULL,
  contract_version TEXT NOT NULL,
  freshness_sla_s  INTEGER NOT NULL,
  dpia_status      TEXT NOT NULL DEFAULT 'cleared',
  owner            TEXT NOT NULL,
  quality_score    REAL NOT NULL DEFAULT 1.0,
  last_seen_at     TEXT
);

-- ------------------------------------------------------------------ twin
CREATE TABLE IF NOT EXISTS asset (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenant(id),
  kind           TEXT NOT NULL,
  name           TEXT NOT NULL,
  geometry       TEXT NOT NULL,
  criticality    INTEGER NOT NULL,
  owner_dept     TEXT NOT NULL,
  current_state  TEXT NOT NULL DEFAULT '{}',
  reported_state TEXT NOT NULL DEFAULT '{}',
  desired_state  TEXT NOT NULL DEFAULT '{}',
  permitted_actions TEXT NOT NULL DEFAULT '[]',
  maintenance_window TEXT,
  geometry_accuracy_m REAL DEFAULT 5.0
);

CREATE TABLE IF NOT EXISTS asset_dependency (
  dependent_id  TEXT NOT NULL REFERENCES asset(id),
  depends_on_id TEXT NOT NULL REFERENCES asset(id),
  relation      TEXT NOT NULL,
  PRIMARY KEY (dependent_id, depends_on_id)
);

-- ------------------------------------------------------- ingest / events
CREATE TABLE IF NOT EXISTS raw_payload (
  content_hash TEXT PRIMARY KEY,
  connector_id TEXT NOT NULL REFERENCES connector(id),
  received_at  TEXT NOT NULL,
  body         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL REFERENCES tenant(id),
  connector_id    TEXT NOT NULL REFERENCES connector(id),
  source_event_id TEXT,
  content_hash    TEXT REFERENCES raw_payload(content_hash),
  kind            TEXT NOT NULL,
  event_time      TEXT NOT NULL,
  ingest_time     TEXT NOT NULL,
  geometry        TEXT,
  payload         TEXT NOT NULL,
  schema_version  TEXT NOT NULL,
  quarantined     INTEGER NOT NULL DEFAULT 0,
  quarantine_reason TEXT,
  UNIQUE (connector_id, source_event_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_event_time ON event(event_time);

-- --------------------------------------------------------------- incident
CREATE TABLE IF NOT EXISTS incident (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenant(id),
  title          TEXT NOT NULL,
  incident_class TEXT NOT NULL,
  severity       TEXT NOT NULL,
  state          TEXT NOT NULL,
  opened_at      TEXT NOT NULL,
  closed_at      TEXT,
  geometry       TEXT,
  detector       TEXT NOT NULL,
  evidence_ids   TEXT NOT NULL DEFAULT '[]',
  asset_ids      TEXT NOT NULL DEFAULT '[]',
  first_observation_at TEXT
);

-- ----------------------------------------------------- evidence + claims
CREATE TABLE IF NOT EXISTS evidence (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenant(id),
  connector_id   TEXT NOT NULL REFERENCES connector(id),
  event_id       TEXT REFERENCES event(id),
  evidence_class TEXT NOT NULL,
  statement      TEXT NOT NULL,
  value_json     TEXT NOT NULL,
  observed_at    TEXT NOT NULL,
  expires_at     TEXT NOT NULL,
  trust_tier     TEXT NOT NULL,
  integrity_hash TEXT NOT NULL,
  geometry       TEXT,
  status         TEXT NOT NULL DEFAULT 'valid',
  prov_activity  TEXT,
  prov_derived_from TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS evidence_conflict (
  id           TEXT PRIMARY KEY,
  tenant_id    TEXT NOT NULL REFERENCES tenant(id),
  evidence_a   TEXT NOT NULL REFERENCES evidence(id),
  evidence_b   TEXT NOT NULL REFERENCES evidence(id),
  subject      TEXT NOT NULL,
  detected_at  TEXT NOT NULL,
  resolution   TEXT NOT NULL DEFAULT 'unresolved',
  resolved_by_rule TEXT,
  winner_evidence_id TEXT REFERENCES evidence(id)
);

CREATE TABLE IF NOT EXISTS claim (
  id            TEXT PRIMARY KEY,
  tenant_id     TEXT NOT NULL REFERENCES tenant(id),
  incident_id   TEXT REFERENCES incident(id),
  statement     TEXT NOT NULL,
  subject       TEXT NOT NULL,
  predicate     TEXT NOT NULL,
  object        TEXT NOT NULL,
  claim_class   TEXT NOT NULL,
  valid_from    TEXT NOT NULL,
  valid_to      TEXT NOT NULL,
  evidence_ids  TEXT NOT NULL,
  confidence_basis TEXT,
  uncertainty   TEXT,
  author        TEXT NOT NULL,
  author_kind   TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS forecast (
  id            TEXT PRIMARY KEY,
  incident_id   TEXT NOT NULL REFERENCES incident(id),
  model_version TEXT NOT NULL,
  horizon_min   INTEGER NOT NULL,
  produced_at   TEXT NOT NULL,
  value_json    TEXT NOT NULL,
  in_envelope   INTEGER NOT NULL DEFAULT 1,
  envelope_note TEXT,
  evidence_ids  TEXT NOT NULL DEFAULT '[]'
);

-- ------------------------------------------------------- plans + actions
CREATE TABLE IF NOT EXISTS plan (
  id            TEXT PRIMARY KEY,
  tenant_id     TEXT NOT NULL REFERENCES tenant(id),
  incident_id   TEXT NOT NULL REFERENCES incident(id),
  title         TEXT NOT NULL,
  rationale     TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  created_by    TEXT NOT NULL,
  status        TEXT NOT NULL,
  evidence_ids  TEXT NOT NULL DEFAULT '[]',
  claim_ids     TEXT NOT NULL DEFAULT '[]',
  validation    TEXT NOT NULL DEFAULT '{}',
  objective_score TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS action (
  id              TEXT PRIMARY KEY,
  plan_id         TEXT NOT NULL REFERENCES plan(id),
  tool_id         TEXT NOT NULL,
  sequence        INTEGER NOT NULL,
  args            TEXT NOT NULL,
  target_asset_id TEXT REFERENCES asset(id),
  risk_tier       TEXT NOT NULL,
  risk_inputs     TEXT NOT NULL DEFAULT '{}',
  blast_radius    INTEGER NOT NULL DEFAULT 0,
  reversible      INTEGER NOT NULL DEFAULT 1,
  rollback_tool_id TEXT,
  status          TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  policy_decision_id TEXT,
  executed_at     TEXT,
  intended_state  TEXT,
  actual_state    TEXT,
  verification    TEXT,
  verification_method TEXT
);

CREATE TABLE IF NOT EXISTS approval (
  id           TEXT PRIMARY KEY,
  action_id    TEXT NOT NULL REFERENCES action(id),
  plan_id      TEXT NOT NULL REFERENCES plan(id),
  decision     TEXT NOT NULL,
  approver_id  TEXT NOT NULL REFERENCES principal(id),
  approver_authority TEXT,
  rationale    TEXT,
  decided_at   TEXT NOT NULL,
  expires_at   TEXT,
  dual_control_of TEXT REFERENCES approval(id)
);

-- ----------------------------------------------------------------- policy
CREATE TABLE IF NOT EXISTS policy_bundle (
  id           TEXT PRIMARY KEY,
  version      TEXT NOT NULL,
  rules_hash   TEXT NOT NULL,
  activated_at TEXT NOT NULL,
  active       INTEGER NOT NULL DEFAULT 0,
  source       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_decision (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenant(id),
  bundle_version TEXT NOT NULL,
  inputs_hash    TEXT NOT NULL,
  inputs         TEXT NOT NULL,
  effect         TEXT NOT NULL,
  rule_id        TEXT NOT NULL,
  reason         TEXT NOT NULL,
  decided_at     TEXT NOT NULL,
  subject_action_id TEXT
);

-- ------------------------------------------------------------------ tools
-- sandbox_ref is NOT NULL and non-empty by registration check: a write tool
-- without a sandbox twin cannot be registered (PRD section 20).
CREATE TABLE IF NOT EXISTS tool_manifest (
  id            TEXT PRIMARY KEY,
  version       TEXT NOT NULL,
  description   TEXT NOT NULL,
  input_schema  TEXT NOT NULL,
  output_schema TEXT NOT NULL,
  risk_class    TEXT NOT NULL,
  sandbox_ref   TEXT NOT NULL,
  egress_allowlist TEXT NOT NULL DEFAULT '[]',
  verification_method TEXT NOT NULL,
  rollback_tool_id TEXT,
  signature     TEXT NOT NULL,
  allowed_roles TEXT NOT NULL DEFAULT '[]',
  -- Risk inputs, mirrored from the in-process registry so the Governance
  -- screen can answer "why is this tool R4?" from the database alone.
  action_class  TEXT NOT NULL DEFAULT 'read',
  reversible    INTEGER NOT NULL DEFAULT 1,
  write         INTEGER NOT NULL DEFAULT 0,
  public_facing INTEGER NOT NULL DEFAULT 0,
  trust_domain  TEXT NOT NULL DEFAULT 'prod',
  prohibited    INTEGER NOT NULL DEFAULT 0
);

-- ------------------------------------------------------------------- audit
-- Append-only, hash-chained. seq is monotonic per tenant and entry_hash chains
-- prev_hash, so any deletion or edit breaks the chain verifiably.
CREATE TABLE IF NOT EXISTS audit_event (
  id          TEXT PRIMARY KEY,
  tenant_id   TEXT NOT NULL REFERENCES tenant(id),
  seq         INTEGER NOT NULL,
  workflow_id TEXT NOT NULL,
  at          TEXT NOT NULL,
  actor_id    TEXT NOT NULL,
  actor_kind  TEXT NOT NULL,
  kind        TEXT NOT NULL,
  subject_id  TEXT,
  payload     TEXT NOT NULL,
  prev_hash   TEXT NOT NULL,
  entry_hash  TEXT NOT NULL,
  UNIQUE (tenant_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_audit_workflow ON audit_event(workflow_id, seq);

-- --------------------------------------------------------- AI + model mgmt
CREATE TABLE IF NOT EXISTS model_version (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL,
  version       TEXT NOT NULL,
  envelope      TEXT NOT NULL DEFAULT '{}',
  registered_at TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS evidence_snapshot (
  id            TEXT PRIMARY KEY,
  incident_id   TEXT NOT NULL REFERENCES incident(id),
  taken_at      TEXT NOT NULL,
  evidence_ids  TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  body          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_run (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL REFERENCES tenant(id),
  workflow_id     TEXT NOT NULL,
  agent_id        TEXT NOT NULL,
  incident_id     TEXT REFERENCES incident(id),
  prompt_template TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  model_version   TEXT NOT NULL,
  evidence_snapshot_id TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  ended_at        TEXT,
  status          TEXT NOT NULL,
  tokens_in       INTEGER DEFAULT 0,
  tokens_out      INTEGER DEFAULT 0,
  cost_usd        REAL DEFAULT 0,
  degraded        INTEGER NOT NULL DEFAULT 0,
  output          TEXT,
  claim_ids       TEXT NOT NULL DEFAULT '[]'
);

-- ------------------------------------------------------------- simulation
CREATE TABLE IF NOT EXISTS simulation_run (
  id            TEXT PRIMARY KEY,
  scenario      TEXT NOT NULL,
  base_snapshot TEXT,
  seed          INTEGER NOT NULL,
  overrides     TEXT NOT NULL DEFAULT '{}',
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  results_hash  TEXT,
  results       TEXT,
  trust_domain  TEXT NOT NULL DEFAULT 'sim'
);

-- ------------------------------------------------------------ field + public
CREATE TABLE IF NOT EXISTS work_order (
  id           TEXT PRIMARY KEY,
  tenant_id    TEXT NOT NULL REFERENCES tenant(id),
  incident_id  TEXT REFERENCES incident(id),
  action_id    TEXT REFERENCES action(id),
  title        TEXT NOT NULL,
  instructions TEXT NOT NULL,
  asset_id     TEXT REFERENCES asset(id),
  priority     INTEGER NOT NULL DEFAULT 3,
  status       TEXT NOT NULL DEFAULT 'open',
  assigned_to  TEXT,
  created_at   TEXT NOT NULL,
  closed_at    TEXT,
  field_confirmation TEXT
);

CREATE TABLE IF NOT EXISTS alert_publication (
  id           TEXT PRIMARY KEY,
  incident_id  TEXT NOT NULL REFERENCES incident(id),
  cap_xml      TEXT NOT NULL,
  authority    TEXT NOT NULL,
  channel      TEXT NOT NULL,
  version      INTEGER NOT NULL DEFAULT 1,
  status       TEXT NOT NULL,
  published_at TEXT,
  disclosure_delay_s INTEGER NOT NULL DEFAULT 300
);

-- Cameras whose feeds are analysed. `authorized_by` is NOT NULL on purpose:
-- pointing an analyser at a feed is a decision someone has to own.
CREATE TABLE IF NOT EXISTS camera (
  id            TEXT PRIMARY KEY,
  tenant_id     TEXT NOT NULL REFERENCES tenant(id),
  name          TEXT NOT NULL,
  stream_url    TEXT NOT NULL,
  lat           REAL NOT NULL,
  lon           REAL NOT NULL,
  road_segment  TEXT,
  enabled       INTEGER NOT NULL DEFAULT 1,
  authorized_by TEXT NOT NULL,
  sample_fps    REAL NOT NULL DEFAULT 3.0,
  tuning_json   TEXT,
  registered_at TEXT NOT NULL,
  last_ok_at    TEXT,
  last_error    TEXT
);

-- -------------------------------------------------------- emergency response
CREATE TABLE IF NOT EXISTS registered_device (
  id                  TEXT PRIMARY KEY,
  tenant_id           TEXT NOT NULL REFERENCES tenant(id),
  user_id             TEXT,
  fcm_token           TEXT NOT NULL UNIQUE,
  device_type         TEXT NOT NULL DEFAULT 'web',
  last_lat            REAL,
  last_lon            REAL,
  opt_in_emergency    INTEGER NOT NULL DEFAULT 1,
  permissions_granted INTEGER NOT NULL DEFAULT 1,
  registered_at       TEXT NOT NULL,
  last_seen_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emergency_dispatch (
  id                  TEXT PRIMARY KEY,
  tenant_id           TEXT NOT NULL REFERENCES tenant(id),
  incident_id         TEXT NOT NULL REFERENCES incident(id),
  service_type        TEXT NOT NULL, -- 'ambulance' | 'police' | 'fire' | 'disaster_response'
  severity            TEXT NOT NULL,
  latitude            REAL NOT NULL,
  longitude           REAL NOT NULL,
  road_segment        TEXT,
  evidence_ids        TEXT NOT NULL DEFAULT '[]',
  status              TEXT NOT NULL DEFAULT 'submitted', -- 'submitted' | 'awaiting_confirmation' | 'confirmed' | 'failed_escalated'
  external_ref        TEXT,
  requesting_authority TEXT NOT NULL,
  approved_by         TEXT REFERENCES principal(id),
  eta_minutes         INTEGER,
  hazards_reported    TEXT NOT NULL DEFAULT '[]',
  created_at          TEXT NOT NULL,
  confirmed_at        TEXT,
  response_payload    TEXT
);

CREATE TABLE IF NOT EXISTS emergency_notification (
  id           TEXT PRIMARY KEY,
  tenant_id    TEXT NOT NULL REFERENCES tenant(id),
  incident_id  TEXT NOT NULL REFERENCES incident(id),
  channel      TEXT NOT NULL, -- 'fcm_push' | 'twilio_sms'
  recipient_id TEXT NOT NULL,
  recipient_category TEXT NOT NULL, -- 'public_geofence' | 'disaster_officer' | 'field_responder'
  message_text TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'sent', -- 'sent' | 'delivered' | 'failed'
  provider_ref TEXT,
  created_at   TEXT NOT NULL,
  delivered_at TEXT,
  failure_reason TEXT
);

-- People who asked to be warned. A row here is not permission:
-- `consent_verified` is, and delivery code must check it.
CREATE TABLE IF NOT EXISTS alert_subscriber (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenant(id),
  phone_e164       TEXT NOT NULL,
  language         TEXT NOT NULL DEFAULT 'en',
  last_lat         REAL,
  last_lon         REAL,
  consent_verified INTEGER NOT NULL DEFAULT 0,
  consent_source   TEXT,
  active           INTEGER NOT NULL DEFAULT 1,
  registered_at    TEXT NOT NULL,
  last_seen_at     TEXT,
  UNIQUE(tenant_id, phone_e164)
);

CREATE TABLE IF NOT EXISTS emergency_contact (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenant(id),
  name             TEXT NOT NULL,
  role             TEXT NOT NULL,
  phone_e164       TEXT NOT NULL,
  consent_verified INTEGER NOT NULL DEFAULT 1,
  active           INTEGER NOT NULL DEFAULT 1
);
