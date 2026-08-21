# Repository structure

Mapped 1:1 onto PRD v3.0 §58 so a reviewer can walk the spec and the repo side
by side. Where this build collapses several §58 services into one process, the
directory still exists and the ADR names the threshold at which it splits out.

```
auralis/
├── apps/
│   └── web/                    Next.js 15 — all 13 experiences + 404
│       ├── app/                route segments (App Router)
│       │   ├── command/        Command Center
│       │   ├── incidents/[id]/ Incident Room
│       │   ├── plans/[id]/     Plan Review
│       │   ├── actions/        Action Monitor
│       │   ├── trace/          AI Trace
│       │   ├── data-health/    Data Health
│       │   ├── audit/          Audit + replay
│       │   ├── simulation/     Simulation + counterfactual
│       │   ├── executive/      Executive view
│       │   ├── public/         Public Status Portal
│       │   ├── governance/     Governance / Settings
│       │   ├── field/          Field PWA
│       │   └── not-found.tsx   404
│       ├── components/
│       │   ├── shell/          navbar, status rail, preloader, bottom nav
│       │   ├── ui/             EvidenceChip, ClaimBlock, RiskBadge, ...
│       │   └── map/            MapLibre + deck.gl surfaces
│       ├── lib/                api client, types, motion, locations
│       └── public/fonts/       Morhefa · Givonic · Unica One · Quffer
│
├── services/api/               single deployable (see ADR-0021)
│   ├── main.py                 app, middleware, identity, error envelope
│   ├── models.py               wire contracts — the shared truth
│   ├── schema.sql              SQLite DDL
│   ├── routers/                the /v1 surface, thin
│   ├── core/
│   │   ├── db · repo · geo             storage + geometry (Shapely/GEOS)
│   │   ├── ingest · evidence · claims  data plane + grounding
│   │   ├── incident · twin             detection + operational graph
│   │   ├── audit                       append-only hash chain
│   │   ├── policy · risk               deterministic, never imports agents/
│   │   ├── gateway · verify            single action path + verification
│   │   ├── forecast                    deterministic numeric models
│   │   ├── simulator · seed            scenario player + counterfactual
│   ├── tools/                  manifest registry + sandbox twins
│   └── agents/                 LLM gateway, specialists, coordinator
│       └── prompts/            versioned prompt templates (release artifacts)
│
├── policies/                   versioned + hashed policy bundle
├── schemas/contracts/          per-connector data contracts as code
├── data/seed/                  Vijayawada twin, connectors, scenario script
├── scripts/                    seed_db · run_demo
├── tests/                      lane unit suites + acceptance gates
├── docs/
│   ├── CONTRACT.md             the build contract
│   ├── DEMO.md                 presenter runbook
│   ├── STRUCTURE.md            this file
│   ├── adr/                    20 architecture decision records
│   ├── architecture/           C4 context/containers/components, trust boundaries
│   ├── runbooks/               15 operational runbooks
│   ├── compliance-map.md       India / DPDP / CERT-In / NDMA + EU baseline
│   └── production-gap.md       what this proves vs what production needs
└── security/
    ├── threat-model.md         agentic threats -> control -> enforcing module -> test
    ├── prohibited-actions.md   registry, each with its enforcing rule id
    └── drills.md               kill-switch, sim-barrier, tamper, exit drills
```

## Where this collapses §58, and why

§58 lists fourteen services (`api-gateway`, `ingestion`, `incident`,
`evidence`, `claims`, `digital-twin`, `policy`, `tool-gateway`, `audit`,
`notifications`, `llm-gateway`, `federation`, `edge-agent`, `simulation-api`).
This build runs them as **modules in one process**, each in its own file with
the same boundaries and the same interfaces.

That is the PRD's own earned-complexity rule (§10): a single-jurisdiction pilot
does not need fourteen deployables, and splitting them now would buy network
hops, distributed tracing and deployment surface without buying isolation this
slice can use. The module boundaries are real, so the split is mechanical when
a threshold is crossed.

| §58 service | Module here | Split it out when |
|---|---|---|
| ingestion | `core/ingest.py` | sustained ingest > 5k events/min |
| incident | `core/incident.py` | > 200 concurrent active workflows |
| evidence + claims | `core/evidence.py`, `core/claims.py` | evidence retrieval p95 > 800 ms |
| digital-twin | `core/twin.py` | > 100k assets or traversal p95 > 500 ms |
| policy | `core/policy.py` | policy decisions become a latency floor, or a second tenant needs its own bundle lifecycle |
| tool-gateway | `core/gateway.py` | tools need independent scaling or per-tool network egress isolation |
| audit | `core/audit.py` | audit write contention, or retention moves to object storage |
| llm-gateway | `agents/llm_gateway.py` | more than one consuming service, or provider routing needs its own SLO |
| simulation-api | `core/simulator.py` | simulation load competes with production for CPU |
| federation, edge-agent, notifications | not built | out of slice scope — see `docs/production-gap.md` |

The one boundary that is **not** negotiable and is enforced rather than
organisational: `core/policy.py` and `core/risk.py` never import `agents/`.
A test asserts it. Policy outside the model is a property of the build, not a
convention.
