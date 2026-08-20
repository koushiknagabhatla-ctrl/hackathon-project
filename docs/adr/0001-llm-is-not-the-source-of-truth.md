# 0001 — The LLM is not the source of truth

**Status:** Accepted

## Context
An urban operations system that lets a language model produce the number a
decision hangs on has no defensible failure story. "The model said 2.4 m" is
not evidence, is not reproducible, and cannot be replayed for an inquiry.

## Decision
Numbers, tiers and verdicts are produced by deterministic code; the model
produces language only.

| Output | Produced by | Model involved |
|---|---|---|
| Flood depth / traffic delay | `core/forecast.py`, seeded `random.Random(seed)`, 200 ensemble members | no |
| Risk tier | `core/risk.py::compute_tier` | no |
| Policy effect | `policies/bundle_v3.0.7.py::evaluate` | no |
| Incident detection | `core/incident.py` threshold rules, rule id stored in `incident.detector` | no |
| Verification verdict | `core/verify.py` read-back comparison | no |
| Narrative, plan prose, claim statements | `agents/**` | yes |

A model-authored statement only enters the system as a `claim` row, and
`core/claims.py::check_grounding` refuses any `fact`/`forecast` claim whose
`evidence_ids` is empty or cites an id not present in `evidence`.
`core/forecast.py` abstains (`median=None`, `abstained=True`) outside its
declared operating envelope rather than extrapolating; an agent narrating an
abstention cannot invent the number, because the number is not in the payload.

## Consequences
- Every number in the UI traces to a pure function and a seed. Replay is exact.
- The model has no path to change an outcome, so prompt injection can change
  the wording of a sentence but not a forecast, a tier or a decision. See
  `security/threat-model.md`.
- Cost: forecasting is limited to what someone wrote a model for — two
  hydrology curves and one traffic degradation curve is the whole numeric
  repertoire in this build.
- Degraded mode is cheap: with no `ANTHROPIC_API_KEY` the system loses prose,
  not capability.

## Earned-complexity trigger
Revisit when a forecast class is needed that cannot be expressed as a
parameterised curve — a learned surrogate for 2D hydraulic routing — or at
**more than 5 distinct numeric model families in production**. At that point
the determinism guarantee moves from "pure function" to "pinned model artefact
+ recorded seed + `model_version` in the registry" (ADR 0011), and the replay
test must compare hashes of recorded model outputs rather than recomputing them.
