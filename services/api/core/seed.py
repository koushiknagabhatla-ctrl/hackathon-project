"""Idempotent database seeder. Run from the repo root:

    python scripts/seed_db.py        # standalone
    # or automatically at API boot via main.py lifespan

Seeds one demo tenant (Vijayawada, AP), principals, connectors, assets,
dependencies, a policy bundle, tool manifests and model versions.
Every INSERT uses INSERT OR IGNORE so re-running is safe.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from services.api.core import db


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
]

ASSETS = [
    ("ast_pump_p12", "pump_station", "Ajit Singh Nagar pump house", 80.6338, 16.5261, 3, "water",
     {"units_running": 2, "units_total": 4}),
    ("ast_gate_bd04", "gate", "Budameru gate BD-04", 80.6113, 16.5498, 5, "water",
     {"position_pct": 100}),
    ("ast_sub_pk3", "substation", "Payakapuram substation", 80.6189, 16.5361, 5, "power",
     {"energised": True}),
    ("ast_road_rr1", "road", "Ramavarappadu Ring", 80.6702, 16.5195, 4, "transport",
     {"lanes_open": 4, "lanes_total": 4}),
    ("ast_pump_p08", "pump_station", "Ramavarappadu pump house", 80.6695, 16.5180, 3, "water",
     {"units_running": 3, "units_total": 3}),
    ("ast_bund_east", "bund", "Eastern bund section A", 80.6250, 16.5400, 4, "water",
     {"condition": "good"}),
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


def ensure_seeded() -> None:
    """Seed the database if empty. Fully idempotent."""
    conn = db.get_conn()
    row = conn.execute("SELECT COUNT(*) c FROM tenant").fetchone()
    if row and row["c"] > 0:
        return  # already seeded

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

    print(f"[seed] Vijayawada demo city seeded ({len(ASSETS)} assets, "
          f"{len(CONNECTORS)} connectors, {len(TOOLS)} tools)")


if __name__ == "__main__":
    import os
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    db_path = os.environ.get("AURALIS_DB", str(repo / "auralis.db"))
    db.init_db(db_path)
    ensure_seeded()
