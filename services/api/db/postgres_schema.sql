-- Auralis operational schema — PostgreSQL 17 + PostGIS 3.3.
-- Port of services/api/schema.sql (SQLite). Applied by
-- scripts/migrate_to_postgres.py; every statement is idempotent, so running it
-- twice is a no-op. See docs/adr/0021-postgresql-postgis-as-operational-database.md.
--
-- What changed from the SQLite DDL, and why:
--   * TEXT timestamps        -> timestamptz
--   * INTEGER booleans       -> boolean
--   * JSON string columns    -> jsonb (+ GIN where a query reaches inside them)
--   * GeoJSON TEXT geometry  -> kept as TEXT, PLUS a STORED generated
--                               geometry(Geometry,4326) column with a GIST index.
--   * audit_event            -> append-only enforced by trigger, not convention
--   * tenant-scoped tables   -> row level security keyed on a GUC
--
-- Why geometry is a generated column rather than a replaced column: the GeoJSON
-- text is load-bearing. `evidence.integrity_hash` is a sha256 over the geometry
-- STRING (core/evidence.py::verify_integrity), and ADR-0020 makes "geometry is
-- GeoJSON in EPSG:4326, readable without this application" part of the exit
-- drill's pass condition. Replacing the text with WKB would silently invalidate
-- every stored integrity hash and regress the exit drill. The generated column
-- gives the thing PostGIS is actually for — an indexed spatial predicate you can
-- push into the query plan (core/geo.py::dwithin_sql) — and cannot drift from
-- the text, because Postgres derives it. Invalid GeoJSON is rejected at INSERT
-- by ST_GeomFromGeoJSON, which is validation this build did not previously have.
--
-- PostGIS may live in schema "extensions" (Supabase) or "public". Everything
-- below is written unqualified and relies on search_path including it; the
-- migration runner sets that up.

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------- tenancy
CREATE TABLE IF NOT EXISTS tenant (
  id            text PRIMARY KEY,
  name          text NOT NULL,
  jurisdiction  text NOT NULL,
  data_region   text NOT NULL DEFAULT 'eu-west',
  created_at    timestamptz NOT NULL
);

-- humans and workloads share one identity model
CREATE TABLE IF NOT EXISTS principal (
  id            text PRIMARY KEY,
  tenant_id     text NOT NULL REFERENCES tenant(id),
  display_name  text NOT NULL,
  role          text NOT NULL,
  authority     text,
  spiffe_id     text,
  trust_domain  text NOT NULL DEFAULT 'prod',
  status        text NOT NULL DEFAULT 'active'
);

-- ------------------------------------------------------------ connectors
CREATE TABLE IF NOT EXISTS connector (
  id               text PRIMARY KEY,
  tenant_id        text NOT NULL REFERENCES tenant(id),
  name             text NOT NULL,
  trust_tier       text NOT NULL,
  contract_version text NOT NULL,
  freshness_sla_s  integer NOT NULL,
  dpia_status      text NOT NULL DEFAULT 'cleared',
  owner            text NOT NULL,
  quality_score    double precision NOT NULL DEFAULT 1.0,
  last_seen_at     timestamptz
);

-- ------------------------------------------------------------------ twin
CREATE TABLE IF NOT EXISTS asset (
  id             text PRIMARY KEY,
  tenant_id      text NOT NULL REFERENCES tenant(id),
  kind           text NOT NULL,
  name           text NOT NULL,
  geometry       text NOT NULL,
  geom           geometry(Geometry, 4326)
                 GENERATED ALWAYS AS (ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326)) STORED,
  criticality    integer NOT NULL,
  owner_dept     text NOT NULL,
  current_state  jsonb NOT NULL DEFAULT '{}'::jsonb,
  reported_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  desired_state  jsonb NOT NULL DEFAULT '{}'::jsonb,
  permitted_actions jsonb NOT NULL DEFAULT '[]'::jsonb,
  maintenance_window text,
  geometry_accuracy_m double precision DEFAULT 5.0
);
CREATE INDEX IF NOT EXISTS idx_asset_geom ON asset USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_asset_tenant ON asset(tenant_id);

CREATE TABLE IF NOT EXISTS asset_dependency (
  dependent_id  text NOT NULL REFERENCES asset(id),
  depends_on_id text NOT NULL REFERENCES asset(id),
  relation      text NOT NULL,
  PRIMARY KEY (dependent_id, depends_on_id)
);
CREATE INDEX IF NOT EXISTS idx_dep_depends_on ON asset_dependency(depends_on_id);

