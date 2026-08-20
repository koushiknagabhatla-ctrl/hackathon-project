# 0003 — The tool gateway is the single action path

**Status:** Accepted

## Context
Safety controls that live in more than one place are safety controls that
disagree. Every "just this once" direct call is a hole nobody documents.

## Decision
`core/gateway.py::execute` is the only function permitted to invoke
`tools/sandbox.py::call`. Routers are thin; `POST /v1/actions/{id}/execute` is
the only route that reaches an effect. The chain runs in a fixed order and
short-circuits with an `action.blocked` audit event at every step:

```
1  plan status                  8  evidence / precondition RECHECK
2  args vs manifest schema      9  risk gate (tier may have escalated)
3  tool allow-list for role    10  approval present + unexpired
4  identity not revoked        11  idempotency key
5  tenant authorization        12  sandbox implementation
6  SIMULATION BARRIER          13  response vs output_schema
7  policy.decide               14  reconcile -> verify -> audit
```

The order is the security design, not a coincidence:

- Step 6 precedes step 7 so a `sim` principal is refused even if the policy
  bundle were misconfigured — two independent checks, not one.
- Between steps 6 and 7 the gateway re-reads **live** facts: asset criticality,
  blast radius via `sandbox.blast_radius`, evidence age and status. It then
  recomputes the tier with `risk.compute_tier`. Approval-time values are never
  reused.
- Step 8 exists because evidence goes stale between approval and execute.
- Step 9 refuses when the recomputed tier exceeds the tier the action was
  planned and approved at, with both tiers in the error.

Failure mapping is explicit: `ToolTimeout` → status `unknown` and verification
`UNKNOWN` (never `failed`, never assumed success); `ProhibitedTool` → status
`blocked` with `rule_id=R5_PROHIBITED`; any other exception → `failed`; an
output that does not match `output_schema` → `failed`.

## Consequences
- One function to read to know what can happen; one place to instrument.
- Approval is never a standing permission. It is trusted only together with a
  re-check of the world it was granted against.
- Cost: `execute` is the longest function in the codebase and carries the
  highest test burden. It is also the one worth it.

## Earned-complexity trigger
Revisit at **~50 tool invocations/second sustained**, or the first tool that
cannot complete inside the HTTP request (a job that outlives the call). Async
tools require an execution-record state machine plus a separate reconciliation
worker — a materially different design. Do not retrofit it into `execute`.
