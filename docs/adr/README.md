# Architecture Decision Records

One file per decision. Every ADR carries an **earned-complexity trigger**: the
measurable threshold at which the decision must be revisited. A decision with
no trigger is a decision nobody will ever reopen, which is how prototypes
become legacy.

Status vocabulary used here:
- **Accepted** — decided and implemented in this build.
- **Accepted (slice-scoped)** — decided for the vertical slice, with a named
  swap trigger.
- **Partially implemented / Accepted in design** — the constraint is real and
  binds the architecture, but the mechanism is not built. Each such ADR says so
  in a "What this build actually does" section.

| # | Decision | Status | Revisit when |
|---|---|---|---|
| [0001](0001-llm-is-not-the-source-of-truth.md) | LLM is not the source of truth | Accepted | >5 numeric model families, or a forecast that is not a parameterised curve |
| [0002](0002-policy-lives-outside-the-model.md) | Policy lives outside the model | Accepted | >40 rules, or 3+ tenants with divergent rule sets |
| [0003](0003-tool-gateway-is-the-single-action-path.md) | Tool gateway is the single action path | Accepted | ~50 invocations/s, or the first tool that outlives its request |
| [0004](0004-evidence-service-with-provenance-and-expiry.md) | Evidence with provenance and expiry | Accepted | ~10k evidence rows/subject/day, or external integrity verification |
| [0005](0005-append-only-hash-chained-audit.md) | Append-only hash-chained audit | Accepted | first third-party-verified audit, or ~10M entries |
| [0006](0006-sqlite-shapely-instead-of-postgis.md) | SQLite + Shapely/GEOS, not PostgreSQL/PostGIS | Accepted (slice-scoped) | >1 API worker, >50k assets, PITR/replication/RLS, or >20 writes/s |
| [0007](0007-digital-twin-as-operational-graph.md) | Twin is an operational graph, not a visualisation | Accepted | >100k assets, or weighted/multi-hop queries |
| [0008](0008-simulation-in-a-separate-trust-domain.md) | Simulation in a separate trust domain | Accepted | simulation >10s wall clock or >1/min; any sim→prod write |
| [0009](0009-human-approval-for-public-impact-action.md) | Human approval for public-impact action | Accepted | >20 approvals/hour in a live event; second jurisdiction |
| [0010](0010-verify-after-action-never-assume-success.md) | Verify after action, never assume success | Accepted | first tool whose effect propagates slower than its request |
| [0011](0011-model-registry-and-evaluation-gates.md) | Model registry and evaluation gates | Partially implemented | first fitted model, or >2 model versions live |
| [0012](0012-zero-trust-identity-for-humans-and-workloads.md) | Zero-trust identity for humans and workloads | Accepted (credentials are prototype) | **any deployment reachable beyond localhost** |
| [0013](0013-claims-ledger-grounding-as-a-data-structure.md) | Claims ledger — grounding as a data structure | Accepted | >~50 claims/hour, or first cited-but-unsupported claim that changed an action |
| [0014](0014-llm-gateway-single-chokepoint.md) | LLM gateway as the single chokepoint | Accepted | >1 provider or >3 model ids; >10 concurrent calls |
| [0015](0015-contracts-as-code-as-the-enforcement-point.md) | Contracts as code are the enforcement point | Accepted | operator-editable contracts, or >15 connectors |
| [0016](0016-deterministic-python-policy-bundle-instead-of-opa-rego.md) | Deterministic Python policy bundle, not OPA/Rego | Accepted (slice-scoped) | second consumer, non-engineer authors, >3 divergent bundles, or coverage evidence |
| [0017](0017-mcp-style-tool-manifests-are-description-only.md) | Tool manifests describe; the server authorizes | Accepted | tools supplied outside this repo; >30 tools |
| [0018](0018-edge-autonomy-ceiling-r2-when-islanded.md) | Edge autonomy ceiling of R2 when islanded | Design only — not built | contracted offline field operation, or >5 outage-prone sites |
| [0019](0019-federation-by-policy-sovereignty-by-construction.md) | Federation by policy, sovereignty by construction | Design; single-tenant here | **the second tenant** |
| [0020](0020-exit-drill-as-an-acceptance-gate.md) | Exit drill as an acceptance gate | Accepted (partly manual) | before any pilot agreement; on every schema change touching audit payloads |

## The three that carry the most weight

- **0002 + 0016** together are the claim "policy is outside the model". 0002 is
  the invariant; 0016 is the honest account of the engine that implements it.
- **0006** is the storage tradeoff. Same geometry engine as PostGIS, different
  storage engine, with the swap trigger named.
- **0012** names the largest gap in this build: the identity *model* is real
  and enforced, the *credential* layer is a header with no secret.
