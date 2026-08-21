"""The ONLY path to a language model in this system. Nothing else may call a
provider - if you are about to import httpx elsewhere to reach an LLM, stop.

The model is never the source of truth and never the policy authority. It does
language-heavy work only: summarising evidence that other code verified, and
drafting plan candidates from a catalogue other code handed it. Forecasts are
deterministic numeric code (`core/forecast.py`). The whole product runs with the
model switched off, and that is the DEFAULT path, not a fallback of last resort:
with no `ANTHROPIC_API_KEY` every agent still produces a full, grounded,
useful answer from its deterministic generator and reports `degraded=True`.

What this module owns:
  * template loading + versioning          (prompts/*.md)
  * PII egress redaction BEFORE any bytes leave the process
  * context firewall: sanitize() + screen() over untrusted DATA fields
  * response cache (repeated analyses cost nothing)
  * per-workflow token and cost budget, persisted for cost-per-incident
  * one retry, then deterministic fallback - never an exception at the caller
  * full request/response logging into `agent_run`
  * backend routing, and reporting WHICH backend actually answered

BACKENDS, in the order `AURALIS_LLM_BACKEND` names them (default
`local,anthropic,deterministic`):

  local          the fine-tuned Andhra Pradesh adapter in `local_model.py`.
                 No API key, no per-token cost, no data egress. Refuses to run
                 outside its declared geographic envelope.
  anthropic      the hosted path, used when ANTHROPIC_API_KEY is set.
  deterministic  the agent's own template generator. Always available, always
                 last, and the one the demo runs on.

Each backend is tried in turn; the first that answers wins and the rest are
skipped. Falling through is never silent: `GatewayResult.backend`,
`model_version` and `reason` all say what happened, the same three values land
in `agent_run`, and the API response carries them up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

import httpx

from services.api.core import db

from . import local_model

log = logging.getLogger("auralis.llm")

# ----------------------------------------------------------------- settings
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL_ID = os.environ.get("AURALIS_LLM_MODEL", "claude-sonnet-5")
DETERMINISTIC_VERSION = "deterministic-template-1.0.0"
DEFAULT_BACKENDS = ("local", "anthropic", "deterministic")


def backends() -> tuple[str, ...]:
    """Routing order. `deterministic` is always the terminal element, whatever
    the operator configured - there is no configuration in which a request can
    end with no answer at all."""
    raw = os.environ.get("AURALIS_LLM_BACKEND", "").strip()
    order = tuple(p.strip().lower() for p in raw.split(",") if p.strip()) or DEFAULT_BACKENDS
    return order if order[-1] == "deterministic" else (*order, "deterministic")

# claude-sonnet-5 list price, USD per million tokens. The $2/$10 introductory
# rate runs to 2026-08-31; budgeting at list price never under-reserves.
PRICE_IN_PER_MTOK = 3.00
PRICE_OUT_PER_MTOK = 15.00

DEFAULT_MAX_TOKENS = 1200
REQUEST_TIMEOUT_S = 30.0


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def token_budget() -> int:
    return _int_env("AURALIS_WORKFLOW_TOKEN_BUDGET", 40000)


def cost_budget_usd() -> float:
    try:
        return float(os.environ.get("AURALIS_WORKFLOW_COST_BUDGET_USD", 0.50))
    except ValueError:
        return 0.50


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# The twelve PRD context requirements. Every template carries all twelve, and
# tests/test_lane_c.py fails the build if one goes missing.
CONTEXT_REQUIREMENTS = (
    "1. OBJECTIVE (BOUNDED)",
    "2. TASK ID AND JURISDICTION",
    "3. EVIDENCE SNAPSHOT (SOURCE + TIME METADATA)",
    "4. EXPLICIT UNKNOWNS",
    "5. ALLOWED TOOLS AND SCHEMAS",
    "6. ACTION-RISK POLICY REFERENCE",
    "7. OUTPUT JSON SCHEMA",
    "8. STOP CONDITIONS",
    "9. UNTRUSTED DATA",
    "10. NEVER CLAIM A TOOL RAN WITHOUT A TOOL RESULT",
    "11. NEVER INVENT CURRENT STATE",
    "12. REQUEST APPROVAL, NEVER BYPASS IT",
)

DATA_MARKER = "\n=== DATA (UNTRUSTED) ===\n"


# ------------------------------------------------------------------ result
@dataclass(frozen=True)
class GatewayResult:
    text: str
    parsed: dict[str, Any]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model_version: str
    prompt_version: str
    degraded: bool
    cache_hit: bool
    reason: str = ""          # why the deterministic path was taken, if it was
    injection_flags: tuple[str, ...] = ()
    pii_redactions: int = 0
    backend: str = "deterministic"   # which one ACTUALLY answered
    in_envelope: bool = True         # was the request inside the model envelope
    envelope_reason: str = ""        # and if not, why not


# ------------------------------------------------------------- templates
@lru_cache(maxsize=32)
def load_template(name: str) -> tuple[str, str]:
    """Return (version, body) for prompts/<name>.md.

    A system prompt is BEHAVIOUR GUIDANCE, never a security boundary. Every
    rule in these templates is a way of asking for good behaviour from a
    statistical system that can be talked out of it. Nothing in the product
    depends on the model obeying them: grounding is enforced in
    `core/claims.py`, the tool catalogue is filtered in `agents/planning.py`
    after the model has spoken, risk tiers come from `core/risk.py`, policy
    from `core/policy.py`, and every external effect from `core/gateway.py`.
    If a template were replaced wholesale by an attacker, the system would
    produce worse prose and exactly the same enforcement decisions.
    """
    path = PROMPT_DIR / f"{name}.md"
    body = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", body, re.S)
    if not m:
        raise ValueError(f"prompt template {name} has no front matter")
    v = re.search(r"^version:\s*(\S+)\s*$", m.group(1), re.M)
    if not v:
        raise ValueError(f"prompt template {name} has no `version:` front-matter line")
    return v.group(1), body[m.end():]


def render(name: str, variables: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return (version, system_part, user_part). The user part holds the DATA."""
    version, body = load_template(name)
    tpl = Template(body)
    values = {k: _as_text(v) for k, v in variables.items()}
    for ident in tpl.get_identifiers():
        values.setdefault(ident, "(not provided)")
    rendered = tpl.safe_substitute(values)
    system, sep, user = rendered.partition(DATA_MARKER)
    return version, system, (user if sep else "Produce the JSON object now.")


