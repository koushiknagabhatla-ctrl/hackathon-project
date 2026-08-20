# 0008 — Simulation runs in a separate trust domain

**Status:** Accepted

## Context
A counterfactual engine is a machine for producing plausible-looking city state
that never happened. Two failure modes follow: simulated output presented as
observation, and a simulation run that reaches a production effect.

## Decision
Simulation is separated by **identity**, not by convention.

- `principal.trust_domain` is `'prod'` or `'sim'`. `tool_manifest.trust_domain`
  is the same vocabulary.
- The barrier is enforced **twice, independently**:
  1. `core/gateway.py` step 6, before `policy.decide` runs at all —
     `trust_domain='sim'` principal + `trust_domain='prod'` tool → refuse with
     `code="simulation_barrier"` and an audit event.
  2. `policies/bundle_v3.0.7.py::_c_sim_barrier`, rule `SIMULATION_BARRIER`,
     which denies the same combination inside the policy engine.
  Either one alone would stop it. Both exist so a misconfigured bundle is not a
  single point of failure.
- `ROLE_MAX_TIER['sim'] = 'R1'` and `ROLE_HARD_MAX['sim'] = 'R1'`. Even inside
  the sim domain a sim principal can never reach an acting tier.
- Simulation output is typed as untrustworthy at the model layer:
  `SimulationResult` pins `trust_domain: Literal["sim"]` and
  `evidence_class: Literal["synthetic"]`. Invariant 9 requires every surface to
  render `synthetic` with a synthetic label.
- `simulation_run` is a separate table with its own `seed`, `overrides`,
  `results_hash` and `trust_domain` column defaulting to `'sim'`.
- Counterfactual policy questions go through `policy.replay()`, which is pure
  and writes nothing — a simulation cannot pollute the production decision log.

## Consequences
- "Run the September 2024 Budameru scenario" cannot touch a production tool
  even if the scenario script asks it to, and the refusal is auditable.
- Simulated evidence cannot silently become the basis of a real claim: the
  class is carried on the row and rendered.
- Cost: a real principal cannot "just try it in sim" with their own identity.
  Testing a plan requires assuming a sim identity, which is the point.

## Earned-complexity trigger
Revisit when simulation needs its own compute — **any simulation exceeding ~10s
of wall clock, or run at more than ~1/minute** — at which point sim moves to a
separate process and database file with no write path to the production
database at all, and the barrier becomes a network boundary rather than an
in-process check. Revisit sooner if simulation ever needs to *write* into the
production twin (e.g. to persist a calibrated parameter): that is a promotion
step and needs an explicit, approved, audited promotion path, not a shared
connection.
