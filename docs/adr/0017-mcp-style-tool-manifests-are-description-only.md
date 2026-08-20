# 0017 — MCP-style tool manifests are description only; authorization stays server-side

**Status:** Accepted

## Context
Tool manifests look like permissions. They are not. A manifest is a description
an agent reads to know a tool exists and what shape its arguments take. If the
manifest is also the authorization decision, then anything that can influence
what an agent reads can influence what it may do — which is exactly the
tool-poisoning class (MITRE ATLAS `AML.T0110`, OWASP `ASI02`).

## Decision
The manifest describes. The server decides. Always both, never one.

- `tool_manifest` carries `input_schema`, `output_schema`, `risk_class`,
  `action_class`, `sandbox_ref`, `egress_allowlist`, `verification_method`,
  `rollback_tool_id`, `allowed_roles` and a `signature`.
- **`risk_class` is a floor, not the tier.** The tier that governs an action is
  recomputed per action *instance* by `core/risk.py` at execution time from the
  live target's criticality, blast radius, evidence age, public-facing flag and
  reversibility. The same tool is R3 against a small reversible target and R4
  against a public-facing one. A manifest cannot declare itself low-risk.
- **Manifests are signed and verified on use.** `registry.sign()` is an HMAC
  over the canonical JSON of the manifest excluding the signature;
  `registry.require()` re-verifies before every execution and raises
  `ManifestRejected` on mismatch. A manifest edited in the database does not
  become authoritative — it becomes invalid.
- **Visibility is itself an authorization decision.**
  `registry.manifest_for(principal)` filters by `allowed_roles` **and**
  `bundle.role_permits(role, risk_class)`. An agent cannot enumerate a tool it
  may not use. `GET /v1/tools` returns that filtered view.
- **Visibility is not permission.** `gateway.execute` re-checks
  `registry.visible_to()` at step 3 and then runs the full policy evaluation at
  step 7 anyway. Seeing a tool never implies being allowed to call it.
- A prohibited tool stays **visible** to its allow-listed roles on purpose:
  `scada.direct_control` is registered so the policy engine refuses it visibly,
  rather than the refusal being indistinguishable from a missing feature.

## Consequences
- An attacker who controls agent-visible text can, at most, cause the agent to
  request a tool. The request then meets the manifest schema check, the
  visibility check, the identity check, the tenant check, the simulation
  barrier, the policy engine, the freshness recheck, the risk gate, the
  approval gate and idempotency — none of which read the manifest's own
  claim about its risk.
- Adding a tool is a governed act: no sandbox twin, no registration; no
  verification method on a write tool, no registration.
- Cost: manifest metadata is duplicated between the registry module and the
  `tool_manifest` table (`registry.sync_to_db`), which must stay in step.
- `AURALIS_TOOL_SIGNING_KEY` defaults to a development HMAC key. That is a
  prototype credential, not a security boundary — see `docs/production-gap.md`.

## Earned-complexity trigger
Move signing to a KMS-held asymmetric key, and manifest distribution to a
signed bundle with rotation, when **tools are supplied by anyone other than
this repository** — a third-party MCP server, a vendor integration, or a second
team. `registry._key()` is the only function that changes; the canonical-JSON
payload and verify path stay identical. Also revisit at **>30 registered
tools**, where per-role allow-lists need to become capability groups.
