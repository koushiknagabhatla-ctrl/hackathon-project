# 0018 — Edge autonomy ceiling of R2 when islanded

**Status:** Accepted in design; **not implemented in this build**

## Context
During the September 2024 Budameru event, parts of Vijayawada lost power and
connectivity while the water was still rising. Any honest design has to answer
what an edge node does when it cannot reach the core — and the two easy answers
are both wrong. "Do nothing" abandons the city at the worst moment. "Do whatever
it judges necessary" removes every control this architecture exists to provide,
precisely when nobody is watching.

## Decision
An islanded edge node may observe, compute and recommend. It may not act.

**Ceiling: R2.** Concretely, while islanded a node may:
- ingest local sensor readings and mint local evidence (R0);
- run the deterministic forecast models locally (R1);
- draft a plan and queue it for approval (R2).

It may **not**: raise a work order (R3), publish an advisory (R3/R4), change a
setpoint (R3), publish a public alert (R4), or isolate anything (R4). Those are
queued as pending proposals with their local evidence attached.

Rationale for R2 specifically: R2 is the highest tier that produces **no
external effect**. R3 is where the first irreversible-in-the-world thing
happens. The ceiling therefore falls on the boundary that already exists in
`core/risk.py::ACTION_CLASS_BASE`, rather than inventing an edge-specific
category. This is the same shape as `ROLE_MAX_TIER['agent'] = 'R2'` — an
unattended actor tops out where effects begin.

On rejoin: queued proposals are re-evaluated against the **current** policy
bundle and **current** evidence, not the evidence that existed when they were
drafted. The gateway's step 8 freshness recheck and step 9 risk gate do this
for free — a proposal drafted three hours ago against evidence that is now
stale is refused with `evidence_stale`, which is the correct outcome.

## What this build actually does
Nothing. There is no edge runtime, no islanding detection, no local queue and
no rejoin reconciliation in this repository. The mechanisms this ADR relies on
(`ROLE_MAX_TIER`, `ACTION_CLASS_BASE`, the freshness recheck, the risk gate)
all exist and are enforced; the edge node that would use them does not.

This ADR is recorded because the ceiling is an architectural commitment that
constrains the design — not because it has been built. Do not present it as a
shipped capability. See `docs/production-gap.md` and
`docs/runbooks/edge-islanding.md` (which documents the manual procedure that
applies today).

## Consequences
- An islanded node is degraded in *authority*, not in *usefulness*: crews still
  get local readings and a drafted plan on rejoin.
- The pathological case — a partitioned node acting on a partial view of the
  city while the core holds a different view — cannot occur.
- Cost: during a total comms failure, no automated action happens at all.
  Response falls back to radio and human judgement. That is the intended answer.

## Earned-complexity trigger
Build the edge runtime when **field operation without connectivity is a
contracted requirement**, or at **more than ~5 sites where a comms outage is
expected more than once a season**. Anything above R2 at the edge requires, at
minimum: locally-held credentials with short expiry, a local policy bundle with
a verified hash matching the core's, a local audit chain that merges into the
core chain on rejoin without breaking `seq` monotonicity, and a written
authority delegation from the city. That is a project, not a feature.
