# 0022 — A local fine-tuned model for Andhra Pradesh, behind the same gateway

**Status:** Implemented — with one debt this ADR names explicitly (see
"Consequences")

## Context
Every language-model call in this system goes through
`agents/llm_gateway.py` (ADR 0014), and until now that gateway had exactly two
backends: a hosted frontier model when `ANTHROPIC_API_KEY` is set, and a
deterministic template generator otherwise. That is a good default and the demo
runs on the deterministic path. It also has three properties that are awkward
for a municipal deployment in Andhra Pradesh:

1. **Data egress.** Evidence text — citizen grievances, gauge readings, road
   names, incident narratives — leaves the process to a third party. PII is
   redacted on the way out (`llm_gateway.redact`), which reduces the exposure
   but does not remove it. For a municipality, "the data never left the box" is
   a materially stronger answer than "we redacted it first".
2. **A key and a bill.** The hosted path needs a credential and costs money per
   token. A control room that cannot get a key gets the deterministic path.
3. **No domain knowledge.** A frontier model is excellent and generic. It has
   never seen Budameru's flood behaviour, the shape of an AP grievance record,
   or how a Vijayawada duty officer writes.

We have a fine-tune that addresses all three: a PEFT LoRA adapter (r=16,
alpha=32) over `Qwen/Qwen2.5-1.5B-Instruct`, trained on real Andhra Pradesh
evidence (`data_mode: real_ap_evidence`), best checkpoint 818, eval_loss 0.159.
It ships with a `model_envelope.json` declaring its geographic scope, five
behavioural rules and three limitations, and an `artifact_hashes.json` pinning
a sha256 for every file.

The question this ADR answers is not "is a 1.5B model as good as a frontier
model" — it plainly is not. It is "what is this model allowed to be, and what
has to be true before it is allowed to speak".

## Decision
Add `local` as a first-class backend behind the existing gateway, under the
same chokepoint rules and three new controls.

**It is an analysis layer, and nothing about the safety architecture moves.**
`core/policy.py`, `core/risk.py` and `core/gateway.py` do not import
`local_model.py` and never will; the tool catalogue is still filtered after the
model has spoken; retrieved content is still DATA, still passes through
`sanitize()`/`screen()`; and every statement it produces still has to survive
`core/claims.py`, which drops an ungrounded fact or forecast rather than
softening it. Deleting this file leaves a working product.

**1. Supply chain — verify before loading.** `verify_artifacts()` recomputes
sha256 for all 15 entries in `artifact_hashes.json` and compares them against
the pinned values. It runs inside `load()` *before* any weight is read. A
mismatch raises `ArtifactMismatch`, logs a security event, and the gateway
degrades to the deterministic path. ADR 0011 asked for hash-pinned,
provenance-recorded model artifacts; this is that control, executing.

**2. Envelope — enforced as data, not asked for in a prompt.** The envelope
says "Andhra Pradesh, India only". `check_envelope()` tests the request's
jurisdiction — derived by `agents/base.py` from the tenant row, never from
anything a model or a data field said — before the model is invoked. Outside
Andhra Pradesh, and for an unknown jurisdiction, the serving layer **abstains**:
`in_envelope=false` with a reason, the request is answered by the deterministic
generator, and the breach is written to the hash-chained ledger
(`model.out_of_envelope`). It does not extrapolate to a region it was not
trained on. The in-envelope case is recorded too (`model.envelope_checked`),
carrying the five rules, so the AI Trace view shows an operator what the model
is constrained to on every call, not only when something went wrong.

**3. Time — a real, generous, enforced timeout.** Greedy decoding
(temperature 0) for replay determinism, bounded `max_new_tokens`, and a hard
wall-clock budget (`AURALIS_LOCAL_MODEL_TIMEOUT_S`, default 240s). Generation
runs in a worker thread with `max_time` set inside it, so a request that blows
the budget gets the deterministic answer *and* the abandoned generation
releases the CPU instead of running to completion. Prompts are rendered through
the model's own `chat_template.jinja` via the tokenizer; the format is never
hand-rolled.

**Routing is explicit and the fallback is never silent.**
`AURALIS_LLM_BACKEND` is a comma-separated order, default
`local,anthropic,deterministic`; `deterministic` is always appended as the
terminal element, so no configuration can leave a request unanswered. Whichever
backend answers, `GatewayResult.backend`, `model_version` and `reason` say
which and why, the same values are written to `agent_run`, and
`cost_report()` reads the backends back **out of the rows the calls wrote**
rather than inferring them from configuration. An operator can never be shown
an answer without being able to see which model produced it.

