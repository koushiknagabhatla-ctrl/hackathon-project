# 0013 — The claims ledger: grounding as a data structure, not a rule

**Status:** Accepted

## Context
"Always cite your sources" in a system prompt is a request. A model that
ignores it produces an uncited assertion that renders identically to a cited
one, and nobody downstream can tell.

## Decision
An AI-authored statement is not text in a response. It is a `claim` row, and
the row cannot exist ungrounded.

`core/claims.py::check_grounding` runs on the write path and raises
`UngroundedClaim` when:
- `claim_class` ∈ {`fact`, `forecast`} and `evidence_ids` is empty, **or**
- any cited `evidence_id` does not exist in the `evidence` table.

`models.py::Claim` re-checks the first condition in a Pydantic
`model_validator`, so the invariant holds on the way out of the API as well as
on the way into the database. An agent that was told not to emit an ungrounded
claim and does it anyway gets a `ValueError` and **no row** — it does not get a
warning, and the UI never sees it.

Structure of a claim:

```json
{"id":"cl_...", "statement":"...", "subject":"...", "predicate":"...",
 "object":"...", "claim_class":"forecast", "evidence_ids":["ev_1"],
 "uncertainty":{"lower":0.4,"upper":1.1,"unit":"m"},
 "confidence_basis":"...", "author":"forecast-agent", "author_kind":"agent",
 "valid_from":"...", "valid_to":"...", "status":"active"}
```

- `claim_class` separates `fact` and `forecast` (grounded, hard-checked) from
  `recommendation` (an opinion, which may cite evidence but is not required to
  — and which the UI must render as an opinion).
- `subject/predicate/object` make claims comparable and contradictions findable
  by query rather than by reading prose.
- `status` moves between `active` / `flagged` / `retracted` with an audit
  event. **Claims are never deleted.** When the evidence under a claim expires
  or is retracted, `evidence.expire_and_propagate()` walks to the dependent
  claims and plans.
- Every claim write emits a `claim.created` audit event carrying the class,
  statement, evidence ids and uncertainty.

## Consequences
- Grounding is enforced by a type and a foreign-key-style existence check, so
  its failure mode is an exception, not a subtly wrong sentence.
- The UI's evidence chip is a projection of real data, not a decoration:
  removing the evidence removes the claim's basis and the propagation marks it.
- Cost: agents must be built to emit structured claims, not paragraphs. That is
  more work per agent and is the reason the invariant survives contact with a
  deadline.
- Limit: grounding proves a claim *cites* evidence. It does not prove the claim
  *follows from* it. A model can cite a real water-level reading and state a
  wrong implication. Mitigation is that the implication (the number, the tier)
  is computed elsewhere (ADR 0001), so the space of a wrong-but-cited claim is
  narrow prose, not a decision input.

## Earned-complexity trigger
Add entailment checking — a second model or a rule set that scores whether the
statement is supported by the cited evidence — when **claims/hour exceeds human
review capacity (~50/hour)**, or when the first post-incident review finds a
cited-but-unsupported claim that changed an operator's action. Until then the
`unsupported_claim_rate` SLI in `OpsMetrics` plus human review is the control.
