# 0014 — The LLM gateway is the single chokepoint for cost, safety and routing

**Status:** Accepted

## Context
Once two modules can call a provider, there is no single place to answer "what
did we send, what did it cost, and was there a phone number in it".

## Decision
`services/api/agents/llm_gateway.py::complete()` is the only function in the
system permitted to reach a model provider. Every agent — `evidence_agent`,
`forecast_agent`, `situation`, `planning` — goes through it. It owns:

| Concern | Mechanism |
|---|---|
| Prompt versioning | `prompts/*.md`, version returned with every result and stored on `agent_run.prompt_version` |
| PII egress redaction | `redact()` over the **outbound** variable tree before any byte leaves the process — email, phone, national-id shapes. Deliberately over-eager |
| Context firewall | `firewall()` = `sanitize()` + `screen()` over untrusted DATA fields, replacing matches with visible `[neutralised:<flag>]` markers |
| Caching | sha256 over template, prompt version, model id, redacted variables and schema. A repeated analysis costs nothing |
| Budget | `spend(workflow_id)` sums `agent_run` tokens and cost **from the database**, so a restart cannot reset a budget. Over budget → deterministic path with reason `budget_exceeded` |
| Cost attribution | `cost_report()` gives `llm_cost_usd` and `cost_per_incident_usd` for `/v1/metrics/ops` |
| Degradation | **never raises.** No key, budget spent, HTTP error, malformed JSON, schema mismatch → the agent's own deterministic `fallback` runs, `degraded=True`, `reason` recorded |
| Logging | full request/response into `agent_run` with tokens, cost, model version, evidence snapshot id |

Two properties worth stating explicitly:

1. **Offline is the default path, not a fallback of last resort.** With no
   `ANTHROPIC_API_KEY` every agent still returns a full, grounded answer from
   its deterministic generator. The demo runs on that path.
2. **The context firewall is defence in depth only, and the code says so.**
   The module's own comment: an attacker who phrases an injection outside the
   patterns gets through, and that is accepted, *because no policy enforcement
   depends on this function*. A fully persuaded model still cannot emit an
   ungrounded claim (`core/claims.py`), name a tool outside the catalogue
   (`agents/planning.py` drops it post-parse), lower a tier (`core/risk.py`),
   clear a rule (`core/policy.py`) or reach the world (`core/gateway.py`).

Prompts carry all twelve PRD context requirements — bounded objective, task id
and jurisdiction, evidence snapshot with source and time metadata, explicit
unknowns, allowed tools and schemas, action-risk policy reference, output JSON
schema, stop conditions, untrusted-data marker, and the three prohibitions
(never claim a tool ran without a result, never invent current state, never
bypass approval). A test fails the build if a template loses one.

## Consequences
- One file to audit for what leaves the process, and one place to change a
  provider, model id or price table.
- Cost per incident is a real number in the ops metrics, not an estimate.
- Cost: every agent must supply a deterministic `fallback` of the same output
  shape. That is real work and it is what makes degraded mode honest.

## Earned-complexity trigger
Revisit at **more than one provider or more than 3 model ids in production**,
where routing becomes a policy of its own (task class → model), or at
**>10 concurrent model calls**, where the in-process dict cache and synchronous
`httpx.post` become the bottleneck. The cache key is already stable, so a
persistent `llm_cache` table is a drop-in when warm cache must survive restart.
