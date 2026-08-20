# 0012 — Zero-trust identity for humans and workloads

**Status:** Accepted (identity model real; credential layer is a prototype)

## Context
Agents act. If an agent's identity is "the service account the API runs as",
then revoking one misbehaving agent means turning off the API, and the audit
log says the API did it.

## Decision
Humans and workloads share **one** identity model: the `principal` table.

| Column | Purpose |
|---|---|
| `role` | `operator` \| `approver` \| `auditor` \| `admin` \| `agent` \| `sim` |
| `authority` | statutory authority held, recorded on approvals |
| `spiffe_id` | workload identity for non-human principals |
| `trust_domain` | `prod` \| `sim` (ADR 0008) |
| `status` | `active` \| `revoked` — checked on every request |
| `tenant_id` | required; no principal is global |

Enforcement points:
- `main.py::get_principal` rejects unknown or non-`active` principals with 401
  or 403 **before any router logic runs**.
- `bundle::IDENTITY_VALID` denies a principal that is missing, not active, or
  is an `agent` with no `spiffe_id`. An agent without a workload identity
  cannot act, full stop.
- `TENANT_MATCH` denies when the principal tenant, resource tenant or target
  asset tenant disagree.
- `ROLE_MAX_TIER` / `ROLE_HARD_MAX` bound every role. `agent` caps at **R2** —
  an agent can plan and draft, and can never act, under any approval:

```
public R0 | auditor R0 | sim R1 | agent R2 | operator R3(hard R4)
approver R4 | admin R4      # nobody is ever granted R5
```
- Tool *visibility* is itself an authorisation decision:
  `registry.manifest_for(principal)` returns only tools the role may see, so an
  agent cannot enumerate a tool it may not use.
- Revocation is immediate and total: `gateway.revoke_agent` sets
  `status='revoked'`, halts open `agent_run` rows, and blocks that agent's
  draft/validated/approved/executing plans and their actions (ADR see
  `security/drills.md`).

## What this build actually does
The identity *model* is real and enforced. The *credential* layer is not: the
API authenticates with a bare `X-Auralis-Principal` header and no secret. There
is no SPIFFE/SPIRE deployment, no mTLS, no token issuance, no expiry. The
`spiffe_id` column is populated and checked for presence, not verified against
an issuing authority.

This is stated plainly because it is the single largest gap between this build
and a deployable one. See `docs/production-gap.md`.

## Consequences
- Least privilege, tenant isolation and per-agent revocation are demonstrable
  today and testable.
- Anyone who can reach the API can assume any principal. The prototype must
  never be exposed beyond localhost.

## Earned-complexity trigger
Replace the header with real credentials **before any deployment reachable from
outside the operator's own machine** — that is the trigger, and it is binary,
not a scale threshold. Minimum viable replacement: OIDC for humans (mapping to
`principal.id`), SPIRE-issued SVIDs with mTLS for workloads, short-lived tokens,
and `authority` sourced from the city's own directory rather than a seed file.