-- ------------------------------------------------------- ingest / events
-- body stays text: content_hash is a sha256 over these exact bytes.
CREATE TABLE IF NOT EXISTS raw_payload (
  content_hash text PRIMARY KEY,
  connector_id text NOT NULL REFERENCES connector(id),
  received_at  timestamptz NOT NULL,
  body         text NOT NULL
);

CREATE TABLE IF NOT EXISTS event (
  id              text PRIMARY KEY,
  tenant_id       text NOT NULL REFERENCES tenant(id),
  connector_id    text NOT NULL REFERENCES connector(id),
  source_event_id text,
  content_hash    text REFERENCES raw_payload(content_hash),
  kind            text NOT NULL,
  event_time      timestamptz NOT NULL,
  ingest_time     timestamptz NOT NULL,
  geometry        text,
  geom            geometry(Geometry, 4326)
                  GENERATED ALWAYS AS (ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326)) STORED,
  payload         jsonb NOT NULL,
  schema_version  text NOT NULL,
  quarantined     boolean NOT NULL DEFAULT false,
  quarantine_reason text,
  UNIQUE (connector_id, source_event_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_event_time ON event(event_time);
CREATE INDEX IF NOT EXISTS idx_event_geom ON event USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_event_payload ON event USING GIN (payload);
CREATE INDEX IF NOT EXISTS idx_event_connector_ingest ON event(connector_id, ingest_time);

-- --------------------------------------------------------------- incident
CREATE TABLE IF NOT EXISTS incident (
  id             text PRIMARY KEY,
  tenant_id      text NOT NULL REFERENCES tenant(id),
  title          text NOT NULL,
  incident_class text NOT NULL,
  severity       text NOT NULL,
  state          text NOT NULL,
  opened_at      timestamptz NOT NULL,
  closed_at      timestamptz,
  geometry       text,
  geom           geometry(Geometry, 4326)
                 GENERATED ALWAYS AS (ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326)) STORED,
  detector       text NOT NULL,
  evidence_ids   jsonb NOT NULL DEFAULT '[]'::jsonb,
  asset_ids      jsonb NOT NULL DEFAULT '[]'::jsonb,
  first_observation_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_incident_geom ON incident USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_incident_tenant_state ON incident(tenant_id, state);

-- ----------------------------------------------------- evidence + claims
CREATE TABLE IF NOT EXISTS evidence (
  id             text PRIMARY KEY,
  tenant_id      text NOT NULL REFERENCES tenant(id),
  connector_id   text NOT NULL REFERENCES connector(id),
  event_id       text REFERENCES event(id),
  evidence_class text NOT NULL,
  statement      text NOT NULL,
  value_json     jsonb NOT NULL,
  observed_at    timestamptz NOT NULL,
  expires_at     timestamptz NOT NULL,
  trust_tier     text NOT NULL,
  integrity_hash text NOT NULL,
  geometry       text,
  geom           geometry(Geometry, 4326)
                 GENERATED ALWAYS AS (ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326)) STORED,
  status         text NOT NULL DEFAULT 'valid',
  prov_activity  text,
  prov_derived_from jsonb DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_evidence_geom ON evidence USING GIST (geom);
-- repo.list_evidence / evidence.detect_conflicts reach into value_json->subject
CREATE INDEX IF NOT EXISTS idx_evidence_value ON evidence USING GIN (value_json);
CREATE INDEX IF NOT EXISTS idx_evidence_tenant_observed ON evidence(tenant_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS evidence_conflict (
  id           text PRIMARY KEY,
  tenant_id    text NOT NULL REFERENCES tenant(id),
  evidence_a   text NOT NULL REFERENCES evidence(id),
  evidence_b   text NOT NULL REFERENCES evidence(id),
  subject      text NOT NULL,
  detected_at  timestamptz NOT NULL,
  resolution   text NOT NULL DEFAULT 'unresolved',
  resolved_by_rule text,
  winner_evidence_id text REFERENCES evidence(id)
);

CREATE TABLE IF NOT EXISTS claim (
  id            text PRIMARY KEY,
  tenant_id     text NOT NULL REFERENCES tenant(id),
  incident_id   text REFERENCES incident(id),
  statement     text NOT NULL,
  subject       text NOT NULL,
  predicate     text NOT NULL,
  object        text NOT NULL,
  claim_class   text NOT NULL,
  valid_from    timestamptz NOT NULL,
  valid_to      timestamptz NOT NULL,
  evidence_ids  jsonb NOT NULL,
  confidence_basis text,
  uncertainty   jsonb,
  author        text NOT NULL,
  author_kind   text NOT NULL,
  status        text NOT NULL DEFAULT 'active',
  -- Invariant 1, as a database constraint rather than only a service check:
  -- a fact or forecast must cite at least one piece of evidence.
  CONSTRAINT claim_grounded CHECK (
    claim_class NOT IN ('fact', 'forecast') OR jsonb_array_length(evidence_ids) > 0
  )
);
CREATE INDEX IF NOT EXISTS idx_claim_incident ON claim(incident_id);

CREATE TABLE IF NOT EXISTS forecast (
  id            text PRIMARY KEY,
  incident_id   text NOT NULL REFERENCES incident(id),
  model_version text NOT NULL,
  horizon_min   integer NOT NULL,
  produced_at   timestamptz NOT NULL,
  value_json    jsonb NOT NULL,
  in_envelope   boolean NOT NULL DEFAULT true,
  envelope_note text,
  evidence_ids  jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- ------------------------------------------------------- plans + actions
CREATE TABLE IF NOT EXISTS plan (
  id            text PRIMARY KEY,
  tenant_id     text NOT NULL REFERENCES tenant(id),
  incident_id   text NOT NULL REFERENCES incident(id),
  title         text NOT NULL,
  rationale     text NOT NULL,
  created_at    timestamptz NOT NULL,
  created_by    text NOT NULL,
  status        text NOT NULL,
  evidence_ids  jsonb NOT NULL DEFAULT '[]'::jsonb,
  claim_ids     jsonb NOT NULL DEFAULT '[]'::jsonb,
  validation    jsonb NOT NULL DEFAULT '{}'::jsonb,
  objective_score jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_plan_incident ON plan(incident_id);

CREATE TABLE IF NOT EXISTS action (
  id              text PRIMARY KEY,
  plan_id         text NOT NULL REFERENCES plan(id),
  tool_id         text NOT NULL,
  sequence        integer NOT NULL,
  args            jsonb NOT NULL,
  target_asset_id text REFERENCES asset(id),
  risk_tier       text NOT NULL,
  risk_inputs     jsonb NOT NULL DEFAULT '{}'::jsonb,
  blast_radius    integer NOT NULL DEFAULT 0,
  reversible      boolean NOT NULL DEFAULT true,
  rollback_tool_id text,
  status          text NOT NULL,
  idempotency_key text UNIQUE,
  policy_decision_id text,
  executed_at     timestamptz,
  intended_state  jsonb,
  actual_state    jsonb,
  verification    text,
  verification_method text,
  CONSTRAINT action_risk_tier CHECK (risk_tier IN ('R0','R1','R2','R3','R4','R5'))
);
CREATE INDEX IF NOT EXISTS idx_action_plan ON action(plan_id, sequence);

CREATE TABLE IF NOT EXISTS approval (
  id           text PRIMARY KEY,
  action_id    text NOT NULL REFERENCES action(id),
  plan_id      text NOT NULL REFERENCES plan(id),
  decision     text NOT NULL,
  approver_id  text NOT NULL REFERENCES principal(id),
  approver_authority text,
  rationale    text,
  decided_at   timestamptz NOT NULL,
  expires_at   timestamptz,
  dual_control_of text REFERENCES approval(id),
  -- CONTRACT.md "Approval vocabulary": 'confirmed' is written by the
  -- verification path and is evidence, never authorization.
  CONSTRAINT approval_decision CHECK (decision IN ('approved','denied','confirmed'))
);
CREATE INDEX IF NOT EXISTS idx_approval_action ON approval(action_id);

-- ----------------------------------------------------------------- policy
CREATE TABLE IF NOT EXISTS policy_bundle (
  id           text PRIMARY KEY,
  version      text NOT NULL,
  rules_hash   text NOT NULL,
  activated_at timestamptz NOT NULL,
  active       boolean NOT NULL DEFAULT false,
  source       text NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_decision (
  id             text PRIMARY KEY,
  tenant_id      text NOT NULL REFERENCES tenant(id),
  bundle_version text NOT NULL,
  inputs_hash    text NOT NULL,
  inputs         jsonb NOT NULL,
  effect         text NOT NULL,
  rule_id        text NOT NULL,
  reason         text NOT NULL,
  decided_at     timestamptz NOT NULL,
  subject_action_id text,
  CONSTRAINT policy_effect CHECK (effect IN ('allow','deny','require_approval'))
);
CREATE INDEX IF NOT EXISTS idx_policy_decision_tenant ON policy_decision(tenant_id, decided_at DESC);

-- ------------------------------------------------------------------ tools
-- sandbox_ref is NOT NULL and non-empty by registration check: a write tool
-- without a sandbox twin cannot be registered (PRD section 20, invariant 4).
CREATE TABLE IF NOT EXISTS tool_manifest (
  id            text PRIMARY KEY,
  version       text NOT NULL,
  description   text NOT NULL,
  input_schema  jsonb NOT NULL,
  output_schema jsonb NOT NULL,
  risk_class    text NOT NULL,
  sandbox_ref   text NOT NULL,
  egress_allowlist jsonb NOT NULL DEFAULT '[]'::jsonb,
  verification_method text NOT NULL,
  rollback_tool_id text,
  signature     text NOT NULL,
  allowed_roles jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- Risk inputs, mirrored from the in-process registry so the Governance
  -- screen can answer "why is this tool R4?" from the database alone.
  action_class  text NOT NULL DEFAULT 'read',
  reversible    boolean NOT NULL DEFAULT true,
  write         boolean NOT NULL DEFAULT false,
  public_facing boolean NOT NULL DEFAULT false,
  trust_domain  text NOT NULL DEFAULT 'prod',
  prohibited    boolean NOT NULL DEFAULT false,
  CONSTRAINT tool_sandbox_twin_required CHECK (length(trim(sandbox_ref)) > 0)
);

-- ------------------------------------------------------------------- audit
-- Append-only, hash-chained. seq is monotonic per tenant and entry_hash chains
-- prev_hash, so any deletion or edit breaks the chain verifiably. In SQLite
-- "no UPDATE, no DELETE" was a convention; here it is a trigger.
CREATE TABLE IF NOT EXISTS audit_event (
  id          text PRIMARY KEY,
  tenant_id   text NOT NULL REFERENCES tenant(id),
  seq         bigint NOT NULL,
  workflow_id text NOT NULL,
  at          timestamptz NOT NULL,
  actor_id    text NOT NULL,
  actor_kind  text NOT NULL,
  kind        text NOT NULL,
  subject_id  text,
  payload     jsonb NOT NULL,
  prev_hash   text NOT NULL,
  entry_hash  text NOT NULL,
  UNIQUE (tenant_id, seq),
  CONSTRAINT audit_seq_positive CHECK (seq > 0),
  CONSTRAINT audit_hash_shape CHECK (entry_hash ~ '^[0-9a-f]{64}$' AND prev_hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS idx_audit_workflow ON audit_event(workflow_id, seq);
CREATE INDEX IF NOT EXISTS idx_audit_payload ON audit_event USING GIN (payload);

CREATE OR REPLACE FUNCTION auralis_audit_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
  RAISE EXCEPTION 'audit_event is append-only: % refused', TG_OP
    USING ERRCODE = 'restrict_violation',
          DETAIL  = 'Invariant 6: the ledger is hash-chained and immutable.',
          HINT    = 'Correct a mistake by appending a new entry, never by editing one.';
  RETURN NULL;
END;
$fn$;

DROP TRIGGER IF EXISTS trg_audit_no_update_delete ON audit_event;
CREATE TRIGGER trg_audit_no_update_delete
  BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION auralis_audit_append_only();

DROP TRIGGER IF EXISTS trg_audit_no_truncate ON audit_event;
CREATE TRIGGER trg_audit_no_truncate
  BEFORE TRUNCATE ON audit_event
  FOR EACH STATEMENT EXECUTE FUNCTION auralis_audit_append_only();

-- --------------------------------------------------------- AI + model mgmt
CREATE TABLE IF NOT EXISTS model_version (
  id            text PRIMARY KEY,
  name          text NOT NULL,
  kind          text NOT NULL,
  version       text NOT NULL,
  envelope      jsonb NOT NULL DEFAULT '{}'::jsonb,
  registered_at timestamptz NOT NULL,
  status        text NOT NULL DEFAULT 'active'
);

-- body stays text: snapshot_hash is a sha256 over these exact bytes.
CREATE TABLE IF NOT EXISTS evidence_snapshot (
  id            text PRIMARY KEY,
  incident_id   text NOT NULL REFERENCES incident(id),
  taken_at      timestamptz NOT NULL,
  evidence_ids  jsonb NOT NULL,
  snapshot_hash text NOT NULL,
  body          text NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_run (
  id              text PRIMARY KEY,
  tenant_id       text NOT NULL REFERENCES tenant(id),
  workflow_id     text NOT NULL,
  agent_id        text NOT NULL,
  incident_id     text REFERENCES incident(id),
  prompt_template text NOT NULL,
  prompt_version  text NOT NULL,
  model_version   text NOT NULL,
  evidence_snapshot_id text NOT NULL,
  started_at      timestamptz NOT NULL,
  ended_at        timestamptz,
  status          text NOT NULL,
  tokens_in       integer DEFAULT 0,
  tokens_out      integer DEFAULT 0,
  cost_usd        double precision DEFAULT 0,
  degraded        boolean NOT NULL DEFAULT false,
  output          jsonb,
  claim_ids       jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_agent_run_tenant ON agent_run(tenant_id);

-- ------------------------------------------------------------- simulation
-- No tenant_id: simulation is a separate trust domain (ADR-0008), not a tenant.
CREATE TABLE IF NOT EXISTS simulation_run (
  id            text PRIMARY KEY,
  scenario      text NOT NULL,
  base_snapshot text,
  seed          bigint NOT NULL,
  overrides     jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at    timestamptz NOT NULL,
  ended_at      timestamptz,
  results_hash  text,
  results       jsonb,
  trust_domain  text NOT NULL DEFAULT 'sim',
  CONSTRAINT simulation_is_sim CHECK (trust_domain = 'sim')
);

-- ------------------------------------------------------------ field + public
CREATE TABLE IF NOT EXISTS work_order (
  id           text PRIMARY KEY,
  tenant_id    text NOT NULL REFERENCES tenant(id),
  incident_id  text REFERENCES incident(id),
  action_id    text REFERENCES action(id),
  title        text NOT NULL,
  instructions text NOT NULL,
  asset_id     text REFERENCES asset(id),
  priority     integer NOT NULL DEFAULT 3,
  status       text NOT NULL DEFAULT 'open',
  assigned_to  text,
  created_at   timestamptz NOT NULL,
  closed_at    timestamptz,
  field_confirmation text
);
CREATE INDEX IF NOT EXISTS idx_work_order_tenant ON work_order(tenant_id, priority, created_at DESC);

CREATE TABLE IF NOT EXISTS alert_publication (
  id           text PRIMARY KEY,
  incident_id  text NOT NULL REFERENCES incident(id),
  cap_xml      text NOT NULL,
  authority    text NOT NULL,
  channel      text NOT NULL,
  version      integer NOT NULL DEFAULT 1,
  status       text NOT NULL,
  published_at timestamptz,
  disclosure_delay_s integer NOT NULL DEFAULT 300
);

-- -------------------------------------------------------- emergency response
CREATE TABLE IF NOT EXISTS registered_device (
  id                  text PRIMARY KEY,
  tenant_id           text NOT NULL REFERENCES tenant(id),
  user_id             text,
  fcm_token           text NOT NULL UNIQUE,
  device_type         text NOT NULL DEFAULT 'web',
  last_lat            double precision,
  last_lon            double precision,
  last_seen_point     geometry(Point, 4326)
                      GENERATED ALWAYS AS (
                        CASE WHEN last_lat IS NULL OR last_lon IS NULL THEN NULL
                             ELSE ST_SetSRID(ST_MakePoint(last_lon, last_lat), 4326) END
                      ) STORED,
  opt_in_emergency    boolean NOT NULL DEFAULT true,
  permissions_granted boolean NOT NULL DEFAULT true,
  registered_at       timestamptz NOT NULL,
  last_seen_at        timestamptz NOT NULL
);
-- adapters/fcm_push.py::find_nearby_registered_devices is the geofence query
CREATE INDEX IF NOT EXISTS idx_device_point ON registered_device USING GIST (last_seen_point);

CREATE TABLE IF NOT EXISTS emergency_dispatch (
  id                  text PRIMARY KEY,
  tenant_id           text NOT NULL REFERENCES tenant(id),
  incident_id         text NOT NULL REFERENCES incident(id),
  service_type        text NOT NULL,
  severity            text NOT NULL,
  latitude            double precision NOT NULL,
  longitude           double precision NOT NULL,
  location            geometry(Point, 4326)
                      GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) STORED,
  road_segment        text,
  evidence_ids        jsonb NOT NULL DEFAULT '[]'::jsonb,
  status              text NOT NULL DEFAULT 'submitted',
  external_ref        text,
  requesting_authority text NOT NULL,
  approved_by         text REFERENCES principal(id),
  eta_minutes         integer,
  hazards_reported    jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at          timestamptz NOT NULL,
  confirmed_at        timestamptz,
  response_payload    jsonb,
  CONSTRAINT dispatch_service_type CHECK (
    service_type IN ('ambulance','police','fire','disaster_response')),
  CONSTRAINT dispatch_status CHECK (
    status IN ('submitted','awaiting_confirmation','confirmed','failed_escalated',
               'blocked_simulation_barrier','blocked_outbound_disabled'))
);
CREATE INDEX IF NOT EXISTS idx_dispatch_location ON emergency_dispatch USING GIST (location);

CREATE TABLE IF NOT EXISTS emergency_notification (
  id           text PRIMARY KEY,
  tenant_id    text NOT NULL REFERENCES tenant(id),
  incident_id  text NOT NULL REFERENCES incident(id),
  channel      text NOT NULL,
  recipient_id text NOT NULL,
  recipient_category text NOT NULL,
  message_text text NOT NULL,
  status       text NOT NULL DEFAULT 'sent',
  provider_ref text,
  created_at   timestamptz NOT NULL,
  delivered_at timestamptz,
  failure_reason text
);

-- Consent is given by a person. consent_verified defaults FALSE here on
-- purpose: nothing may default a consent that nobody gave.
CREATE TABLE IF NOT EXISTS emergency_contact (
  id               text PRIMARY KEY,
  tenant_id        text NOT NULL REFERENCES tenant(id),
  name             text NOT NULL,
  role             text NOT NULL,
  phone_e164       text NOT NULL,
  consent_verified boolean NOT NULL DEFAULT false,
  active           boolean NOT NULL DEFAULT true
);

-- ------------------------------------------------------ row level security
-- Tenant isolation is a release gate (CONTRACT.md), so it is structural here
-- rather than only a required tenant_id argument in core/repo.py.
--
-- The policy reads a session GUC: core/db.py::set_tenant() issues
--   SET LOCAL auralis.tenant_id = '<tenant>'
-- and with no GUC set, current_setting(..., true) is NULL and every row is
-- invisible — fail closed, not fail open.
--
-- NOTE: Postgres exempts a table's OWNER from RLS unless FORCE is set. The
-- migration runner therefore also FORCEs it, so the same connection string that
-- runs the app is subject to the policy. See ADR-0021.
DO $rls$
DECLARE
  t text;
  tenant_tables text[] := ARRAY[
    'principal','connector','asset','event','incident','evidence',
    'evidence_conflict','claim','plan','policy_decision','audit_event',
    'agent_run','work_order','registered_device','emergency_dispatch',
    'emergency_notification','emergency_contact'
  ];
BEGIN
  FOREACH t IN ARRAY tenant_tables LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS auralis_tenant_isolation ON %I', t);
    EXECUTE format(
      'CREATE POLICY auralis_tenant_isolation ON %I'
      '  USING (tenant_id = current_setting(''auralis.tenant_id'', true))'
      '  WITH CHECK (tenant_id = current_setting(''auralis.tenant_id'', true))', t);
  END LOOP;
END
$rls$;

-- To create the least-privilege application role the app should actually
-- connect as, run this yourself with a password you generate. It is NOT in this
-- file and must never be committed:
--
--   CREATE ROLE auralis_app LOGIN PASSWORD '<generate-your-own>';
--   GRANT USAGE ON SCHEMA public TO auralis_app;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auralis_app;
--   REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM auralis_app;
--
-- auralis_app is not the table owner, so RLS binds it unconditionally.
