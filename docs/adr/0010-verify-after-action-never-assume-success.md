# 0010 — Verify after action, never assume success

**Status:** Accepted

## Context
An HTTP 200 from a control system means the request was accepted, not that the
pump changed. Systems that close an action on the call returning are systems
that report a city as safe while it floods.

## Decision
`core/verify.py` compares intended state to observed state after every write
action. Four verdicts, and the mapping to action status is fixed:

| Verification | Meaning | Action status |
|---|---|---|
| `SUCCESS` | intended state observed on read-back | `verified` |
| `DIFFERENCE` | observed, but not what was intended | `difference` |
| `FAILED` | the read-back itself failed | `failed` |
| `UNKNOWN` | we do not know | `unknown` |

**A tool timeout maps to `UNKNOWN`.** Never `failed` (which would invite a
retry that double-actuates) and never `executed` (which would invite closing
the incident). `gateway._on_timeout` writes status `unknown`, verification
`UNKNOWN`, an `action.timeout` audit event, and returns — it does not retry.

`verification_method` is declared on the tool manifest and is a **registration
requirement**: `tools/registry.py::register` rejects any manifest with
`write=True` and an empty `verification_method`. An effect that cannot be read
back cannot be closed out, so it cannot be registered.

- `readback` — re-read the asset state the tool claimed to change and compare
  (numeric comparison with tolerance `1e-6`).
- `human_confirmation` — a person records that the effect happened.
  `alert.publish_cap` uses this; a database row does not prove a siren sounded.

`DIFFERENCE` is a reconciliation exception, not a failure: the action happened
and the world is not what was intended, which is the more dangerous state and
is surfaced as such. `sandbox.DRIFT_TOOLS` injects this deliberately so the
path is demonstrable rather than theoretical, and `sandbox.TIMEOUT_TOOLS` does
the same for `UNKNOWN`.

## Consequences
- Incidents cannot close on optimism. The state machine requires `verifying`
  before `closed`.
- `unknown` requires a human decision. That is correct: only a person can
  choose between re-reading, dispatching a crew, or rolling back.
- Cost: every write tool needs a read path, which roughly doubles the
  integration work per tool. That cost is the reason `verification_method` is
  a registration gate rather than a nice-to-have.

## Earned-complexity trigger
Revisit when a tool's effect has **propagation delay longer than the request**
— a gate that takes 90 seconds to travel, a broadcast with delivery receipts
arriving over minutes. That needs a deferred verification queue with a
deadline, re-checking on a schedule, and an escalation when the deadline
passes with the action still `unknown`. Build it at the first such tool; do not
build it speculatively.
