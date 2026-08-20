"""Lane A (data core) invariants. Run from the repo root:

    python -m pytest tests/test_lane_a.py -q

No fixture library, no mocks: a temp SQLite file and real rows.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.core import audit, claims, db, evidence, incident, ingest, repo, twin  # noqa: E402
from services.api.models import EventIn  # noqa: E402

T = "ten_lane_a"          # main tenant
TA = "ten_audit_only"     # isolated tenant so the chain test sees only its own rows
P = "prn_operator"
NOW = None


def _seed() -> None:
    now = db.now_iso()
    with db.tx() as c:
        for tid, name in ((T, "Lane A City"), (TA, "Audit Sandbox")):
            c.execute("INSERT INTO tenant(id,name,jurisdiction,created_at) VALUES(?,?,?,?)",
                      (tid, name, "UK", now))
        c.execute(
            "INSERT INTO principal(id,tenant_id,display_name,role,trust_domain,status) "
            "VALUES(?,?,?,?,?,?)", (P, T, "Ops One", "operator", "prod", "active"))
        for cid, cname, tier, sla in (
            ("con_scada", "Hydrology SCADA", "certified", 600),
            ("con_gauge", "Environment Agency Gauge", "statutory", 600),
            ("con_crowd", "Citizen Reports", "crowdsourced", 600),
            ("con_crowd2", "Social Signals", "crowdsourced", 600),
            ("con_fast", "Fast Expiring Feed", "verified", 1),
        ):
            c.execute(
                "INSERT INTO connector(id,tenant_id,name,trust_tier,contract_version,"
                "freshness_sla_s,owner) VALUES(?,?,?,?,?,?,?)",
                (cid, T, cname, tier, "1.0.0", sla, "data-eng"))
        # a 3-hop dependency chain: pump <- main <- estate <- clinic
        chain = [
            ("asset_pump", "Riverside Pump", -0.1200, 51.5000, 4, '{"threshold_m": 3.0}'),
            ("asset_main", "Trunk Main", -0.1210, 51.5005, 3, "{}"),
            ("asset_estate", "Estate Supply", -0.1220, 51.5010, 3, "{}"),
            ("asset_clinic", "Clinic Feed", -0.1230, 51.5015, 5, "{}"),
            ("asset_far", "Far Depot", -0.5000, 51.9000, 1, "{}"),
        ]
        for aid, aname, lon, lat, crit, state in chain:
            c.execute(
                "INSERT INTO asset(id,tenant_id,kind,name,geometry,criticality,owner_dept,"
                "current_state,reported_state,desired_state,geometry_accuracy_m) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (aid, T, "water", aname,
                 f'{{"type":"Point","coordinates":[{lon},{lat}]}}', crit, "water",
                 state, "{}", "{}", 5.0))
        for dep, on in (("asset_main", "asset_pump"), ("asset_estate", "asset_main"),
                        ("asset_clinic", "asset_estate")):
            c.execute("INSERT INTO asset_dependency(dependent_id,depends_on_id,relation) "
                      "VALUES(?,?,'supplies')", (dep, on))


def setup_module(module) -> None:  # noqa: ANN001
    path = Path(tempfile.mkdtemp(prefix="auralis_lane_a_")) / "test.db"
    db.init_db(path)
    _seed()


PUMP_XY = [-0.12, 51.5]
FAR_XY = [-0.50, 51.9]


def _event(connector_id: str, payload: dict, kind: str = "water_level",
           xy: list[float] | None = None, **kw) -> EventIn:
    return EventIn(connector_id=connector_id, kind=kind, event_time=db.now_iso(),
                   payload=payload,
                   geometry={"type": "Point", "coordinates": xy or PUMP_XY}, **kw)


# --------------------------------------------------------------------- audit
def test_hash_chain_verifies_then_reports_the_tampered_seq():
    for i in range(3):
        audit.append(TA, "wf_chain", "svc.test", "service", "test.step", f"sub_{i}",
                     {"i": i, "note": "original"})

    ok = audit.verify_chain(TA)
    assert ok.ok is True and ok.checked == 3 and ok.first_break_seq is None

    # tamper with seq 2 the only way it can be done: raw SQL, behind the module's back
    db.run("UPDATE audit_event SET payload=? WHERE tenant_id=? AND seq=2",
           '{"i":2,"note":"tampered"}', TA)

    broken = audit.verify_chain(TA)
    assert broken.ok is False
    assert broken.first_break_seq == 2, broken.detail
    assert broken.checked == 1  # seq 1 verified before the break
    assert "modified after write" in broken.detail


def test_export_workflow_carries_the_ledger_and_its_records():
    export = audit.export_workflow("wf_chain")
    assert export["workflow_id"] == "wf_chain"
    assert [e["seq"] for e in export["events"]] == [1, 2, 3]
    assert export["genesis_prev_hash"] == "0" * 64
    assert export["events"][0]["prev_hash"] == "0" * 64
    assert export["chain"]["ok"] is False  # the tamper above is visible in the export


# -------------------------------------------------------------------- claims
def test_ungrounded_fact_claim_raises():
    with pytest.raises(ValueError, match="ungrounded"):
        claims.create_claim(T, "The river is over its bank", "asset_pump", "level_over",
                            "bank", "fact", [], "test-agent")


def test_claim_citing_nonexistent_evidence_raises():
    with pytest.raises(ValueError, match="does not exist"):
        claims.create_claim(T, "Level will reach 4 m", "asset_pump", "forecast_level", "4m",
                            "forecast", ["ev_does_not_exist"], "test-agent")


def test_grounded_claim_is_written_and_audited():
    accepted = ingest.ingest_event(_event("con_scada", {"asset_id": "asset_pump", "level_m": 1.2}), P)
    assert accepted.evidence_id
    claim = claims.create_claim(T, "Level is 1.2 m", "asset_pump", "level_is", "1.2m",
                                "fact", [accepted.evidence_id], "test-agent")
    assert claim.evidence_ids == [accepted.evidence_id]
    assert any(c.id == claim.id for c in repo.list_claims(T))
    # a recommendation may stand without evidence; a fact may not
    assert claims.create_claim(T, "Consider closing the sluice", "asset_pump", "recommend",
                               "close", "recommendation", [], "test-agent").id


# -------------------------------------------------------------------- ingest
def test_duplicate_event_is_deduplicated_not_re_stored():
    ev = _event("con_scada", {"asset_id": "asset_pump", "level_m": 1.4},
                source_event_id="scada-42")
    first = ingest.ingest_event(ev, P)
    second = ingest.ingest_event(ev, P)

    assert first.accepted and first.deduplicated is False
    assert second.deduplicated is True
    assert second.id == first.id
    assert db.scalar("SELECT COUNT(*) FROM event WHERE source_event_id='scada-42'") == 1


def test_impossible_value_is_quarantined_and_still_queryable():
    accepted = ingest.ingest_event(
        _event("con_scada", {"asset_id": "asset_pump", "level_m": 999.0},
               source_event_id="scada-bad"), P)

    assert accepted.accepted is True and accepted.quarantined is True
    assert "impossible value" in accepted.reason
    assert accepted.evidence_id is None

    row = db.q1("SELECT * FROM event WHERE id=?", accepted.id)
    assert row is not None and row["quarantined"] == 1          # not dropped
    assert accepted.id in [e["id"] for e in repo.list_events(T, quarantined=True)]
    assert db.scalar("SELECT COUNT(*) FROM evidence WHERE event_id=?", accepted.id) == 0
    assert db.q1("SELECT * FROM raw_payload WHERE content_hash=?", row["content_hash"])


def test_clock_skew_quarantines_a_future_event():
    stale = EventIn(connector_id="con_scada", kind="water_level", event_time="2999-01-01T00:00:00Z",
                    payload={"asset_id": "asset_pump", "level_m": 1.0})
    accepted = ingest.ingest_event(stale, P)
    assert accepted.quarantined is True and "clock skew" in accepted.reason


def test_unknown_connector_is_rejected_and_audited():
    accepted = ingest.ingest_event(_event("con_nope", {"level_m": 1.0}), P)
    assert accepted.accepted is False and "unknown connector" in accepted.reason
    assert db.scalar(
        "SELECT COUNT(*) FROM audit_event WHERE tenant_id=? AND kind='ingest.rejected'", T) >= 1


# ------------------------------------------------------------------ evidence
def test_conflicting_sources_resolve_by_precedence_and_never_average():
    statutory = ingest.ingest_event(
        _event("con_gauge", {"asset_id": "asset_gauge", "level_m": 4.2}, xy=FAR_XY), P)
    ingest.ingest_event(
        _event("con_crowd", {"asset_id": "asset_gauge", "level_m": 6.9}, xy=FAR_XY), P)

    conflicts = evidence.detect_conflicts("asset_gauge:water_level")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.resolution == "precedence"
    assert conflict.resolved_by_rule == evidence.PRECEDENCE_RULE
    assert conflict.winner_evidence_id == statutory.evidence_id

    values = [db.jload(r["value_json"])["value"] for r in db.q(
        "SELECT * FROM evidence WHERE json_extract(value_json,'$.subject')=?",
        "asset_gauge:water_level")]
    assert sorted(values) == [4.2, 6.9]          # both survive
    assert 5.55 not in values                    # the average is never written
    assert evidence.detect_conflicts("asset_gauge:water_level")[0].id == conflict.id  # idempotent

    # same tier on both sides is left for a human
    ingest.ingest_event(_event("con_crowd", {"asset_id": "asset_tie", "level_m": 1.0},
                               xy=FAR_XY, source_event_id="tie-a"), P)
    ingest.ingest_event(_event("con_crowd", {"asset_id": "asset_tie", "level_m": 8.0},
                               xy=FAR_XY, source_event_id="tie-b"), P)
    # two different connectors, both crowdsourced: no precedence rule applies
    db.run("UPDATE evidence SET connector_id='con_crowd2' WHERE id="
           "(SELECT id FROM evidence WHERE json_extract(value_json,'$.value')=8.0 LIMIT 1)")
    tie = evidence.detect_conflicts("asset_tie:water_level")
    assert tie and tie[0].resolution == "unresolved" and tie[0].winner_evidence_id is None


def test_evidence_ref_computes_freshness_at_read_time():
    row = db.q1("SELECT * FROM evidence WHERE json_extract(value_json,'$.value')=4.2")
    ref = evidence.as_ref(row)
    assert ref.fresh is True and ref.age_s < 600
    assert evidence.as_ref(row, at="2999-01-01T00:00:00Z").fresh is False
    assert evidence.verify_integrity(row) is True


# ---------------------------------------------------------------- incidents
def test_detection_opens_an_incident_naming_its_rule():
    accepted = ingest.ingest_event(
        _event("con_scada", {"asset_id": "asset_pump", "level_m": 4.5},
               source_event_id="flood-1"), P)
    assert accepted.incident_id
    inc = repo.get_incident(accepted.incident_id)
    assert inc.detector == "det.water_level.over_asset_threshold.v1"
    assert inc.state == "detected" and inc.first_observation_at
    assert accepted.evidence_id in inc.evidence_ids
    entries = repo.list_audit(inc.id)
    assert any(e.kind == "incident.detected" and
               e.payload["detector"] == inc.detector for e in entries)


def test_nearby_event_correlates_into_the_open_incident():
    before = db.scalar("SELECT COUNT(*) FROM incident WHERE tenant_id=?", T)
    accepted = ingest.ingest_event(
        _event("con_scada", {"asset_id": "asset_pump", "level_m": 5.0},
               source_event_id="flood-2"), P)
    assert db.scalar("SELECT COUNT(*) FROM incident WHERE tenant_id=?", T) == before
    assert accepted.evidence_id in repo.get_incident(accepted.incident_id).evidence_ids


def test_illegal_incident_transition_raises():
    inc_id = db.scalar("SELECT id FROM incident WHERE tenant_id=? AND state='detected' LIMIT 1", T)
    with pytest.raises(incident.IllegalTransition, match="detected -> acting"):
        incident.transition(inc_id, "acting", P)
    assert incident.transition(inc_id, "assessing", P).state == "assessing"
    with pytest.raises(incident.IllegalTransition):
        incident.transition(inc_id, "not_a_state", P)


# --------------------------------------------------------------------- twin
def test_twin_traversal_depth_and_blast_radius():
    full = twin.query("asset_pump", depth=3)
    assert full.blast_radius == 3
    assert [n.id for n in full.nodes] == [
        "asset_pump", "asset_main", "asset_estate", "asset_clinic"]
    assert [n.depth for n in full.nodes] == [0, 1, 2, 3]
    assert {"from": "asset_main", "to": "asset_pump", "relation": "supplies"} in full.edges
    assert full.traversal_ms >= 0

    assert twin.query("asset_pump", depth=1).blast_radius == 1
    assert twin.query("asset_clinic", depth=3).blast_radius == 0   # nothing depends on it
    with pytest.raises(ValueError):
        twin.query("asset_missing", depth=1)


def test_twin_snapshot_replays_only_events_up_to_t():
    past = twin.snapshot("2000-01-01T00:00:00Z", T)
    assert past["events_replayed"] == 0
    now = twin.snapshot(db.now_iso(), T)
    assert now["events_replayed"] > 0
    pump = next(a for a in now["assets"] if a["id"] == "asset_pump")
    assert "level_m" in pump["state"]


def test_twin_reconcile_reports_sustained_divergence():
    db.run("UPDATE asset SET desired_state='{\"valve\": \"closed\"}', "
           "reported_state='{\"valve\": \"open\"}', current_state='{\"valve\": \"opening\"}' "
           "WHERE id='asset_far'")
    divergences = twin.reconcile(T, sustained_s=0)
    far = [d for d in divergences if d["asset_id"] == "asset_far"]
    assert len(far) == 1 and far[0]["key"] == "valve"
    assert (far[0]["desired"], far[0]["reported"], far[0]["current"]) == \
        ("closed", "open", "opening")


# ------------------------------------------------------ expiry propagation
def test_expired_evidence_flags_claims_and_returns_plans_to_revalidate():
    stale_time = db.iso(db.parse_iso(db.now_iso()) - timedelta(seconds=60))
    accepted = ingest.ingest_event(
        EventIn(connector_id="con_fast", kind="water_level", event_time=stale_time,
                payload={"asset_id": "asset_far", "level_m": 0.5},
                source_event_id="fast-1"), P)
    claim = claims.create_claim(T, "Far depot level is 0.5 m", "asset_far", "level_is", "0.5m",
                                "fact", [accepted.evidence_id], "test-agent")
    inc_id = db.scalar("SELECT id FROM incident WHERE tenant_id=? LIMIT 1", T)
    db.run("INSERT INTO plan(id,tenant_id,incident_id,title,rationale,created_at,created_by,"
           "status,claim_ids) VALUES('pl_test',?,?,'Test plan','because',?,?,'draft',?)",
           T, inc_id, db.now_iso(), P, db.jdump([claim.id]))

    plans = evidence.expire_and_propagate()

    assert "pl_test" in plans
    assert db.scalar("SELECT status FROM evidence WHERE id=?", accepted.evidence_id) == "expired"
    assert db.scalar("SELECT status FROM claim WHERE id=?", claim.id) == "flagged"
    assert db.scalar(
        "SELECT COUNT(*) FROM audit_event WHERE kind='claim.flagged' AND subject_id=?",
        claim.id) == 1
    # retraction is an event, not a deletion
    evidence.retract(accepted.evidence_id, "sensor recalibrated", P, "human")
    assert db.q1("SELECT * FROM evidence WHERE id=?", accepted.evidence_id)["status"] == "retracted"


def test_incident_export_stitches_the_ingest_timeline_for_replay():
    accepted = ingest.ingest_event(
        _event("con_scada", {"asset_id": "asset_pump", "level_m": 6.0},
               source_event_id="export-1"), P)
    export = audit.export_workflow(accepted.incident_id)
    kinds = [e["kind"] for e in export["events"]]
    assert "incident.detected" in kinds or "incident.correlated" in kinds
    assert "evidence.minted" in kinds and "ingest.accepted" in kinds
    assert accepted.evidence_id in [r["id"] for r in export["records"]["evidence"]]
    assert accepted.id in [r["id"] for r in export["records"]["event"]]
    assert export["chain"]["ok"] is True


def test_repo_health_and_metrics_are_tenant_scoped():
    health = {h.id: h for h in repo.connector_health(T)}
    assert health["con_scada"].events_24h > 0
    assert health["con_scada"].quarantined_24h > 0
    assert health["con_scada"].fresh is True
    metrics = repo.ops_metrics(T)
    assert metrics.audit_events > 0 and metrics.time_to_detect_s is not None
    assert metrics.unsupported_claim_rate > 0        # the flagged claim above
    assert repo.list_incidents(T) and not repo.list_incidents(TA)


def test_main_tenant_chain_is_still_intact_after_everything():
    report = audit.verify_chain(T)
    assert report.ok is True, report.detail
    assert report.checked > 10
