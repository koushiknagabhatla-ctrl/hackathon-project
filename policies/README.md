# Auralis policy bundles

Policy lives **outside the model**. `services/api/core/policy.py` and the
bundles in this directory never import anything under `services/api/agents/**`
(contract invariant 2, enforced by `tests/test_lane_b.py`). No model output
can change a policy outcome. Only the evidence and the action instance can.

## Layout

| File | What it is |
|---|---|
| `bundle_v3.0.7.py` | The active bundle: rule data + pure check functions. |

A bundle exports:

- `VERSION` — the version string in the filename.
- `RULES` — an ordered list of `{id, description, applies_to, check}`.
- `evaluate(ctx) -> (effect, rule_id, reason)` — pure, no I/O.
- `RULES_SOURCE` / `RULES_HASH` — the file text and its sha256, so a decision
  can name the exact bundle that produced it.
- `CTX_KEYS` — the closed set of decision inputs. `policy.normalize()` keeps
  only these, in this order, before hashing.

## Evaluation order

First **deny** wins. Otherwise the first **require_approval** wins. Otherwise
**allow**. `R5_PROHIBITED` is deliberately the first rule so nothing can
pre-empt the prohibited-action registry.

| # | Rule | Effect it can produce |
|---|---|---|
| 1 | `R5_PROHIBITED` | deny |
| 2 | `IDENTITY_VALID` | deny |
| 3 | `TENANT_MATCH` | deny |
| 4 | `SIMULATION_BARRIER` | deny |
| 5 | `ROLE_TIER` | deny / require_approval |
| 6 | `ASSET_CRITICALITY_CEILING` | deny / require_approval |
| 7 | `EVIDENCE_FRESHNESS` | deny |
| 8 | `GEOFENCE` | deny |
| 9 | `TIME_WINDOW` | require_approval |
| 10 | `RATE_LIMIT` | deny |
| 11 | `BLAST_RADIUS_CEILING` | deny / require_approval |
| 12 | `REVERSIBILITY_REQUIRED` | require_approval |
| 13 | `DUAL_CONTROL` | require_approval |
| 14 | `EMERGENCY_OVERRIDE` | deny |

`EMERGENCY_OVERRIDE` is fail-closed: break-glass without a reason code, or
without a distinct second approver at R4/R5, is a **denial**. Claiming an
emergency can never make an action more permitted than it already was.

## The prohibited-action registry

`PROHIBITED_TOOLS` and `PROHIBITED_ACTION_CLASSES` are the "we never build
direct equipment control" line. `scada.direct_control` is registered in the
tool registry **only so the refusal is visible** — the manifest is listed, the
sandbox raises, and `R5_PROHIBITED` denies before execution is ever reached.
The rule reads the tool id, action class and computed tier. It never reads the
arguments, so no wording of a request changes the outcome.

## Risk tier is per action instance

`core/risk.py::compute_tier` is the only place a tier is produced. The same
tool is R3 against a small reversible target and R4 when the instance is
public-facing or the blast radius crosses the threshold. Escalation is capped
at R4: nothing can *escalate into* R5, because R5 is reserved for action
classes that are direct physical control, and those are already prohibited.

## Replay

Every `decide()` writes a `policy_decision` row with `bundle_version`, the
full `inputs`, and `inputs_hash = sha256(canonical_json(inputs))` where
canonical json is `sort_keys=True, separators=(",",":")`. `policy.replay(
inputs, bundle_version)` re-evaluates those inputs against any bundle version
and writes nothing, so Lane F's simulator can ask "what would policy have
said?" without polluting the decision log.

## ponytail: why Python and not Rego

We are not shipping an OPA binary or a Rego runtime for a vertical slice. The
bundle is deterministic Python: versioned, content-hashed, pure, and unit
tested — which is the property that actually matters (a decision is
reproducible from its logged inputs plus its bundle hash).

The swap to OPA is a **`decide()` reimplementation, not a rewrite**. Everything
outside `policy.py::_evaluate` — the ctx shape, `CTX_KEYS`, the decision row,
`inputs_hash`, `replay()`, the effect vocabulary — is already the OPA input/
result contract. Porting means: translate `RULES` to Rego, replace the body of
`_evaluate` with an HTTP POST to `/v1/data/auralis/decision`, and keep
`RULES_HASH` as the bundle revision. Do it when policy authors are not
engineers, or when policy must ship on a different cadence than the API.
Until then, one file and one hash beats a sidecar.
