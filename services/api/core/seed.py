"""Idempotent database seeder. Run from the repo root:

    python -m services.api.core.seed        # standalone
    # or automatically at API boot via main.py lifespan

Seeds the live Vijayawada demo city with:
- Tenant & Zero-trust principals
- Ingestion connectors & active SLAs
- Physical assets & topological dependencies
- Real ingested events & minted evidence
- Active incidents detected by deterministic rules
- Grounded claims bound to verified evidence
- Forecasts & envelopes
- Candidate plans & governed tool actions
- Immutable cryptographic audit chain
- Field work orders
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from services.api.core import audit, claims, db, ingest, policy, repo
from services.api.models import EventIn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode()).hexdigest()[:16]


TENANT = "ten_vijayawada"
PRINCIPALS = [
    ("p_operator", "Ops Controller", "operator", "prod"),
    ("p_approver", "District Collector", "approver", "prod"),
    ("p_auditor", "Audit Reviewer", "auditor", "prod"),
    ("p_admin", "System Admin", "admin", "prod"),
    ("p_agent", "AI Pipeline", "agent", "prod"),
    ("p_sim", "Simulation Runner", "agent", "sim"),
]

CONNECTORS = [
    ("conn_hydro_scada", "Hydrology SCADA", "statutory", 120),
    ("conn_imd", "IMD nowcast feed", "certified", 300),
    ("conn_scada_pumps", "Pump station SCADA", "certified", 120),
    ("conn_cctv", "Traffic CCTV vision", "verified", 180),
    ("conn_citizen", "Citizen reports", "crowdsourced", 900),
    ("conn_sat", "Sentinel-1 flood extent", "certified", 3600),
    ("conn_tomtom_traffic", "Traffic Speed Telemetry", "verified", 180),
    ("conn_traffic_cam_01", "Municipal CCTV Collision Detector", "verified", 60),
]

ASSETS = [
    ("ast_pump_p12", "pump_station", "Ajit Singh Nagar pump house", 80.6338, 16.5261, 3, "water",
     {"units_running": 2, "units_total": 4, "capacity_m3s": 24.0}),
    ("ast_gate_bd04", "gate", "Budameru gate BD-04", 80.6113, 16.5498, 5, "water",
     {"position_pct": 100, "stage_m": 4.82, "threshold_m": 4.40}),
    ("ast_sub_pk3", "substation", "Payakapuram substation", 80.6189, 16.5361, 5, "power",
     {"energised": True, "water_level_m": 0.35, "cutoff_threshold_m": 0.80}),
    ("ast_road_rr1", "road", "Ramavarappadu Ring", 80.6702, 16.5195, 4, "transport",
     {"lanes_open": 2, "lanes_total": 4, "flood_depth_cm": 25}),
    ("ast_pump_p08", "pump_station", "Ramavarappadu pump house", 80.6695, 16.5180, 3, "water",
     {"units_running": 3, "units_total": 3}),
    ("ast_bund_east", "bund", "Eastern bund section A", 80.6250, 16.5400, 4, "water",
     {"condition": "monitoring", "freeboard_m": 0.65}),
]

DEPS = [
    ("ast_gate_bd04", "ast_pump_p12", "drains_to"),
    ("ast_gate_bd04", "ast_sub_pk3", "floods"),
    ("ast_sub_pk3", "ast_road_rr1", "powers"),
    ("ast_pump_p12", "ast_bund_east", "protects"),
]

TOOLS = [
    ("tool.pump.set_capacity", "Set pump station unit count", "R2",
     {"asset_id": {"type": "string"}, "units": {"type": "integer"}},
     {"units_running": {"type": "integer"}},
     "pump", "read-back after 60 s", "tool.pump.set_capacity", True),
    ("tool.gate.set_position", "Set gate position percentage", "R3",
     {"asset_id": {"type": "string"}, "position_pct": {"type": "integer"}},
     {"position_pct": {"type": "integer"}},
     "gate", "read-back within 120 s", "tool.gate.set_position", True),
    ("tool.diversion.activate", "Activate traffic diversion route", "R3",
     {"route_id": {"type": "string"}, "reason": {"type": "string"}},
     {"active": {"type": "boolean"}},
     "diversion", "read-back within 60 s", "tool.diversion.deactivate", True),
    ("tool.public.siren", "Activate public warning siren", "R5",
     {"zone": {"type": "string"}, "message_id": {"type": "string"}},
     {"activated": {"type": "boolean"}},
     "siren", "citizen confirmation", None, False),
    ("forecast.run", "Run the seeded hydrology forecast for an asset", "R1",
     {"asset_id": {"type": "string"}, "horizon_min": {"type": "integer"}, "seed": {"type": "integer"}},
     {"median": {"type": "number"}, "p10": {"type": "number"}, "p90": {"type": "number"}},
     "forecast_sandbox", "deterministic replay", None, True),
    ("twin.query", "Query digital twin dependency graph", "R0",
     {"asset_id": {"type": "string"}, "depth": {"type": "integer"}},
     {"nodes": {"type": "array"}, "edges": {"type": "array"}},
     "twin_sandbox", "deterministic", None, True),
]


def ensure_emergency_tables_seeded() -> None:
    now = _now()
    with db.tx() as c:
        for cid, name, trust, sla in CONNECTORS:
            c.execute(
                "INSERT OR IGNORE INTO connector(id,tenant_id,name,trust_tier,contract_version,freshness_sla_s,owner,quality_score) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (cid, TENANT, name, trust, "1.0.0", sla, "Auralis Command", 1.0),
            )
        c.execute(
            "INSERT OR IGNORE INTO emergency_contact(id, tenant_id, name, role, phone_e164, consent_verified, active) "
            "VALUES(?,?,?,?,?,?,?)",
            ("cnt_disaster_01", TENANT, "District Disaster Management Officer", "disaster_officer", "+919876543210", 1, 1),
        )
        c.execute(
            "INSERT OR IGNORE INTO emergency_contact(id, tenant_id, name, role, phone_e164, consent_verified, active) "
            "VALUES(?,?,?,?,?,?,?)",
            ("cnt_traffic_01", TENANT, "Traffic Police Control Room", "traffic_police", "+919876543211", 1, 1),
        )
        c.execute(
            "INSERT OR IGNORE INTO registered_device(id, tenant_id, user_id, fcm_token, device_type, last_lat, last_lon, opt_in_emergency, permissions_granted, registered_at, last_seen_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("dev_vja_001", TENANT, "p_operator", "fcm_token_vja_responder_01", "mobile_pwa", 16.5062, 80.6480, 1, 1, now, now),
        )


def ensure_seeded() -> None:
    """Seed the database with the live operational city model if empty."""
    ensure_emergency_tables_seeded()
    conn = db.get_conn()
    row = conn.execute("SELECT COUNT(*) c FROM incident").fetchone()
    if row and row["c"] > 0:
        return  # already fully seeded with operational data

    now = _now()
    with db.tx() as c:
        # tenant
        c.execute(
            "INSERT OR IGNORE INTO tenant(id,name,jurisdiction,data_region,created_at) "
            "VALUES(?,?,?,?,?)",
            (TENANT, "Vijayawada", "Andhra Pradesh, IN", "ap-south", now),
        )

        # principals
        for pid, name, role, td in PRINCIPALS:
            c.execute(
                "INSERT OR IGNORE INTO principal(id,tenant_id,display_name,role,trust_domain,status) "
                "VALUES(?,?,?,?,?,?)",
                (pid, TENANT, name, role, td, "active"),
            )

        # connectors
        for cid, cname, tier, sla in CONNECTORS:
            c.execute(
                "INSERT OR IGNORE INTO connector(id,tenant_id,name,trust_tier,"
                "contract_version,freshness_sla_s,owner,last_seen_at) VALUES(?,?,?,?,?,?,?,?)",
                (cid, TENANT, cname, tier, "2.1.0", sla, "data-eng", now),
            )

        # assets
        for aid, kind, name, lon, lat, crit, dept, state in ASSETS:
            geom = json.dumps({"type": "Point", "coordinates": [lon, lat]})
            c.execute(
                "INSERT OR IGNORE INTO asset(id,tenant_id,kind,name,geometry,criticality,"
                "owner_dept,current_state,reported_state,desired_state,geometry_accuracy_m) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (aid, TENANT, kind, name, geom, crit, dept,
                 json.dumps(state), "{}", "{}", 5.0),
            )

        # dependencies
        for dep, on, rel in DEPS:
            c.execute(
                "INSERT OR IGNORE INTO asset_dependency(dependent_id,depends_on_id,relation) "
                "VALUES(?,?,?)",
                (dep, on, rel),
            )

        # policy bundle
        bundle_src = "policies/bundle_v3.0.7.py"
        bundle_hash = _hash(bundle_src)
        c.execute(
            "INSERT OR IGNORE INTO policy_bundle(id,version,rules_hash,activated_at,active,source) "
            "VALUES(?,?,?,?,?,?)",
            ("pb_3_0_7", "3.0.7", bundle_hash, now, 1, bundle_src),
        )

        # tool manifests
        for tid, desc, risk, inp, out, sandbox, verify, rollback, reversible in TOOLS:
            is_write = risk not in ("R0", "R1")
            is_public = risk in ("R4", "R5")
            c.execute(
                "INSERT OR IGNORE INTO tool_manifest("
                "id,version,description,input_schema,output_schema,risk_class,"
                "sandbox_ref,egress_allowlist,verification_method,rollback_tool_id,"
                "signature,allowed_roles,action_class,reversible,write,public_facing,"
                "trust_domain,prohibited) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, "1.0.0", desc,
                 json.dumps({"type": "object", "properties": inp}),
                 json.dumps({"type": "object", "properties": out}),
                 risk, f"sandbox.{sandbox}", "[]", verify,
                 rollback, _hash(tid), '["operator","approver","admin"]',
                 "write" if is_write else "read",
                 1 if reversible else 0,
                 1 if is_write else 0,
                 1 if is_public else 0,
                 "prod", 0),
            )

        # model versions
        for mid, mname, mkind in [
            ("mdl_routing_321", "routing", "forecast"),
            ("mdl_anomaly_100", "anomaly-detector", "detection"),
            ("mdl_travel_200", "travel-time", "prediction"),
        ]:
            c.execute(
                "INSERT OR IGNORE INTO model_version(id,name,kind,version,envelope,registered_at,status) "
                "VALUES(?,?,?,?,?,?,?)",
                (mid, mname, mkind, "3.2.1", '{"rain_mm_hr":[0,200],"water_level_m":[0,10]}',
                 now, "active"),
            )

    # ------------------------------------------------ Ingest Live Events
    # 1. Gauge overtopping event (triggers incident detection)
    evt_gauge = EventIn(
        connector_id="conn_hydro_scada",
        kind="water_level",
        event_time=now,
        payload={"asset_id": "ast_gate_bd04", "level_m": 4.82, "flow_m3s": 1420.0},
        geometry={"type": "Point", "coordinates": [80.6113, 16.5498]},
    )
    acc_gauge = ingest.ingest_event(evt_gauge, "p_operator")

    # 2. Rainfall event
    evt_rain = EventIn(
        connector_id="conn_imd",
        kind="rainfall",
        event_time=now,
        payload={"rate_mm_h": 22.6, "accum_mm": 68.0},
        geometry={"type": "Point", "coordinates": [80.6200, 16.5300]},
    )
    acc_rain = ingest.ingest_event(evt_rain, "p_operator")

    # 3. Pump station state event
    evt_pump = EventIn(
        connector_id="conn_scada_pumps",
        kind="asset_state",
        event_time=now,
        payload={"asset_id": "ast_pump_p12", "units_running": 2, "units_total": 4},
        geometry={"type": "Point", "coordinates": [80.6338, 16.5261]},
    )
    acc_pump = ingest.ingest_event(evt_pump, "p_operator")

    # 4. Traffic blockage event
    evt_traffic = EventIn(
        connector_id="conn_cctv",
        kind="traffic_flow",
        event_time=now,
        payload={"flow_vph": 450.0, "speed_kph": 8.0, "baseline_vph": 3200.0},
        geometry={"type": "Point", "coordinates": [80.6702, 16.5195]},
    )
    acc_traffic = ingest.ingest_event(evt_traffic, "p_operator")

    # 5. Citizen report
    evt_citizen = EventIn(
        connector_id="conn_citizen",
        kind="water_level",
        event_time=now,
        payload={"level_m": 0.45, "note": "Water entering homes near Payakapuram"},
        geometry={"type": "Point", "coordinates": [80.6231, 16.5324]},
    )
    acc_citizen = ingest.ingest_event(evt_citizen, "p_operator")

    # Resolve active incident id
    conn = db.get_conn()
    inc_row = conn.execute("SELECT id FROM incident LIMIT 1").fetchone()
    inc_id = inc_row["id"] if inc_row else "inc_budameru_01"

    # Update incident state to awaiting_approval
    with db.tx() as c:
        c.execute(
            "UPDATE incident SET title=?, incident_class=?, severity=?, state=?, asset_ids=? WHERE id=?",
            ("Budameru rivulet overtopping at Payakapuram", "flood.urban", "critical",
             "awaiting_approval", json.dumps(["ast_gate_bd04", "ast_pump_p12", "ast_sub_pk3"]), inc_id),
        )

    # ------------------------------------------------ Assert Grounded Claims
    ev_ids = [e for e in [acc_gauge.evidence_id, acc_rain.evidence_id, acc_pump.evidence_id] if e]
    if acc_gauge.evidence_id:
        claims.create_claim(
            TENANT,
            "Budameru stage at gauge BD-04 is 4.82 m, 0.42 m above overtopping threshold.",
            "gauge:BD-04",
            "stage_m",
            "4.82",
            "fact",
            [acc_gauge.evidence_id],
            "evidence-compiler",
            "agent",
            incident_id=inc_id,
            confidence_basis="statutory gauge, 60s cadence",
        )

    if acc_gauge.evidence_id and acc_rain.evidence_id:
        claims.create_claim(
            TENANT,
            "Stage is forecast to peak between 5.3 m and 6.1 m within 180 minutes.",
            "gauge:BD-04",
            "peak_stage_m",
            "5.7",
            "forecast",
            [acc_gauge.evidence_id, acc_rain.evidence_id],
            "forecast-agent",
            "agent",
            incident_id=inc_id,
            confidence_basis="routing model v3.2, p10-p90 envelope",
            uncertainty={"lower": 5.3, "upper": 6.1, "unit": "m"},
        )

    if acc_pump.evidence_id and acc_gauge.evidence_id:
        claims.create_claim(
            TENANT,
            "Bring pump station P-12 to full capacity and pre-close gate BD-04 before forecast peak.",
            "plan:pln_budameru_a",
            "recommends",
            "pump_capacity_full",
            "recommendation",
            [acc_pump.evidence_id, acc_gauge.evidence_id],
            "planner-agent",
            "agent",
            incident_id=inc_id,
            confidence_basis="objective: minimise premises inundated",
        )

    # ------------------------------------------------ Seed Forecast
    with db.tx() as c:
        fc_val = {
            "median": 5.7,
            "p10": 5.3,
            "p90": 6.1,
            "unit": "m",
            "series": [
                {"t": 0, "median": 4.82, "p10": 4.82, "p90": 4.82},
                {"t": 60, "median": 5.21, "p10": 5.05, "p90": 5.4},
                {"t": 120, "median": 5.52, "p10": 5.2, "p90": 5.83},
                {"t": 180, "median": 5.7, "p10": 5.3, "p90": 6.1},
            ],
        }
        c.execute(
            "INSERT OR IGNORE INTO forecast(id,incident_id,model_version,horizon_min,produced_at,value_json,in_envelope,evidence_ids) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("fc_stage_180", inc_id, "routing-3.2.1", 180, now, json.dumps(fc_val), 1, json.dumps(ev_ids)),
        )

    # ------------------------------------------------ Seed Plan & Actions
    plan_id = "pln_budameru_a"
    with db.tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO plan(id,tenant_id,incident_id,title,rationale,created_at,created_by,status,evidence_ids,validation,objective_score) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, TENANT, inc_id,
             "Hold the Payakapuram line before the 180-minute peak",
             "Maximise drainage capacity while stage is below bund crest, then isolate the rivulet ahead of peak.",
             now, "planner-agent", "blocked",
             json.dumps(ev_ids),
             json.dumps({"grounded": True, "sandbox_pass": True, "conflicts": 0}),
             json.dumps({"premises_protected": 1240, "cost_index": 0.34, "time_to_effect_min": 22})),
        )

        # Action 1: Pump expansion (Verified)
        c.execute(
            "INSERT OR IGNORE INTO action(id,plan_id,tool_id,sequence,args,target_asset_id,risk_tier,blast_radius,reversible,status,idempotency_key,executed_at,verification,verification_method) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("act_pump_full", plan_id, "tool.pump.set_capacity", 1,
             json.dumps({"asset_id": "ast_pump_p12", "units": 4}),
             "ast_pump_p12", "R2", 18, 1, "verified", "act_web_9c1f2a", now,
             "SUCCESS", "read-back after 60 s"),
        )

        # Action 2: Gate closure (Proposed / Requires Approval)
        c.execute(
            "INSERT OR IGNORE INTO action(id,plan_id,tool_id,sequence,args,target_asset_id,risk_tier,blast_radius,reversible,status,verification_method) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("act_gate_close", plan_id, "tool.gate.set_position", 2,
             json.dumps({"asset_id": "ast_gate_bd04", "position_pct": 0}),
             "ast_gate_bd04", "R4", 1240, 1, "proposed", "read-back within 120 s"),
        )

        # Policy decision for Gate action
        c.execute(
            "INSERT OR IGNORE INTO policy_decision(id,tenant_id,bundle_version,inputs_hash,inputs,effect,rule_id,reason,decided_at,subject_action_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("pd_gate_close", TENANT, "3.0.7", "sha256:31be77d",
             json.dumps({"risk_tier": "R4", "asset_criticality": 5, "blast_radius": 1240, "public_facing": True}),
             "require_approval", "RULE.GATE.CLOSE.R4",
             "Closing BD-04 affects 1,240 premises downstream and is public-facing. Named approver required.",
             now, "act_gate_close"),
        )

        # Work orders
        c.execute(
            "INSERT OR IGNORE INTO work_order(id,tenant_id,incident_id,action_id,title,instructions,asset_id,priority,status,assigned_to,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("wo_101", TENANT, inc_id, "act_gate_close",
             "Verify gate BD-04 seal after closure",
             "Inspect physical gate seating and check for silt buildup around track.",
             "ast_gate_bd04", 1, "queued", "field_team_1", now),
        )
        c.execute(
            "INSERT OR IGNORE INTO work_order(id,tenant_id,incident_id,action_id,title,instructions,asset_id,priority,status,assigned_to,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("wo_102", TENANT, inc_id, "act_pump_full",
             "Sandbag substation perimeter, Payakapuram",
             "Deploy 200 sandbags along eastern boundary wall facing canal.",
             "ast_sub_pk3", 2, "in_progress", "field_team_1", now),
        )
        # Emergency Contacts (Disaster response and Traffic control)
        c.execute(
            "INSERT OR IGNORE INTO emergency_contact(id, tenant_id, name, role, phone_e164, consent_verified, active) "
            "VALUES(?,?,?,?,?,?,?)",
            ("cnt_disaster_01", TENANT, "District Disaster Management Officer", "disaster_officer", "+919876543210", 1, 1),
        )
        c.execute(
            "INSERT OR IGNORE INTO emergency_contact(id, tenant_id, name, role, phone_e164, consent_verified, active) "
            "VALUES(?,?,?,?,?,?,?)",
            ("cnt_traffic_01", TENANT, "Traffic Police Control Room", "traffic_police", "+919876543211", 1, 1),
        )
        # Sample Consenting Registered Device (Benz Circle / MG Road corridor)
        c.execute(
            "INSERT OR IGNORE INTO registered_device(id, tenant_id, user_id, fcm_token, device_type, last_lat, last_lon, opt_in_emergency, permissions_granted, registered_at, last_seen_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("dev_vja_001", TENANT, "p_operator", "fcm_token_vja_responder_01", "mobile_pwa", 16.5062, 80.6480, 1, 1, now, now),
        )

    # ------------------------------------------------ Append Immutable Audit Chain
    audit.append(TENANT, f"wf_{inc_id}", "conn_hydro_scada", "service", "event.ingested", acc_gauge.evidence_id,
                 {"stage_m": 4.82, "source": "Gauge BD-04"})
    audit.append(TENANT, f"wf_{inc_id}", "detector.water_level", "service", "incident.detected", inc_id,
                 {"severity": "critical", "threshold_m": 4.40})
    audit.append(TENANT, f"wf_{inc_id}", "evidence-compiler", "agent", "claim.asserted", "cl_stage_now",
                 {"grounded": True, "evidence_id": acc_gauge.evidence_id})
    audit.append(TENANT, f"wf_{inc_id}", "planner-agent", "agent", "plan.generated", plan_id,
                 {"actions_count": 2, "objective": "minimise_inundation"})
    audit.append(TENANT, f"wf_{inc_id}", "policy.engine", "service", "policy.evaluated", "act_gate_close",
                 {"effect": "require_approval", "rule_id": "RULE.GATE.CLOSE.R4"})

    print(f"[seed] Vijayawada LIVE operational city initialized: Incident {inc_id} with {len(ev_ids)} evidence rows, grounded claims, and verified audit chain.")


if __name__ == "__main__":
    import os
    from pathlib import Path

    repo_dir = Path(__file__).resolve().parents[3]
    db_path = os.environ.get("AURALIS_DB", str(repo_dir / "auralis.db"))
    db.init_db(db_path)
    ensure_seeded()
