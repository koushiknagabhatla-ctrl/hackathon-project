# 0004 — Evidence service with provenance and expiry

**Status:** Accepted

## Context
"The system knew X" is meaningless without when it was observed, who observed
it, how much that source is trusted, and whether it is still true.

## Decision
Every observation becomes an `evidence` row minted by `core/evidence.py::mint`
from an already-persisted `event`. What makes it evidence rather than data:

- `trust_tier` is **copied from the connector row** — never inferred from the
  payload, never set by a model. Precedence:
  `statutory > certified > verified > crowdsourced > unknown`.
- `expires_at = observed_at + connector.freshness_sla_s`. Expiry is a property
  of the source contract, not a global constant.
- `integrity_hash` over the evidence content; `verify_integrity()` recomputes it.
- `prov_activity` and `prov_derived_from` record derivation lineage.
- `evidence_class` ∈ `observation | derived | synthetic |
  synthetic-corroboration`. Synthetic never renders as observed (invariant 9).
- Retraction is a `status` change plus an audit event. **Rows are never deleted.**
- `expire_and_propagate()` walks from newly-expired evidence to the claims and
  plans that cite it.

Conflicts are found by normalising every value into one shape so SQL can
compare across sources:

```json
{"subject": "<ref>:<metric>", "metric": "...", "value": 3.4,
 "unit": "m", "ref": "<asset/station id>", "payload": {"...raw..."}}
```

`detect_conflicts()` compares same-subject evidence with per-metric absolute
tolerances (water level 0.10 m, reservoir level 0.10 m, rainfall 2.0 mm/h,
traffic flow 50 veh/h, traffic speed 5 km/h) and a 5% relative fallback.
Resolution is by precedence rule `rule.source_precedence.v1`; the losing
evidence stays visible with the conflict recorded.

## Consequences
- The policy engine can refuse an action for stale evidence and name the age
  and the limit (`EVIDENCE_FRESHNESS`). Freshness is enforced, not decorative.
- A crowdsourced citizen report cannot outrank a certified SCADA reading by
  being more recent or more numerous.
- Cost: every query is wider and every UI component renders a provenance chip.
  That is the point.
- `integrity_hash` is an internal SHA-256, not a signature. It detects
  corruption and accidental mutation; it does not prove origin to a third party.

## Earned-complexity trigger
Revisit at **~10k evidence rows per subject per day** — the current
same-subject pairwise scan per new evidence is O(n) in that subject's history,
which is fine at city scale and wrong at sensor-network scale. Revisit
separately the first time an external party must verify evidence integrity
independently: that needs signing keys and a published verification procedure,
not a hash.
