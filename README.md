# Auralis Autonomous City — vertical slice

Evidence-grounded, policy-bounded, auditable urban intelligence.

This repository implements the PRD v3.0 **vertical slice**: one complete
workflow proven end to end, rather than a partial municipal platform.

```
evidence → AI analysis → prediction → policy → authority
        → controlled action → verification → audit → replay
```

The thesis, enforced in code and not merely in prose:

- **The LLM is never the source of truth.** Forecasts, risk tiers, policy and
  verification are deterministic. The model does language work only.
- **Policy lives outside the model.** `core/policy.py` never imports `agents/`,
  and a test enforces that.
- **The tool gateway is the only path from plan to effect.**
- **Nothing closes on assumption.** Actions are verified by read-back; a
  timeout is `UNKNOWN`, never success and never failure.
- **Every consequential workflow replays from an append-only hash-chained
  ledger.** Tampering is detectable, and the Audit screen proves it.

## Run it

Prerequisites: Python 3.13+, Node 20+. No Docker required.

```bash
# 1. API dependencies
python -m pip install -r services/api/requirements.txt

# 2. Seed the city (idempotent)
python scripts/seed_db.py

# 3. API on :8000
python -m uvicorn services.api.main:app --reload --port 8000

# 4. Web on :3000 (second terminal)
cd apps/web && npm install && npm run dev
```

Open <http://127.0.0.1:3000>. API docs at <http://127.0.0.1:8000/docs>.

### The 10-minute demo

```bash
python scripts/run_demo.py          # drives every beat, exits non-zero on failure
```

Presenter script and recovery steps: [docs/DEMO.md](docs/DEMO.md).

### Tests

```bash
python -m pytest -q                 # all lanes
python -m pytest tests/test_acceptance.py -q   # the acceptance gates
```

## LLM configuration

The system runs **fully offline by default**. With no API key the LLM gateway
falls back to a deterministic generator, reports `degraded: true`, and every
other capability — detection, evidence, conflicts, policy, approval, execution,
verification, audit, replay — is unaffected. That is the designed degraded-mode
behaviour, not a limitation.

To enable real model calls:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
```

All model traffic flows through `services/api/agents/llm_gateway.py` — the
single chokepoint for routing, budgets, caching, PII redaction, injection
screening and per-workflow cost attribution. No other module may call a
provider.

## Layout

```
apps/web/           Next.js command centre, public portal, field PWA (13 routes + 404)
services/api/
  core/             db, ingest, evidence, claims, incident, twin, audit, geo   (lane A)
  core/             policy, risk, gateway, verify                              (lane B)
  tools/            manifest registry + sandbox twins                          (lane B)
  agents/           llm gateway, specialist agents, coordinator                (lane C)
policies/           versioned, hashed policy bundle
data/seed/          the seeded district, connectors, scenario script           (lane F)
schemas/contracts/  per-connector data contracts as code
tests/              unit lanes + the acceptance gates
docs/               CONTRACT.md (build contract), DEMO.md (presenter runbook)
```

## Honest scope

City infrastructure integrations are **simulated**. This build does not, and
must not, control real critical infrastructure. R5 safety-critical control is
deliberately registered only so the policy engine can be seen refusing it.

What production still requires: independent security assessment, authoritative
GIS and asset integration, contracted real feeds with SLAs, formal model
evaluation and red teaming, certified control integrations, real authority
mapping and legal review, and enterprise retention, legal hold and DR.

Storage note: SQLite is the storage engine here; all geometry runs on
Shapely/GEOS, the same engine PostGIS uses, so spatial results are equivalent.
The swap to PostgreSQL/PostGIS is contained to `core/repo.py`.
