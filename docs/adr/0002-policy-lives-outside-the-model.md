# 0002 — Policy lives outside the model

**Status:** Accepted

## Context
If the component that decides whether an action is allowed shares a context
window with attacker-controlled text, then the authorisation boundary is a
prompt. Prompts are not a boundary.

## Decision
`core/policy.py` and `policies/bundle_v3.0.7.py` are pure deterministic Python
that never import anything under `services/api/agents/**`.

`policy.normalize()` projects the caller's context down to the documented keys
in `bundle.CTX_KEYS` before evaluation — and **`args` is deliberately not one
of them**. No wording of a request reaches a rule. What reaches a rule: tool
id, action class, computed risk tier, principal identity/role/status/trust
domain/SPIFFE id/jurisdictions, asset tenant and criticality, blast radius,
evidence age and status, public_facing, reversibility, rate counters,
approvals, break-glass block, and `now`.

`decide()` always writes a `policy_decision` row carrying `bundle_version`, the
full normalised inputs and their `inputs_hash`, so "what would policy have
said?" is answerable months later. `replay()` re-evaluates without writing —
that is how the simulator asks counterfactuals without polluting the decision
log. The bundle hashes its own source into `RULES_HASH`, so a decision points
at the exact text that produced it.

Evaluation order: **first deny wins, then the first require_approval, else
allow**. `R5_PROHIBITED` is rule index 0 so nothing can pre-empt it.

## Consequences
- An attacker who fully controls the agent's text output still cannot produce
  an `allow`: the text never reaches `evaluate()`.
- Every denial is explainable — rule id plus a reason string, rendered verbatim
  in the UI and returned as HTTP 403 `{"code":"policy_denied","rule_id":...}`.
- Cost: rules cannot exercise judgement. "Is this advisory wording
  inflammatory?" is not expressible; it has to be reduced to a structural fact
  (public_facing => R4 => dual control) or handed to a human.
- `allow` from one rule means only "this rule has no objection", never
  "authorised". Authorisation is the conjunction of all applicable rules.

## Earned-complexity trigger
Revisit at **more than ~40 rules, or 3+ tenants with divergent rule sets** —
at that point per-tenant rule composition and a rule-level test matrix are
required, and a single flat `RULES` list stops being reviewable. Separately: if
a rule ever needs data the gateway does not already hold, that is a signal the
context projection is wrong, not that the engine needs to be smarter.
