# Auralis vertical slice — build contract

Single source of truth for every worker on this repo. If code and this file
disagree, this file wins until it is amended.

## Stack (fixed, do not substitute)

| Layer | Choice |
|---|---|
| API | Python 3.13 + FastAPI + Pydantic v2, `uvicorn` |
| DB | SQLite (WAL), schema at `services/api/schema.sql` |
| Geometry | **Shapely (GEOS)** + **pyproj**. Never hand-roll lat/lon math. |
| Web | Next.js (App Router) + TypeScript + MapLibre GL JS + GSAP/ScrollTrigger |
| Realtime | SSE (`text/event-stream`), not WebSocket |
| LLM | `services/api/agents/llm_gateway.py` — the ONLY path to a model |

Ports: API `http://127.0.0.1:8000`, web `http://127.0.0.1:3000`.

## Non-negotiable invariants

These are release gates. A change that breaks one is a bug, not a tradeoff.

1. **Grounding.** A `claim` of class `fact` or `forecast` MUST carry a
   non-empty `evidence_ids` array, and every id MUST exist in `evidence`.
   Enforced server-side in `core/claims.py`, not by prompt text.
2. **Policy outside the model.** `core/policy.py` is pure deterministic
   Python. It never imports anything under `agents/`. No model output can
   change a policy outcome — only the evidence and the action instance can.
3. **Single action path.** All external effect goes through
   `core/gateway.py::execute`. No router calls a tool directly.
4. **Sandbox twin required.** `tool_manifest.sandbox_ref` empty => registration
   rejected. Every write tool has a sandbox implementation.
5. **Simulation barrier.** A principal with `trust_domain='sim'` is rejected by
   the tool gateway for any production tool, at the gateway, with an audit
   event. Tested in `tests/test_simulation_barrier.py`.
6. **Audit is append-only + hash-chained.** `entry_hash = sha256(prev_hash +
   canonical_json(entry_without_hashes))`. No UPDATE or DELETE on
   `audit_event`, ever. Chain verification is an endpoint.
7. **Verify, then close.** An action reaches `verified` only after read-back
   comparison. Timeout => `unknown`, never `failed` and never `executed`.
8. **Idempotency.** Every write tool call carries `idempotency_key`; a repeat
   returns the first result and creates no second effect.
9. **Synthetic never presented as observed.** `evidence_class='synthetic'`
   renders with a synthetic label in every surface.
10. **Degraded mode.** If the LLM path fails, detection, incidents, evidence,
    policy, audit and the whole UI stay functional. `degraded=1` is surfaced.

## Canonical types (Pydantic in `services/api/models.py`)

Field names below are the wire format. TypeScript mirrors live in
`apps/web/src/lib/types.ts` and MUST match exactly (snake_case on the wire).

```
RiskTier   = "R0"|"R1"|"R2"|"R3"|"R4"|"R5"
ClaimClass = "fact"|"forecast"|"recommendation"
EvidenceClass = "observation"|"derived"|"synthetic"|"synthetic-corroboration"
TrustTier  = "statutory"|"certified"|"verified"|"crowdsourced"|"unknown"
Verification = "SUCCESS"|"DIFFERENCE"|"FAILED"|"UNKNOWN"
IncidentState = "detected"|"assessing"|"planning"|"awaiting_approval"
              |"acting"|"verifying"|"closed"
PolicyEffect = "allow"|"deny"|"require_approval"
```

`EvidenceRef` — the shape the UI renders as an evidence chip, everywhere:

```json
{ "id":"ev_...", "source":"Hydrology SCADA", "trust_tier":"certified",
  "observed_at":"2026-08-20T09:14:00Z", "age_s":142, "fresh":true,
  "evidence_class":"observation", "status":"valid" }
```

`Claim` — every AI-authored statement in the UI is one of these:

```json
{ "id":"cl_...", "statement":"...", "claim_class":"forecast",
  "evidence_ids":["ev_1"], "uncertainty":{"lower":0.4,"upper":1.1,"unit":"m"},
  "author":"forecast-agent","author_kind":"agent","status":"active" }
```

## HTTP API

