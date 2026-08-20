# 0015 — Contracts as code are the enforcement point

**Status:** Accepted

## Context
A data contract in a PDF is a hope. A schema that is validated only in the UI
is a decoration. Bad data that reaches the store is bad data that reaches a
decision.

## Decision
Every boundary in this system has a machine-checked contract, and violating it
is a refusal, not a log line.

| Boundary | Contract | Enforced in | On violation |
|---|---|---|---|
| Connector → ingest | `ingest.CONTRACTS[kind]`: required fields, numeric ranges, enums | `core/ingest.py` step 2 | reject with reason; no row |
| Physical plausibility | same table's numeric ranges (e.g. rainfall 0–400 mm/h, water level −10–30 m) | `core/ingest.py` step 6 | **quarantine, never drop** — row kept with `quarantined=1` and a reason |
| Clock | >24 h past or >5 min future | `core/ingest.py` step 5 | quarantine with the skew in seconds |
| Agent → tool args | `tool_manifest.input_schema` | `core/gateway.py` step 2 (`validate_schema`) | `args_invalid` with the exact field errors |
| Tool → system | `tool_manifest.output_schema` | `core/gateway.py` step 13 | action → `failed`, `response_invalid` |
| Tool registration | non-empty `sandbox_ref`; `write=True` ⇒ non-empty `verification_method` | `tools/registry.py::register` | `ManifestRejected` — the tool does not exist |
| Agent output | JSON schema passed to `llm_gateway.complete()` | `agents/llm_gateway.py::_parse` | fall back to deterministic generator, `degraded=True` |
| API wire format | Pydantic v2 models in `models.py` | FastAPI | 422 `invalid_request` |
| Claim grounding | class + evidence existence | `core/claims.py` + `models.Claim` validator | `UngroundedClaim`, no row |

Two design choices inside this:

- **Quarantine, never drop.** An impossible reading is data about a failing
  sensor. It is stored, queryable, excluded from evidence, and
  `ingest.release_from_quarantine()` lets a human clear it — with the original
  quarantine reason permanently in the audit ledger.
- **The schema checker is deliberately small.** `gateway.validate_schema`
  covers `type`, `properties`, `required`, `enum`, `minimum`, `maximum` —
  exactly what the manifests use. Pulling in `jsonschema` buys nothing until a
  manifest needs more.

Every ingest outcome — accepted, rejected, deduplicated, quarantined, released
— writes an audit event. There is no silent path.

## Consequences
- Bad data has a recorded reason and a visible state, which is what makes
  `/v1/data-health` meaningful rather than a green light.
- A tool cannot be added without a sandbox twin and a way to verify it, so the
  safety properties of ADR 0010 cannot be bypassed by adding a tool.
- Cost: the contract table in `ingest.py` is a module dict, so changing it is a
  code deploy. That is correct while contracts change with integrations; it is
  wrong once operators need to edit them, which is the trigger below.

## Earned-complexity trigger
Move contracts from a module dict to a `connector_contract` table with
versioning and an approval workflow when **operators need to change a contract
without shipping code**, or at **more than ~15 connectors**, where a single
Python dict stops being reviewable and per-connector contract ownership matters.
At that point contract changes themselves need audit entries and a rollback.
