# 0011 — Model registry and evaluation gates

**Status:** Partially implemented — see "What this build actually does"

## Context
A model in production without a version, an owner and a declared valid input
range is an unattributable decision. When a forecast is wrong, the first
question is "which model, which version, on what inputs" and it must be
answerable from a row, not a deploy log.

## Decision
Every model is a registered artefact with a declared operating envelope, and
every use of it is attributed.

- `model_version` table: `name`, `kind`, `version`, `envelope` (JSON),
  `registered_at`, `status`.
- `agent_run` records `model_version`, `prompt_template`, `prompt_version` and
  `evidence_snapshot_id` for every model invocation, plus tokens, cost and a
  `degraded` flag. Audit export pulls the `model_version` and
  `evidence_snapshot` rows behind every run (ADR 0005), so a replay shows which
  model saw which evidence.
- **The envelope is enforced in code, not documented in a wiki.**
  `core/forecast.py` declares an `Envelope` per model and does one of two things
  outside it, in machine-readable form:
  - `DOWNGRADE` — input just past a bound (within `soft_margin`): clamp to the
    boundary, widen the interval, set `in_envelope=False` and write an
    `envelope_note`.
  - `ABSTAIN` — far outside, or the input is missing: `median/p10/p90` are
    `None`. Nothing is extrapolated and no number is invented.
  The `forecast` table carries `in_envelope` and `envelope_note` per forecast.
- Versions are pinned strings, not "latest": `FLOOD_MODEL_VERSION =
  "flood-depth-curve-1.2.0"`, `TRAFFIC_MODEL_VERSION =
  "traffic-degradation-1.1.0"`.

## What this build actually does
Implemented: the registry table, per-run attribution, pinned versions, and
enforced operating envelopes with abstention.

**Not implemented:** there is no evaluation harness, no held-out benchmark, no
scored gate that blocks promotion of a model version, and no drift monitor that
compares forecast to outturn. `model_version.status` is set by hand. The gate
in this ADR's title is a schema and a convention here, not a running check.
`docs/runbooks/model-drift.md` describes the manual procedure that stands in
for it, and `docs/production-gap.md` lists formal evaluation as a production
requirement.

## Consequences
- Attribution and abstention — the two properties that matter for defensibility
  — are real today.
- Promotion safety is a human process today. A wrong model version reaches
  production if a human ships it.

## Earned-complexity trigger
Build the evaluation harness at the **first learned (fitted) model**, or at
**more than 2 model versions in production simultaneously**, whichever comes
first. Deterministic curves can be reviewed by reading them; a fitted model
cannot, and needs a scored held-out gate plus a drift monitor comparing
predicted to observed before it is allowed to influence a tier.
