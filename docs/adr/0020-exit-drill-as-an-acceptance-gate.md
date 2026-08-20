# 0020 — The exit drill is an acceptance gate

**Status:** Accepted (drill defined; export path implemented, full drill partly manual)

## Context
A city that cannot leave a platform is a city that has to accept whatever the
platform becomes. "Exportable" as a bullet on a slide means nothing; the only
statement worth making is "we ran the exit and here is how long it took".

## Decision
Exit is a drill with a pass condition, run as an acceptance gate — not a
migration plan written after the contract is signed.

**Pass condition:** from a cold machine with no access to the running system,
using only exported artefacts, an independent party can reconstruct any
consequential workflow end to end — what was observed, what was concluded, what
was proposed, what policy said, who approved, what was executed, what was
verified — and can verify the audit chain over the export.

What makes that achievable here:
- `GET /v1/audit/{workflow_id}/export` is **self-contained by construction**.
  It emits the ordered ledger *plus every record any entry points at*, resolved
  by scanning payloads for typed id prefixes: evidence, claims, incidents,
  plans, actions with intended/actual state and verification, approvals, policy
  decisions, agent runs with model and prompt version, model versions, evidence
  snapshots and tool manifests. Reconstruction must be possible from that
  payload **alone**.
- The export carries `hash_algorithm`, `genesis_prev_hash` and a chain
  verification result, so the recipient can re-verify without our code.
- Policy is a file (`policies/bundle_v3.0.7.py`) with a self-hash, so the rules
  in force at decision time leave with the data.
- Storage is a single SQLite file and geometry is GeoJSON in EPSG:4326 — both
  readable without this application. Postgres migration is a schema translation,
  not a data rescue (ADR 0006).
- Prompts are versioned markdown files in the repository.

**What does not leave, and must be stated:** raw model weights (there are none
— a hosted API is used), and the hosted provider's own logs.

## What this build actually does
The export endpoint and the chain verification are implemented. The drill in
`security/drills.md` is runnable end to end for the export-and-verify half.
The "cold machine, independent party, timed" half is a procedure, not an
automated test, and has not been executed against an independent operator.

## Consequences
- The system cannot accrete undocumented state that only it can interpret,
  because the export would stop being sufficient and the drill would fail.
- Any feature that stores meaning outside the ledger is a drill regression.
  That is the useful constraint this ADR buys.
- Cost: `export_workflow` must be maintained whenever a new record type joins a
  workflow. That maintenance is the gate doing its job.

## Earned-complexity trigger
Run the drill with a genuinely independent party — different people, different
machine, timed, with a written report — **before any procurement or pilot
agreement is signed**, and re-run it **on every schema change that adds a table
referenced from an audit payload**. If a workflow export ever exceeds what a
reviewer can hold (say **>50 MB or >10k events**), add a paginated export with
a manifest and per-part hashes rather than weakening the self-containment rule.