def _as_text(v: Any) -> str:
    if isinstance(v, str):
        return v
    return json.dumps(v, indent=2, sort_keys=True, default=str)


# ------------------------------------------------- PII egress redaction
# Best effort and deliberately over-eager: a redacted coordinate costs nothing,
# a leaked phone number is a reportable incident. Runs on OUTBOUND variables
# before any byte leaves the process, so it also covers the cache key.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")),
    ("national_id", re.compile(r"(?<![\w.])\d{3}-\d{2}-\d{4}(?![\w.])")),
    ("phone", re.compile(r"(?<![\w.])\+\d[\d ().-]{7,17}\d(?![\w.])")),
    ("phone", re.compile(r"(?<![\w.])\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w.])")),
    ("national_id", re.compile(r"(?<![\w.])\d{9,11}(?![\w.])")),
)


def redact_text(text: str) -> tuple[str, int]:
    n = 0
    for label, pattern in _PII_PATTERNS:
        text, hits = pattern.subn(f"[redacted:{label}]", text)
        n += hits
    return text, n


def redact(obj: Any) -> tuple[Any, int]:
    """Recursively redact strings anywhere in the outbound variable tree."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, Mapping):
        out, n = {}, 0
        for k, v in obj.items():
            out[k], hits = redact(v)
            n += hits
        return out, n
    if isinstance(obj, (list, tuple)):
        items, n = [], 0
        for v in obj:
            item, hits = redact(v)
            items.append(item)
            n += hits
        return items, n
    return obj, 0


# ------------------------------------------------------- context firewall
# DEFENCE IN DEPTH ONLY. This neutralises the obvious shapes of an instruction
# hidden in a data field. It is a filter, not a guarantee: an attacker who
# phrases an injection outside these patterns gets through, and that is an
# accepted outcome, because NO POLICY ENFORCEMENT DEPENDS ON THIS FUNCTION.
# A model fully persuaded by an injection still cannot emit an ungrounded claim
# (core/claims.py rejects it), still cannot name a tool outside the catalogue
# (agents/planning.py drops it after parsing), still cannot lower a risk tier
# (core/risk.py), still cannot clear a policy rule (core/policy.py) and still
# cannot reach the outside world (core/gateway.py). Treat every improvement
# here as a way to reduce noise, never as a control you can rely on.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("override_instructions", re.compile(
        r"(?i)\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
        r"\b(previous|prior|earlier|above|all|your)\b[^.\n]{0,30}"
        r"\b(instruction|prompt|rule|direction|guideline)s?\b")),
    ("role_reassignment", re.compile(
        r"(?i)\byou\s+are\s+(now|actually|really)\b|"
        r"\b(act|behave)\s+as\s+(if\s+you\s+are\s+)?(an?\s+)?"
        r"(admin|administrator|operator|approver|system)\b")),
    ("role_header", re.compile(r"(?im)^\s{0,8}(system|assistant|developer|human)\s*:")),
    ("fenced_role", re.compile(
        r"(?i)```\s*(system|assistant|developer)\b|</?\s*(system|assistant)\s*>|"
        r"\[/?INST\]|<\|[^|>\n]{0,24}\|>")),
    ("new_instructions", re.compile(
        r"(?i)\bnew\s+(instruction|directive|system\s+prompt|task)s?\s*:")),
    ("policy_bypass", re.compile(
        r"(?i)\b(bypass|skip|suppress|disable|without|no\s+need\s+for)\b[^.\n]{0,40}"
        r"\b(approval|approvals|policy|policies|review|guardrail|safety|human)\b")),
    ("autonomous_effect", re.compile(
        r"(?i)\b(publish|broadcast|issue|send|dispatch|execute|trigger|activate)\b"
        r"[^.\n]{0,40}\b(public\s+alert|alert|evacuation|siren|warning|notification)\b")),
)


def screen(text: str) -> tuple[str, ...]:
    """Report which injection shapes appear in `text`. Does not modify it."""
    return tuple(sorted({
        flag for flag, pattern in _INJECTION_PATTERNS if pattern.search(text)
    }))


def sanitize(text: str) -> str:
    """Neutralise instruction-like patterns in an untrusted DATA field.

    Replaces each match with a visible `[neutralised:<flag>]` marker, so the
    operator reading the trace can see exactly what was defanged and where.
    See the block comment above: defence in depth ONLY.
    """
    for flag, pattern in _INJECTION_PATTERNS:
        text = pattern.sub(f"[neutralised:{flag}]", text)
    return text


def firewall(obj: Any) -> tuple[Any, tuple[str, ...]]:
    """sanitize() every string in the tree, collecting the flags that fired."""
    if isinstance(obj, str):
        return sanitize(obj), screen(obj)
    if isinstance(obj, Mapping):
        out, flags = {}, set()
        for k, v in obj.items():
            out[k], f = firewall(v)
            flags.update(f)
        return out, tuple(sorted(flags))
    if isinstance(obj, (list, tuple)):
        items, flags = [], set()
        for v in obj:
            item, f = firewall(v)
            items.append(item)
            flags.update(f)
        return items, tuple(sorted(flags))
    return obj, ()


# ------------------------------------------------------------------ cache
# ponytail: in-process dict. Ceiling: cleared on restart and not shared between
# workers. Upgrade path: a `llm_cache` table keyed on the same sha256 if warm
# cache has to survive a restart - the key function below is already stable.
_CACHE: dict[str, GatewayResult] = {}


def cache_key(template_name: str, prompt_version: str,
              variables: Any, schema: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"t": template_name, "v": prompt_version, "m": MODEL_ID,
         "b": list(backends()), "vars": variables, "schema": schema},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reset_cache() -> None:
    _CACHE.clear()


# ----------------------------------------------------------------- budget
def spend(workflow_id: str) -> tuple[int, float]:
    """(tokens, usd) already attributed to this workflow. Persisted, so a
    restart cannot reset a budget and a report can price any past incident."""
    row = db.q1(
        "SELECT COALESCE(SUM(tokens_in+tokens_out),0) AS t, "
        "COALESCE(SUM(cost_usd),0) AS c FROM agent_run WHERE workflow_id=?",
        workflow_id,
    )
    return (int(row["t"]), float(row["c"])) if row else (0, 0.0)


def price(tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in / 1e6 * PRICE_IN_PER_MTOK + tokens_out / 1e6 * PRICE_OUT_PER_MTOK, 6
    )


def cost_report(workflow_id: str | None = None) -> dict[str, Any]:
    """Feeds `/v1/metrics/ops`: llm cost per incident, and whether we degraded."""
    where, args = ("WHERE workflow_id=?", (workflow_id,)) if workflow_id else ("", ())
    row = db.q1(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(tokens_in),0) AS ti, "
        "COALESCE(SUM(tokens_out),0) AS to_, COALESCE(SUM(cost_usd),0) AS c, "
        "COALESCE(SUM(degraded),0) AS d, COUNT(DISTINCT incident_id) AS incidents "
        f"FROM agent_run {where}", *args,
    )
    if row is None:
        return {"llm_calls": 0, "llm_tokens": 0, "llm_cost_usd": 0.0,
                "cost_per_incident_usd": 0.0, "degraded": False,
                "model_versions": [], "backends": []}
    incidents = max(1, int(row["incidents"]))
    used = db.q(f"SELECT DISTINCT model_version FROM agent_run {where}", *args)
    versions = sorted({str(r["model_version"]) for r in used})
    return {
        "llm_calls": int(row["calls"]),
        "llm_tokens": int(row["ti"]) + int(row["to_"]),
        "llm_cost_usd": round(float(row["c"]), 6),
        "cost_per_incident_usd": round(float(row["c"]) / incidents, 6),
        "degraded": bool(row["d"]),
        # WHICH model actually answered. Never inferred from configuration -
        # read back out of the rows the calls themselves wrote.
        "model_versions": versions,
        "backends": sorted({_backend_of(v) for v in versions}),
    }


def _backend_of(model_version: str) -> str:
    if model_version == DETERMINISTIC_VERSION:
        return "deterministic"
    if model_version == local_model.MODEL_VERSION:
        return "local"
    if model_version in ("", "n/a"):
        return "none"
    return "anthropic"


# ------------------------------------------------------------------- call
def complete(
    workflow_id: str,
    agent_id: str,
    template_name: str,
    variables: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    fallback: Callable[[Mapping[str, Any]], dict[str, Any]],
    tenant_id: str = "",
    incident_id: str | None = None,
    snapshot_id: str = "",
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> GatewayResult:
    """Complete `template_name` and return schema-shaped JSON. Never raises.

    `fallback` is the agent's own deterministic generator. It is called whenever
    the model path is unavailable, refused or broken - no key, budget spent,
    HTTP error, bad JSON, schema mismatch. It is not a placeholder: it is what
    the demo runs on, and its output is the same shape as the model's.
    """
    prompt_version, _ = load_template(template_name)

    safe_vars, pii_hits = redact(variables)
    safe_vars, flags = firewall(safe_vars)

    key = cache_key(template_name, prompt_version, safe_vars, schema)
    if key in _CACHE:
        hit = replace(_CACHE[key], cache_hit=True, tokens_in=0, tokens_out=0,
                      cost_usd=0.0, reason="cache_hit")
        _log_run(tenant_id, workflow_id, agent_id, incident_id, template_name,
                 prompt_version, hit.model_version, snapshot_id, hit,
                 {"cached": True}, {"cached": True})
        return hit

    tokens_used, usd_used = spend(workflow_id)
    reason = ""
    if tokens_used >= token_budget() or usd_used >= cost_budget_usd():
        reason = (f"budget_exceeded: workflow has spent {tokens_used} tokens / "
                  f"${usd_used:.4f} (limits {token_budget()} / "
                  f"${cost_budget_usd():.2f}) - refusing to call the model")

    request: dict[str, Any] = {}
    response: dict[str, Any] = {}
    in_envelope, envelope_reason = True, ""
    if not reason:
        version, system, user = render(template_name, safe_vars)
        skipped: list[str] = []
        for name in backends():
            if name == "deterministic":
                break
            try:
                if name == "local":
                    ok, why = local_model.available()
                    if not ok:
                        skipped.append(f"local: {why}")
                        continue
                    in_envelope, envelope_reason = local_model.check_envelope(safe_vars)
                    local_model.record_envelope_decision(
                        tenant_id=tenant_id, workflow_id=workflow_id,
                        incident_id=incident_id, agent_id=agent_id,
                        in_envelope=in_envelope, reason=envelope_reason,
                    )
                    if not in_envelope:
                        # ABSTAIN. Outside the envelope the model does not get
                        # to guess - the deterministic path answers instead.
                        skipped.append(f"local: out_of_envelope: {envelope_reason}")
                        continue
                    result, request, response = _call_local(
                        system, user, schema, version, flags, pii_hits)
                elif name == "anthropic":
                    if not os.environ.get("ANTHROPIC_API_KEY"):
                        skipped.append(
                            "no_api_key: anthropic backend skipped "
                            "(this is a supported mode)")
                        continue
                    result, request, response = _call_anthropic(
                        system, user, schema, max_tokens, version, flags, pii_hits)
                else:
                    skipped.append(f"{name}: unknown backend name")
                    continue
            except Exception as exc:  # noqa: BLE001 - degrading is the contract
                skipped.append(f"{name}: {type(exc).__name__}: {exc}")
                log.warning("llm backend %s failed for %s/%s: %s",
                            name, agent_id, template_name, exc)
                continue
            _CACHE[key] = result
            _log_run(tenant_id, workflow_id, agent_id, incident_id, template_name,
                     prompt_version, result.model_version, snapshot_id, result,
                     request, response)
            return result
        reason = "; ".join(skipped) or (
            "backend order is deterministic-only (this is a supported mode)")

    result = GatewayResult(
        text="", parsed=dict(fallback(safe_vars)), tokens_in=0, tokens_out=0,
        cost_usd=0.0, model_version=DETERMINISTIC_VERSION,
        prompt_version=prompt_version, degraded=True, cache_hit=False,
        reason=reason, injection_flags=flags, pii_redactions=pii_hits,
        backend="deterministic", in_envelope=in_envelope,
        envelope_reason=envelope_reason,
    )
    _CACHE[key] = result
    _log_run(tenant_id, workflow_id, agent_id, incident_id, template_name,
             prompt_version, DETERMINISTIC_VERSION, snapshot_id, result,
             request, response)
    return result


def _call_anthropic(
    system: str, user: str, schema: Mapping[str, Any], max_tokens: int,
    version: str, flags: tuple[str, ...], pii_hits: int,
) -> tuple[GatewayResult, dict[str, Any], dict[str, Any]]:
    request = _build_request(system, user, schema, max_tokens)
    response = _post(request)
    parsed, text, ti, to = _parse(response, schema)
    return GatewayResult(
        text=text, parsed=parsed, tokens_in=ti, tokens_out=to,
        cost_usd=price(ti, to), model_version=MODEL_ID, prompt_version=version,
        degraded=False, cache_hit=False, injection_flags=flags,
        pii_redactions=pii_hits, backend="anthropic",
    ), request, response


def _call_local(
    system: str, user: str, schema: Mapping[str, Any], version: str,
    flags: tuple[str, ...], pii_hits: int,
) -> tuple[GatewayResult, dict[str, Any], dict[str, Any]]:
    """The fine-tuned adapter, in-process, on CPU.

    Tokens are counted and attributed exactly as on the hosted path; the cost
    is genuinely zero, and that zero is a measured fact rather than a missing
    number. Nothing leaves the process, so the PII redaction above is not the
    only thing standing between municipal data and a third party - there is no
    third party.
    """
    parsed, text, ti, to = local_model.complete_json(system, user, schema)
    request = {
        "backend": "local", "model": local_model.MODEL_VERSION,
        "base_model": local_model.BASE_MODEL, "temperature": 0,
        "max_new_tokens": local_model.max_new_tokens(),
        "timeout_s": local_model.timeout_s(),
        "envelope": local_model.envelope(),
        "system": system, "messages": [{"role": "user", "content": user}],
    }
    response = {"text": text, "stop_reason": "end_turn",
                "usage": {"input_tokens": ti, "output_tokens": to}}
    return GatewayResult(
        text=text, parsed=parsed, tokens_in=ti, tokens_out=to, cost_usd=0.0,
        model_version=local_model.MODEL_VERSION, prompt_version=version,
        degraded=False, cache_hit=False, injection_flags=flags,
        pii_redactions=pii_hits, backend="local", in_envelope=True,
    ), request, response


def _build_request(system: str, user: str, schema: Mapping[str, Any],
                   max_tokens: int) -> dict[str, Any]:
    """The Anthropic Messages API body.

    NOTE ON DETERMINISM: `claude-sonnet-5` REJECTS `temperature` (HTTP 400) -
    sampling parameters were removed on the 4.6+ family. Replay determinism on
    the model path therefore comes from the response cache keyed on
    (template, prompt_version, model, canonical variables, schema), plus a
    pinned prompt version and structured output. The deterministic path is
    exactly reproducible by construction. `thinking` is disabled to keep the
    output bounded and the cost attributable.
    """
    return {
        "model": MODEL_ID,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "output_config": {"format": {"type": "json_schema", "schema": dict(schema)}},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


def _post(body: dict[str, Any]) -> dict[str, Any]:
    """One retry on 429/5xx, then give up so the caller can degrade."""
    headers = {
        "content-type": "application/json",
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": API_VERSION,
    }
    last: Exception | None = None
    for attempt in (0, 1):
        r = httpx.post(API_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT_S)
        if r.status_code == 429 or r.status_code >= 500:
            last = httpx.HTTPStatusError(
                f"retryable {r.status_code}", request=r.request, response=r
            )
            if attempt == 0:
                time.sleep(float(r.headers.get("retry-after", 1)))
                continue
            raise last
        r.raise_for_status()
        return r.json()
    raise last or RuntimeError("unreachable")


def _parse(response: Mapping[str, Any],
           schema: Mapping[str, Any]) -> tuple[dict[str, Any], str, int, int]:
    if response.get("stop_reason") == "refusal":
        raise ValueError("model refused the request")
    text = next(b["text"] for b in response["content"] if b.get("type") == "text")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model returned JSON that is not an object")
    missing = [k for k in schema.get("required", []) if k not in parsed]
    if missing:
        raise ValueError(f"model output missing required keys: {missing}")
    usage = response.get("usage", {})
    return parsed, text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


# --------------------------------------------------------------- logging
def _log_run(
    tenant_id: str, workflow_id: str, agent_id: str, incident_id: str | None,
    template_name: str, prompt_version: str, model_version: str, snapshot_id: str,
    result: GatewayResult, request: Mapping[str, Any], response: Mapping[str, Any],
) -> None:
    """One `agent_run` row per LLM call: the full request and response, the
    prompt and model version, the snapshot it ran against, and the cost.

    Cost attribution: only these rows carry a non-zero `cost_usd`, so
    `SUM(cost_usd) WHERE workflow_id=?` is exactly the LLM cost of one incident
    with no double counting against the agents' own run rows.

    ponytail: telemetry, so a write failure here is logged and swallowed rather
    than taking down an incident response. The hash-chained ledger in
    `core/audit.py` is the record that must never be lossy, and that one raises.
    """
    status = ("llm_cached" if result.cache_hit
              else "llm_degraded" if result.degraded else "llm_ok")
    output = {
        "status": status,
        "reason": result.reason,
        "backend": result.backend,
        "model_version": result.model_version,
        "in_envelope": result.in_envelope,
        "envelope_reason": result.envelope_reason,
        "injection_flags": list(result.injection_flags),
        "pii_redactions": result.pii_redactions,
        "request": dict(request),
        "response": dict(response),
        "parsed": result.parsed,
    }
    try:
        at = db.now_iso()
        db.run(
            "INSERT INTO agent_run(id,tenant_id,workflow_id,agent_id,incident_id,"
            "prompt_template,prompt_version,model_version,evidence_snapshot_id,"
            "started_at,ended_at,status,tokens_in,tokens_out,cost_usd,degraded,"
            "output,claim_ids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            db.new_id("ar"), tenant_id, workflow_id, agent_id, incident_id,
            template_name, prompt_version, model_version, snapshot_id, at, at,
            status, result.tokens_in, result.tokens_out, result.cost_usd,
            int(result.degraded), db.jdump(output), "[]",
        )
    except sqlite3.Error as exc:
        log.error("agent_run logging failed for %s/%s: %s", agent_id, template_name, exc)