**Serving never downloads.** The base model loads with
`local_files_only=True`. A cold Hugging Face cache makes the local backend
*unavailable* — the request is answered deterministically with that reason
recorded — rather than stalling an incident behind a 3GB fetch.
`scripts/warm_model.py` is the only downloader.

**Registration.** `model_version` gets a row (`mv_auralis_ap_urban_1`, kind
`llm`) carrying the base model, the adapter checkpoint, eval_loss, the pinned
adapter sha256 and the envelope JSON. `core/audit.py::export` already joins
`agent_run.model_version` to that row, so a replay shows exactly which model
saw which evidence and under what constraints.

## Consequences

**The honest trade-off.** A 1.5B model on CPU is slow. Measured on the
reference box (torch 2.11+cpu, no CUDA): 21.6s to load the weights once, then
**1.6 tokens per second** of generation — so a 384-token answer is about four
minutes, against roughly a second for the hosted path. It is also less capable
at general reasoning than a frontier model. In exchange it is
domain-tuned on real Andhra Pradesh evidence, needs no API key, costs nothing
per token, and **no municipal data leaves the process**. For this deployment
that privacy property is the point; the zero cost is a bonus, not the argument.
Operators who want speed and breadth set `AURALIS_LLM_BACKEND=anthropic,
deterministic` and pay for it, per incident, in a number the gateway already
reports.

- Three paths now exist where there were two. The blast radius is contained by
  the fact that all three produce the same schema-shaped JSON and every one of
  them is gated by the same grounding check downstream.
- A 1.5B model has no structured-output mode. Malformed JSON is common enough
  that it must be a normal event, not an error: it raises, the gateway degrades,
  and `agent_run` records the failure *with the offending text*. Watch that rate
  — a high one means the local backend is answering less often than the
  configuration suggests. Observed on the reference box: one run returned clean
  schema-shaped JSON, another died on an invalid `\` escape at char 666.
- **Its citations are not trustworthy, and that is survivable by design.** In a
  real run against the situation template the model returned well-formed JSON
  that cited `"evidence_ids": ["snap_1"]` — the *snapshot* id, not an evidence
  id. `agents/base.py::check_grounding` drops that claim ("cites evidence not
  in snapshot"), the drop is written to the ledger, and nothing reaches an
  operator. This is the architecture working exactly as intended, and it is why
  a weaker model is an acceptable analysis layer here: the model cannot make a
  citation true by asserting it. Expect a non-trivial drop rate and read
  `unsupported_claim_rate` as the measurement of it.
- **Wall-clock, and this one bites today.** Every `AgentSpec.runtime_budget_s`
  is 20s. At 1.6 tok/s the local backend cannot produce a useful answer inside
  20s, so `Agent.run` marks the run `budget_exceeded` and **discards its
  claims** — the model does good work and the runtime throws it away. That is
  the budget behaving exactly as designed; it means running this backend as the
  primary path requires raising `runtime_budget_s` per agent, deliberately, to
  something above `AURALIS_LOCAL_MODEL_TIMEOUT_S`. Until that is done, `local`
  is useful for evaluation and for operators who tune their own specs, and the
  deterministic path is what the demo should keep running on.
- One worker thread. Two concurrent incidents serialise. Fine for a single
  operator console, not fine for a shift room.
- **Debt, named:** ADR 0011's earned-complexity trigger was "build the
  evaluation harness at the first learned (fitted) model". This *is* that model,
  and the harness does not exist. What stands between this model and a bad
  claim today is grounding enforcement, the envelope, and the fact that it
  cannot authorize anything — not a scored gate. `eval_loss=0.159` on the
  training run's own validation split is not evidence of field quality.

## Earned-complexity trigger
Three, any one of which is the moment to spend more:

- **The evaluation harness** is now due, per ADR 0011 — before this backend is
  made the default in any deployment where a human acts on its prose. A
  held-out AP incident set, scored for grounding rate and abstention
  correctness, gating `model_version.status`.
- **Batching, GPU or a served runtime** (vLLM/llama.cpp) when more than one
  incident is assessed concurrently, or when p95 latency stops fitting inside
  the agent runtime budgets. Not before: one thread and `max_time` are enough
  for one console.
- **A second envelope dimension** (time, incident class, data mode) when the
  model is used outside flood/urban work. Geographic scope is the only
  dimension enforced today because it is the only one the envelope declares.
