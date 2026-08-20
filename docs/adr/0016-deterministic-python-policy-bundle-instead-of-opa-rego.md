# 0016 — Deterministic Python policy bundle instead of an OPA/Rego runtime

**Status:** Accepted (slice-scoped)

## Context
The standard answer for externalised authorisation is Open Policy Agent with
Rego. This build uses a versioned, hashed Python module,
`policies/bundle_v3.0.7.py`. That is a real tradeoff and deserves a straight
account, not a rationalisation.

## Decision
A policy bundle is a Python module of plain data plus pure functions. A rule is
a dict: `{"id", "description", "applies_to", "check": (ctx) -> (effect, reason)}`.
`evaluate(ctx)` returns `(effect, rule_id, reason)`; first deny wins, then the
first `require_approval`, else allow.

### What is genuinely equivalent to OPA
- **Policy is data, external to the application.** Rules live in `policies/`,
  loaded by path at runtime via `importlib`, not compiled into the service.
- **Versioned and content-addressed.** `VERSION = "3.0.7"`, filename
  `bundle_v3.0.7.py`, and `RULES_HASH = sha256(normalised source)`. Every
  `policy_decision` row stores the bundle version, so a decision points at the
  exact rule text that produced it. That is OPA's bundle-hash property.
- **Decision logging with input hashing.** Every `decide()` persists the full
  normalised inputs plus `inputs_hash`. That is OPA's decision-log property.
- **Pure evaluation and replay.** `policy.replay(inputs, version)` re-evaluates
  any historical or hypothetical input set against any bundle version and
  writes nothing — OPA's `opa eval` against a stored input.
- **Input minimisation.** `normalize()` projects to `CTX_KEYS` only. Same
  discipline as a well-designed Rego `input` document.
- **Deterministic and side-effect free** inside `evaluate()`. No I/O in a rule.

### What is genuinely NOT equivalent
1. **No sandbox.** Rego cannot open a socket or read a file; Python can. A
   malicious or careless bundle has the privileges of the API process. In OPA
   the policy language itself is the containment; here containment is code
   review and the fact that `policies/` ships with the repo.
2. **No formal properties.** Rego is a restricted, non-Turing-complete
   declarative language with defined evaluation semantics; you can reason about
   termination and, with tooling, coverage. A Python rule can loop forever.
3. **No policy-as-a-service.** OPA is a sidecar with a stable decision API that
   many services in many languages share. This bundle is importable by Python
   in this process only.
4. **No ecosystem.** No `opa test`, no coverage reports, no Rego playground, no
   bundle distribution/signing service, no conftest in CI.
5. **Hot reload is `lru_cache`-shaped.** `load_bundle` is memoised per version;
   changing a bundle in place requires a restart. OPA does live bundle polling.

### Why it is the right call for this slice
The invariant this system needs — *no model output can change a policy outcome*
(ADR 0002) — is achieved by the **input projection and module boundary**, not
by the policy language. Rego would add a process, a container, a wire format
and a second language to review, and it would not make `args` any more absent
from `CTX_KEYS` than it already is. The bundle is 356 lines and a reviewer can
read all of it.

## Consequences
- Rules are unit-testable directly, in the same test run as everything else.
- The reason strings are written by the same person who wrote the rule and are
  shown verbatim in the UI — this is why denials in Auralis read as sentences
  and not as codes.
- Bundle review is now a *security* review, because a bundle is code.

## Earned-complexity trigger
Move to OPA/Rego (or Cedar) at the **first** of:
- **a second consumer** — any non-Python service, or a second deployment, that
  must reach the same decisions;
- **policy authored by anyone outside the core engineering team** — a city
  policy officer editing rules needs a sandboxed language, not Python;
- **more than 3 tenants with divergent bundles**, where composition, inheritance
  and per-tenant override semantics must be defined rather than copy-pasted;
- **a certification or audit requirement for policy coverage evidence**, which
  needs `opa test --coverage`-class tooling.

Migration scope: `RULES` maps to Rego rules one-to-one; `CTX_KEYS` becomes the
`input` schema; `core/policy.py::decide` becomes an HTTP call to the sidecar and
keeps writing the same `policy_decision` row. `core/gateway.py` does not change.
