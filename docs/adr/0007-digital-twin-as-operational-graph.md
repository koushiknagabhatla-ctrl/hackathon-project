# 0007 — The digital twin is an operational graph, not a visualisation

**Status:** Accepted

## Context
Most "city digital twin" demos are a 3D render. A render answers "what does it
look like". Nothing in this system needs that answer. The questions that gate
an action are "if this fails, what else fails?" and "what did the city look
like at 04:12?".

## Decision
The twin is `asset` + `asset_dependency` in SQL, traversed by `core/twin.py`.
No mesh, no tiles, no render pipeline.

- **Blast radius** — `twin.query(asset_id, depth)` walks the *dependent*
  direction (`dependent_id -> depends_on_id`, reversed) breadth-first and
  counts distinct dependents reached, root excluded. That integer is a direct
  policy input: `BLAST_CEILING` denies R3 above 25 dependents and R4 above 250;
  `BLAST_APPROVAL_AT` forces a named approver above 10 (R3) / 50 (R4). The
  graph is not decoration — it changes whether an action is permitted.
- **Point-in-time** — `twin.snapshot(at)` reconstructs asset state as of a
  timestamp, which is what makes audit replay honest: a decision is reviewed
  against the world as it was, not as it is now.
- **Three states per asset** — `current_state` (what we believe), `reported_state`
  (what the asset says), `desired_state` (what we asked for). `twin.reconcile()`
  finds sustained divergence between them. That is drift detection on the
  physical estate, and it is the same comparison `core/verify.py` performs for
  a single action.
- **`permitted_actions`** on the asset row is a per-asset allow-list the
  gateway enforces at step 8: an asset that does not permit a tool refuses it
  regardless of role or tier.
- Detection thresholds are read *from the asset* (`_threshold()` reads
  `current_state` / `desired_state` / `reported_state` before falling back to
  a default), so a bund with a 3.0 m alarm level and one with 4.5 m are
  different objects, not one constant.

Map rendering (MapLibre GL) consumes the same GeoJSON the twin stores. The map
is a view of the graph, never the source of it.

## Consequences
- The twin is queryable in the same transaction as everything else; no separate
  graph store, no sync job, no eventual consistency between "the model" and
  "the data".
- Blast radius is computed at execution time, so a dependency added since
  planning raises the tier and blocks the action (`risk_escalated`).
- Cost: no visual fidelity. There is no 3D city, and this build makes no claim
  to one.
- Depth is capped at 6 in the API and 3 in the gateway's blast-radius call —
  a deliberate bound, not a limitation of the traversal.

## Earned-complexity trigger
Move to a dedicated graph store (or recursive CTEs with materialised closure)
at **>100k assets or traversal depth >6 routinely**, or when the twin must
answer multi-hop queries with edge weights — flow capacity, travel time,
hydraulic connectivity — which SQL breadth-first traversal over an unweighted
edge table cannot express. Add a render pipeline only when a stakeholder can
name a decision that a render changes; none has been named yet.
