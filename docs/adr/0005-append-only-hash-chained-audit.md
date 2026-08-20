# 0005 — Event log and append-only hash-chained audit

**Status:** Accepted

## Context
An audit log a privileged user can silently edit proves nothing in the one
situation it exists for.

## Decision
`core/audit.py` implements an append-only ledger with per-tenant monotonic
`seq` and a hash chain:

```
entry_hash = sha256(prev_hash + canonical_json(entry_without_hashes))
canonical_json = json.dumps(obj, sort_keys=True, separators=(",", ":"))
genesis prev_hash = "0" * 64
```

`seq` is allocated inside the same transaction as the INSERT, so two writers
cannot take the same number, and `UNIQUE (tenant_id, seq)` enforces it in the
schema. The module has **no `update()` and no `delete()`** — not as a
convention, as an absence.

`verify_chain(tenant_id)` recomputes every entry in `seq` order and reports the
**first** break with a specific cause:

| Symptom | Reported as |
|---|---|
| Missing `seq` | `seq gap: expected N, found M - entry deleted` |
| Re-pointed chain | `prev_hash does not match the preceding entry_hash` |
| Edited row | `entry_hash mismatch at seq N: row modified after write` |

Exposed at `GET /v1/audit/verify` and rendered on the Audit screen.

`export_workflow()` emits the ordered ledger **plus every record any entry
points at** — resolved by scanning payloads for typed id prefixes (`ev_`,
`cl_`, `inc_`, `pl_`, `ac_`, `ap_`, `pd_`, `ar_`, …) and pulling the row —
together with agent runs keyed by workflow, their `model_version` and
`evidence_snapshot`, plus approvals, policy decisions and tool manifests
hanging off any action. A workflow replays from the export alone, with no live
database.

## Consequences
- Tampering is detectable and locatable; the Audit screen demonstrates it live
  (`security/drills.md`, audit-chain-tamper drill).
- Recovery from a break is a forensic procedure, not a repair — see
  `docs/runbooks/audit-chain-break.md`.
- Stated limit: `verify_chain` re-canonicalises the stored payload before
  hashing, so an edit that only reorders JSON keys is not reported as a break.
  It changes no meaning. Byte-level custody of the `payload` column would
  require hashing stored bytes verbatim.
- Stated limit: a hash chain proves internal consistency, not external time.
  Nothing is notarised or externally anchored, so an attacker with database
  write access who rewrites the entire chain from a chosen `seq` forward
  leaves a chain that verifies.

## Earned-complexity trigger
Revisit at **the first audit that requires third-party verification** — that
needs periodic anchoring of the head hash to an external append-only store, or
entries signed with keys the operator does not hold. Revisit separately at
**~10M audit entries**, where full-chain recomputation stops being an
acceptable synchronous endpoint and needs signed checkpoints.
