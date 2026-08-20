"""Append-only, hash-chained audit ledger. Invariant 6.

    entry_hash = sha256(prev_hash + canonical_json(entry_without_hashes))
    canonical_json = json.dumps(obj, sort_keys=True, separators=(",", ":"))

There is no update() and no delete() in this module, on purpose. `seq` is
monotonic per tenant and is allocated inside the same BEGIN IMMEDIATE
transaction as the INSERT, so two concurrent writers cannot take the same seq.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from services.api.models import AuditChainReport, AuditEvent

from . import db

GENESIS = "0" * 64

# id prefix -> table, used to pull the full record behind an id mentioned in an
# audit payload so an export can be replayed without the live database.
_PREFIX_TABLE = {
    "ev": "evidence", "cl": "claim", "inc": "incident", "pl": "plan",
    "ac": "action", "ap": "approval", "pd": "policy_decision",
    "ar": "agent_run", "as": "asset", "asset": "asset", "evt": "event",
    "event": "event", "wo": "work_order", "con": "connector",
    "conflict": "evidence_conflict", "mv": "model_version",
}
_ID_RE = re.compile(r"^([a-z]+)_[A-Za-z0-9_.:-]+$")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(entry)).encode("utf-8")).hexdigest()


def _entry(row: Any) -> dict[str, Any]:
    """The hashed projection of an entry: everything except the two hashes."""
    payload = row["payload"]
    return {
        "id": row["id"],
        "seq": row["seq"],
        "workflow_id": row["workflow_id"],
        "at": row["at"],
        "actor_id": row["actor_id"],
        "actor_kind": row["actor_kind"],
        "kind": row["kind"],
        "subject_id": row["subject_id"],
        "payload": db.jload(payload, {}) if isinstance(payload, str) else payload,
    }


def append(
    tenant_id: str,
    workflow_id: str,
    actor_id: str,
    actor_kind: str,
    kind: str,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    entry = {
        "id": db.new_id("aud"),
        "seq": 0,
        "workflow_id": workflow_id,
        "at": db.now_iso(),
        "actor_id": actor_id,
        "actor_kind": actor_kind,
        "kind": kind,
        "subject_id": subject_id,
        "payload": payload or {},
    }
    with db.tx() as c:
        entry["seq"] = c.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM audit_event WHERE tenant_id=?", (tenant_id,)
        ).fetchone()[0]
        prev = c.execute(
            "SELECT entry_hash FROM audit_event WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
        prev_hash = prev[0] if prev else GENESIS
        entry_hash = _hash(prev_hash, entry)
        c.execute(
            "INSERT INTO audit_event(id,tenant_id,seq,workflow_id,at,actor_id,actor_kind,"
            "kind,subject_id,payload,prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry["id"], tenant_id, entry["seq"], workflow_id, entry["at"],
                actor_id, actor_kind, kind, subject_id,
                canonical_json(entry["payload"]), prev_hash, entry_hash,
            ),
        )
    return AuditEvent(**entry, prev_hash=prev_hash, entry_hash=entry_hash)


def verify_chain(tenant_id: str) -> AuditChainReport:
    """Recompute every entry hash in seq order and report the FIRST break.

    ponytail: the stored payload is re-canonicalised before hashing, so an edit
    that only reorders JSON keys is not reported as a break - it changes no
    meaning. Any change to a value, a missing seq, or a re-pointed prev_hash is
    caught. Upgrade path: hash the stored bytes verbatim if byte-level custody
    of the payload column is ever required.
    """
    rows = db.q("SELECT * FROM audit_event WHERE tenant_id=? ORDER BY seq", tenant_id)
    prev_hash, checked, expected_seq = GENESIS, 0, 1
    for row in rows:
        seq = row["seq"]
        if seq != expected_seq:
            return AuditChainReport(
                ok=False, checked=checked, first_break_seq=seq,
                detail=f"seq gap: expected {expected_seq}, found {seq} - entry deleted",
            )
        if row["prev_hash"] != prev_hash:
            return AuditChainReport(
                ok=False, checked=checked, first_break_seq=seq,
                detail="prev_hash does not match the preceding entry_hash",
            )
        if _hash(prev_hash, _entry(row)) != row["entry_hash"]:
            return AuditChainReport(
                ok=False, checked=checked, first_break_seq=seq,
                detail=f"entry_hash mismatch at seq {seq}: row modified after write",
            )
        prev_hash, checked, expected_seq = row["entry_hash"], checked + 1, seq + 1
    return AuditChainReport(ok=True, checked=checked, detail=f"{checked} entries verified")


def workflow(workflow_id: str) -> list[AuditEvent]:
    rows = db.q("SELECT * FROM audit_event WHERE workflow_id=? ORDER BY seq", workflow_id)
    return [
        AuditEvent(**_entry(r), prev_hash=r["prev_hash"], entry_hash=r["entry_hash"])
        for r in rows
    ]


def _ids_in(obj: Any, found: set[str]) -> None:
    if isinstance(obj, str):
        m = _ID_RE.match(obj)
        if m and m.group(1) in _PREFIX_TABLE:
            found.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _ids_in(v, found)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _ids_in(v, found)


def export_workflow(workflow_id: str) -> dict[str, Any]:
    """The JSON the Audit UI downloads and Replay rebuilds a timeline from.

    Self-contained: the ordered ledger plus every record any entry points at -
    evidence, claims, incidents, plans, actions (with intended/actual state and
    verification), approvals, policy decisions, and agent runs with their model
    and prompt metadata.
    """
    seed = db.q("SELECT * FROM audit_event WHERE workflow_id=? ORDER BY seq", workflow_id)
    tenant_id = seed[0]["tenant_id"] if seed else None

    def harvest(rows: list[Any]) -> set[str]:
        found: set[str] = set()
        for r in rows:
            _ids_in(db.jload(r["payload"], {}), found)
            _ids_in(r["subject_id"], found)
        return found

    # Ingest and evidence entries are logged under the EVENT's workflow id, the
    # incident's under its own. One expansion hop stitches them into a single
    # replayable timeline. ponytail: one hop, not a transitive closure - deepen
    # only if a workflow ever needs to pull in a chain of referenced workflows.
    rows = {r["id"]: r for r in seed}
    linked = {i for i in harvest(seed) if i.split("_", 1)[0] in
              ("evt", "event", "inc", "pl", "ac")}
    for wid in sorted(linked):
        for r in db.q("SELECT * FROM audit_event WHERE workflow_id=?", wid):
            rows.setdefault(r["id"], r)

    ordered = sorted(rows.values(), key=lambda r: (r["at"], r["seq"]))
    events = [
        dict(_entry(r), prev_hash=r["prev_hash"], entry_hash=r["entry_hash"]) for r in ordered
    ]
    ids = harvest(ordered)

    records: dict[str, list[dict[str, Any]]] = {}

    def keep(table: str, row: Any) -> None:
        bucket = records.setdefault(table, [])
        if row is not None and not any(x["id"] == row["id"] for x in bucket):
            bucket.append(dict(row))

    for rid in sorted(ids):
        table = _PREFIX_TABLE[rid.split("_", 1)[0]]
        keep(table, db.q1(f"SELECT * FROM {table} WHERE id=?", rid))

    # agent runs are keyed by workflow, not always named inside a payload
    for r in db.q("SELECT * FROM agent_run WHERE workflow_id=?", workflow_id):
        keep("agent_run", r)
    for r in list(records.get("agent_run", [])):
        keep("model_version", db.q1(
            "SELECT * FROM model_version WHERE id=? OR version=?",
            r["model_version"], r["model_version"],
        ))
        keep("evidence_snapshot", db.q1(
            "SELECT * FROM evidence_snapshot WHERE id=?", r["evidence_snapshot_id"]
        ))
    # policy decisions, approvals and tool manifests hanging off any action
    for a in list(records.get("action", [])):
        if a.get("policy_decision_id"):
            keep("policy_decision", db.q1(
                "SELECT * FROM policy_decision WHERE id=?", a["policy_decision_id"]
            ))
        for ap in db.q("SELECT * FROM approval WHERE action_id=?", a["id"]):
            keep("approval", ap)
        keep("tool_manifest", db.q1("SELECT * FROM tool_manifest WHERE id=?", a["tool_id"]))

    return {
        "workflow_id": workflow_id,
        "tenant_id": tenant_id,
        "workflows": sorted({e["workflow_id"] for e in events}),
        "exported_at": db.now_iso(),
        "hash_algorithm": "sha256(prev_hash + canonical_json(entry_without_hashes))",
        "genesis_prev_hash": GENESIS,
        "chain": verify_chain(tenant_id).model_dump() if tenant_id else None,
        "events": events,
        "records": records,
    }
