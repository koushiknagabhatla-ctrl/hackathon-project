# Runbook — Agent compromise

**Severity: HIGH.** An agent behaving outside its declared scope. Revoke first,
investigate second — the agent cannot act above R2, so the blast radius is
bounded, but its *outputs* may have steered a human.

## Detection
- `agent.forbidden_zone_blocked` audit events — the agent reached outside its
  declared scope.
- `claim.dropped_unsupported` at an abnormal rate: the grounding check is
  catching statements the agent should not have produced.
- `plan.action_dropped_out_of_catalogue`: the agent named a tool it cannot see.
- `action.blocked` with `tool_not_allowed`, `identity_invalid` or
  `tenant_mismatch` attributed to an agent principal.
- `injection_flags` populated on many consecutive runs (see
  `source-poisoning.md` if the flags trace to one connector).
- Plans that are structurally odd: same tool repeated, targets outside the
  incident's geography, escalating tier requests.

```bash
sqlite3 auralis.db "SELECT at, kind, actor_id, subject_id, substr(payload,1,120)
  FROM audit_event WHERE actor_kind='agent' AND kind LIKE 'agent.%'
  ORDER BY seq DESC LIMIT 40;"
```

## Immediate action
**Revoke the agent identity. Dual control is required and that is deliberate.**

```bash
curl -X POST localhost:8000/v1/admin/agents/p_agent/revoke \
  -H "X-Auralis-Principal: p_admin" -H "Content-Type: application/json" \
  -d '{"second_approver_id":"p_approver","reason":"suspected compromise"}'
```

`gateway.revoke_agent` in one transaction: sets `principal.status='revoked'`,
halts every open `agent_run`, and blocks that agent's `draft`/`validated`/
`approved`/`executing` plans **and their actions**. From that moment
`main.py::get_principal` returns 403 and `bundle::IDENTITY_VALID` denies.

> ⚠️ At time of writing the route wiring for this endpoint is broken (see
> `docs/architecture/data-flow.md`, drift table). The direct fallback is
> `python -c "from services.api.core import gateway; print(gateway.revoke_agent('p_agent','p_admin','p_approver'))"`.
> Verify it worked: `sqlite3 auralis.db "SELECT id,status FROM principal WHERE id='p_agent';"`

Then freeze the human side: tell approvers to hold on every plan authored by
that agent, including ones already approved but not executed.

## Diagnosis
Reconstruct exactly what the agent saw and said. Every agent run is attributable:

```sql
SELECT id, agent_id, prompt_template, prompt_version, model_version,
       evidence_snapshot_id, degraded, tokens_in, tokens_out, output
FROM agent_run WHERE agent_id = 'p_agent' ORDER BY started_at DESC;
```

Then answer, in order:
1. **What input turned it?** Load the `evidence_snapshot` behind the first bad
   run. Was there attacker-controlled text in it? Check `injection_flags` on the
   run — `firewall()` records which shapes fired.
2. **Was it the agent or the model?** A `degraded=1` run means the deterministic
   generator produced the output — that is a *code* bug, not a compromise.
3. **What did it produce?** `claim_ids` on the run, and the plans it authored.
4. **Did any of it reach effect?** Cross-check `action` rows: an agent cannot
   execute (R2 hard cap), so any executed action was run by a *human* principal
   who accepted the agent's plan. That human needs to be interviewed, not blamed.

## Recovery
1. Retract the affected claims — `claims.set_status(id, 'retracted', reason)`.
   Rows are never deleted; the retraction is an audit event.
2. Re-plan from the same incident with a clean agent identity, or manually.
3. If any action executed on a bad plan and is reversible, roll back via
   `POST /v1/actions/{id}/rollback`. If irreversible (a published alert), go to
   `incorrect-public-alert.md`.
4. Only re-enable the agent after the input path is fixed. Re-enabling is
   another dual-control admin action and should be recorded as such.

## Post-incident
- Was the harm from what the agent *did* or from what a human *believed*?
  In this architecture it is almost always the second, which means the finding
  belongs to the UI: does the operator screen make it obvious that a plan is an
  agent draft and which evidence it rests on?
- Add the input that turned the agent to the injection corpus, then confirm the
  invariant that actually held — that the agent could not act — and write it up.
  The control that worked is the one worth documenting.
- If `agent.forbidden_zone_blocked` fired and nobody was paged, that is the real
  defect. Fix the alerting, not the agent.
