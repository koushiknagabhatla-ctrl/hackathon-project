"""The digital twin: dependency traversal, point-in-time replay, self-audit.

Edges live in asset_dependency as (dependent_id -> depends_on_id). A blast
radius walks the DEPENDENT direction: "if this asset fails, what else does?"
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from services.api.models import TwinNode, TwinQueryResult

from . import db

DEFAULT_SUSTAINED_S = 300
# payload keys that describe the event, not the asset's state
_META_KEYS = {"asset_id", "subject", "station_id", "sensor_id", "segment_id", "unit"}


def _node(row: Any, depth: int, relation: str | None) -> TwinNode:
    return TwinNode(
        id=row["id"], kind=row["kind"], name=row["name"], criticality=row["criticality"],
        depth=depth, relation=relation, geometry=db.jload(row["geometry"]),
        current_state=db.jload(row["current_state"], {}),
    )


def query(asset_id: str, depth: int = 3) -> TwinQueryResult:
    """Breadth-first over asset_dependency from `asset_id` outward to the assets
    that depend on it. blast_radius counts distinct dependents reached, root
    excluded."""
    started = time.perf_counter()
    root = db.q1("SELECT * FROM asset WHERE id=?", asset_id)
    if root is None:
        raise ValueError(f"unknown asset: {asset_id}")

    nodes = [_node(root, 0, None)]
    edges: list[dict[str, str]] = []
    seen = {asset_id}
    queue: deque[tuple[str, int]] = deque([(asset_id, 0)])
    while queue:
        current, d = queue.popleft()
        if d >= depth:
            continue
        for e in db.q(
            "SELECT d.dependent_id, d.relation, a.* FROM asset_dependency d "
            "JOIN asset a ON a.id = d.dependent_id WHERE d.depends_on_id=? "
            "ORDER BY d.dependent_id",
            current,
        ):
            edges.append({"from": e["dependent_id"], "to": current, "relation": e["relation"]})
            if e["dependent_id"] in seen:
                continue
            seen.add(e["dependent_id"])
            nodes.append(_node(e, d + 1, e["relation"]))
            queue.append((e["dependent_id"], d + 1))

    return TwinQueryResult(
        root=asset_id, depth=depth, nodes=nodes, edges=edges,
        blast_radius=len(seen) - 1,
        traversal_ms=round((time.perf_counter() - started) * 1000, 3),
    )


def snapshot(at_iso: str, tenant_id: str | None = None) -> dict[str, Any]:
    """Twin state at time T, rebuilt by replaying events up to that timestamp.

    ponytail: the fold is "apply the event payload's state keys to the asset".
    That is enough for the metrics this slice carries; a real twin needs a typed
    per-kind reducer, which is the upgrade path when asset kinds multiply.
    """
    where = "WHERE quarantined=0 AND event_time<=?"
    args: list[Any] = [at_iso]
    if tenant_id:
        where += " AND tenant_id=?"
        args.append(tenant_id)

    assets = db.q(
        "SELECT * FROM asset" + (" WHERE tenant_id=?" if tenant_id else ""),
        *([tenant_id] if tenant_id else []),
    )
    state = {a["id"]: {} for a in assets}
    replayed = 0
    for e in db.q(f"SELECT * FROM event {where} ORDER BY event_time, ingest_time, id", *args):
        payload = db.jload(e["payload"], {})
        aid = payload.get("asset_id")
        if aid not in state:
            continue
        patch = payload.get("state")
        if not isinstance(patch, dict):
            patch = {k: v for k, v in payload.items() if k not in _META_KEYS}
        state[aid].update(patch)
        state[aid]["_as_of"] = e["event_time"]
        replayed += 1

    return {
        "as_of": at_iso,
        "tenant_id": tenant_id,
        "events_replayed": replayed,
        "assets": [
            {"id": a["id"], "name": a["name"], "kind": a["kind"],
             "criticality": a["criticality"], "geometry": db.jload(a["geometry"]),
             "state": state[a["id"]]}
            for a in assets
        ],
    }


def reconcile(tenant_id: str, sustained_s: int = DEFAULT_SUSTAINED_S) -> list[dict[str, Any]]:
    """The twin auditing itself: report keys where desired, reported and current
    disagree and have kept disagreeing for `sustained_s` (no fresher event has
    touched the asset). A momentary in-flight difference is not a divergence."""
    now = db.now_iso()
    out: list[dict[str, Any]] = []
    for a in db.q("SELECT * FROM asset WHERE tenant_id=?", tenant_id):
        desired = db.jload(a["desired_state"], {})
        reported = db.jload(a["reported_state"], {})
        current = db.jload(a["current_state"], {})
        last = db.scalar(
            "SELECT MAX(event_time) FROM event WHERE quarantined=0 "
            "AND json_extract(payload,'$.asset_id')=?", a["id"],
        )
        stale_for = db.age_s(last, now) if last else None
        if stale_for is not None and stale_for < sustained_s:
            continue
        for key in sorted(set(desired) | set(reported) | set(current)):
            values = {"desired": desired.get(key), "reported": reported.get(key),
                      "current": current.get(key)}
            if len(set(map(db.jdump, values.values()))) == 1:
                continue
            out.append({
                "asset_id": a["id"], "name": a["name"], "key": key, **values,
                "last_event_at": last, "stale_for_s": stale_for,
                "sustained_s": sustained_s,
                "detail": f"{a['name']}.{key}: desired={values['desired']!r} "
                          f"reported={values['reported']!r} current={values['current']!r}",
            })
    return out
