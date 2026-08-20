# Runbook — LLM outage

**Severity: LOW.** This is a designed operating mode, not an incident. Nothing
that gates a decision depends on the model.

## Detection
- `GET /v1/metrics/ops` → `degraded: true`, `llm_calls` flat.
- `agent_run` rows with `degraded=1` and a populated `reason`:
  ```bash
  sqlite3 auralis.db "SELECT agent_id, model_version, degraded, substr(output,1,80)
    FROM agent_run ORDER BY started_at DESC LIMIT 10;"
  ```
  `model_version = 'deterministic-template-1.0.0'` means the fallback ran.
- API log line: `llm call failed for <agent>/<template>: <reason>`.
- UI shows the degraded banner; narrative text is terser and templated.

## Immediate action
**None required.** Confirm the rest of the system is unaffected, in this order:

```bash
curl -s localhost:8000/v1/readiness            # database, evidence, twin, policy, tools
curl -s -H "X-Auralis-Principal: p_operator" localhost:8000/v1/incidents | head
curl -s -H "X-Auralis-Principal: p_auditor"  localhost:8000/v1/audit/verify
```

Detection, evidence, conflicts, forecasts, policy, approval, execution,
verification and audit are all model-free. If any of those are also broken, you
have a different incident — this is not the runbook.

Tell the operators on shift: *"AI narration is degraded; numbers and decisions
are unaffected."* Do not tell them the system is down.

## Diagnosis
`GatewayResult.reason` distinguishes the causes, and they need different actions:

| Reason prefix | Cause | Action |
|---|---|---|
| `no_api_key` | `ANTHROPIC_API_KEY` unset | Expected offline mode. Set the key if narration is wanted |
| `budget_exceeded` | Workflow hit `AURALIS_WORKFLOW_TOKEN_BUDGET` / cost budget | **Not an outage.** Go to `llm-cost-anomaly.md` — a runaway workflow is the more likely story |
| `HTTPStatusError: 401/403` | Bad or revoked key | Rotate the key |
| `HTTPStatusError: 429` | Rate limited | Back off; check for a loop |
| `HTTPStatusError: 5xx` / `ConnectError` / `ReadTimeout` | Provider or network | Check provider status; confirm egress to `api.anthropic.com` |
| `ValidationError` / JSON parse | Model returned off-schema output | Check whether a prompt template changed; pin the previous `prompt_version` |

Note that `complete()` retries once and then degrades. A single transient error
never surfaces to a caller.

## Recovery
1. Fix the underlying cause above.
2. Clear the response cache so a degraded result is not served from memory:
   restart the API, or in a shell `agents.llm_gateway.reset_cache()`.
3. Re-run assessment on any incident where narration matters:
   `POST /v1/incidents/{id}/assess`.
4. Confirm a fresh `agent_run` row has `degraded=0` and a real `model_version`.

Do **not** re-run the workflow to "get better numbers". The numbers were never
model-produced; re-running changes only prose.

## Post-incident
- Record the outage window and the affected incident ids. Their `agent_run`
  rows already carry `degraded=1` — the audit trail is self-documenting.
- If degraded narration made an operator hesitate, that is a UI finding, not an
  LLM finding: the degraded banner needs to say *what is unaffected*, not just
  that something is degraded.
- If the cause was `budget_exceeded`, review whether the per-workflow budget is
  set correctly for a multi-hour event. A flood incident is not a chat session.