Auth: header `X-Auralis-Principal: <principal_id>`. Every response carries
`X-Correlation-Id`. Every list endpoint is tenant-scoped from the principal.

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/events` | ingest; validate, dedup, quarantine, emit evidence |
| GET | `/v1/incidents` | list |
| GET | `/v1/incidents/{id}` | detail + evidence + claims + conflicts |
| POST | `/v1/incidents/{id}/assess` | run agents, returns claims |
| GET/POST | `/v1/incidents/{id}/plans` | list / generate candidate plans |
| GET | `/v1/plans/{id}` | plan + actions + per-action policy decision |
| POST | `/v1/plans/{id}/approve` | body: `{action_id, decision, rationale}` |
| POST | `/v1/actions/{id}/execute` | gateway path; requires idempotency key |
| POST | `/v1/actions/{id}/rollback` | compensating action |
| GET | `/v1/evidence/{id}` | R0 read |
| GET | `/v1/claims?incident_id=` | claims ledger |
| GET | `/v1/twin/query?asset_id=&depth=` | dependency traversal + blast radius |
| GET | `/v1/twin/snapshot?at=` | point-in-time twin |
| GET | `/v1/audit/{workflow_id}` | ordered ledger slice |
| GET | `/v1/audit/{workflow_id}/export` | JSON export used by Replay |
| GET | `/v1/audit/verify` | recompute hash chain, report first break |
| GET | `/v1/policies/decisions` | decision log w/ inputs hash |
| POST | `/v1/simulations` | `{scenario, seed, overrides}` counterfactual |
| GET | `/v1/data-health` | per-connector freshness, quality, conflicts |
| GET | `/v1/metrics/ops` | SLIs, LLM cost, policy blocks, tool errors |
| POST | `/v1/admin/agents/{id}/revoke` | kill switch, R4-gated, dual control |
| GET | `/v1/stream` | SSE: incidents, actions, evidence, health |
| GET | `/v1/public/status` | redacted, disclosure-delayed |
| GET/POST | `/v1/field/work-orders` | field PWA |
| POST | `/v1/demo/reset` \| `/v1/demo/step` | scripted 10-minute demo driver |

Errors: `{"error":{"code","message","detail","correlation_id"}}`. A policy
denial is **200** on the plan view (it is data, shown in the UI) and **403**
with `code="policy_denied"` and the exact `rule_id` + `reason` on execute.

## Risk tier is computed, never static

`core/risk.py::compute_tier(action_class, asset_criticality, blast_radius,
evidence_age_s, public_facing, reversible=True) -> (RiskTier, inputs_dict)`.
Same tool can be R3 or R4 depending on target. Deterministic and unit-tested.

## Approval vocabulary

`ApprovalRequest.decision` is `approved|denied` — that is the human approval
API. The `approval.decision` COLUMN additionally accepts `confirmed`, written
by the verification path when a tool declares
`verification_method='human_confirmation'`. A confirmation is evidence that an
effect happened; it is not an authorization. Never treat `confirmed` as
approval, and never let it satisfy an approval gate.

## Design tokens (from the PRD design appendix, exact)

```
--bg #F4F4F4   --text #000000  --accent #FA8128  --surface #FFFFFF
--muted #5B5B5B  --line #D8D8D8
radius: 18px surfaces, 12px controls, 999px pills
grid: 12col desktop (max 1440px) / 4col tablet / 1col mobile, 18-20px mobile pad
fonts: Morhefa = navbar, Givonic = all UI copy, UnicaOne/Quffer = numerals only
```

Severity, verification and permission are NEVER color-only — always paired
with a text label and an icon or pattern. WCAG 2.2 AA is a gate.

## Routes (13 + 404, all responsive)

`/` `/command` `/incidents/[id]` `/plans/[id]` `/actions` `/trace` `/data-health`
`/audit` `/simulation` `/executive` `/public` `/governance` `/field` + `not-found`

## Ownership map (do not edit outside your lane)

| Lane | Paths |
|---|---|
| A data core | `services/api/core/{db,repo,ingest,evidence,claims,incident,twin,audit}.py` |
| B safety | `services/api/core/{policy,risk,gateway,verify}.py`, `services/api/tools/**`, `policies/**` |
| C AI | `services/api/agents/**`, `services/api/core/forecast.py` |
| D web shell | `apps/web/{app/layout,app/globals.css,components/shell,lib}/**` |
| E web screens | `apps/web/app/**` page files only |
| F scenario | `data/**`, `services/api/core/simulator.py`, `tests/**`, `scripts/**` |

Shared files (`models.py`, `main.py`, `types.ts`) are written by the
coordinator only. Need a change there? Report it, do not edit.
