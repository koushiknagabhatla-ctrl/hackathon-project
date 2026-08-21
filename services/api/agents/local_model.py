"""The local fine-tuned backend: Qwen2.5-1.5B-Instruct + the Auralis Andhra
Pradesh LoRA adapter, on CPU, in this process. Reached ONLY through
`agents/llm_gateway.py` - nothing else may import this module.

It is an ANALYSIS layer and nothing more. It has no tools, no network, no
policy opinion and no authority. Everything it says is prose over evidence
another part of the system already verified, and every statement it produces
still has to survive `core/claims.py`: a fact or forecast with no evidence id
is DROPPED, not softened. The whole product runs with this file deleted.

Three controls live here, in the order they run:

  1. SUPPLY CHAIN - `verify_artifacts()` recomputes sha256 for every entry in
     `artifact_hashes.json` and compares against the pinned value. A mismatch
     REFUSES to load and logs a security event. This runs BEFORE any weights
     are read, so a tampered adapter never reaches memory.
  2. ENVELOPE - `model_envelope.json` declares "Andhra Pradesh, India only".
     `check_envelope()` enforces that as DATA, against the request's
     jurisdiction, before the model is invoked. Outside it the serving layer
     ABSTAINS and downgrades to the deterministic path. It never extrapolates,
     and the breach is written to the audit ledger where the AI Trace view
     shows it, together with the five behavioural rules the model is bound to.
  3. TIME - CPU inference on 1.5B parameters is slow. Generation is greedy
     (temperature 0, for replay determinism), bounded in new tokens, and has a
     hard wall-clock timeout. On timeout the gateway degrades to the
     deterministic generator rather than hanging the request.

The model's own `chat_template.jinja` is used through the tokenizer. The prompt
format is never hand-rolled.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.api.core import audit, db

log = logging.getLogger("auralis.llm.local")

DEFAULT_MODEL_DIR = r"C:\Users\koush\OneDrive\Desktop\final_model"

# Pinned identity. This exact string is written to `agent_run.model_version`
# and to `model_version.version`, which is how AI Trace joins a claim to the
# model that produced it (core/audit.py::export looks the row up by version).
MODEL_NAME = "auralis-ap-urban-intelligence"
MODEL_VERSION = "auralis-ap-urban-1.5b-lora@checkpoint-818"
REGISTRY_ID = "mv_auralis_ap_urban_1"
BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

# CALIBRATION. Measured on the reference box (torch 2.11+cpu, no CUDA):
# 21.6s to load, then ~1.6 tokens/second of generation. 384 tokens is therefore
# about four minutes of decode, and the timeout has to be bigger than that or
# every call dies at the deadline. Both are env-overridable - a faster machine
# should raise the token ceiling and lower the timeout, and neither number
# survives contact with different hardware unchanged.
DEFAULT_MAX_NEW_TOKENS = 384
DEFAULT_TIMEOUT_S = 300.0

KIND_ENVELOPE_OK = "model.envelope_checked"
KIND_ENVELOPE_BREACH = "model.out_of_envelope"
KIND_ARTIFACT_MISMATCH = "model.artifact_hash_mismatch"

# "Andhra Pradesh, India only", as a matcher over the request's jurisdiction.
# Deliberately narrow: an unrecognised or unknown jurisdiction is OUTSIDE the
# envelope, because abstaining is the correct answer when scope is unclear.
# The name matches in any case; the bare code stays UPPERCASE, so an ordinary
# lowercase word never accidentally reads as the state code.
_AP_RE = re.compile(r"(?i:\bandhra\s*pradesh\b)|\b(?:IN-)?AP\b")


class ArtifactMismatch(RuntimeError):
    """A pinned artifact hash did not match. The model is not loaded."""


class LocalModelTimeout(TimeoutError):
    """Wall-clock budget spent. The caller degrades to the deterministic path."""


# --------------------------------------------------------------- location
def model_dir() -> Path:
    """Read the env var every call so a test can point this at a fixture."""
    return Path(os.environ.get("AURALIS_LOCAL_MODEL_DIR") or DEFAULT_MODEL_DIR)


def max_new_tokens() -> int:
    try:
        return int(os.environ.get("AURALIS_LOCAL_MODEL_MAX_NEW_TOKENS",
                                  DEFAULT_MAX_NEW_TOKENS))
    except ValueError:
        return DEFAULT_MAX_NEW_TOKENS


def timeout_s() -> float:
    try:
        return float(os.environ.get("AURALIS_LOCAL_MODEL_TIMEOUT_S",
                                    DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _may_download() -> bool:
    """Serving NEVER downloads 3GB of base weights. `scripts/warm_model.py`
    sets this; every other caller loads from the local cache or gives up."""
    return os.environ.get("AURALIS_LOCAL_MODEL_ALLOW_DOWNLOAD", "").strip().lower() in (
        "1", "true", "yes", "on")


# ------------------------------------------------------- supply chain gate
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_artifacts(directory: str | Path | None = None) -> list[str]:
    """Recompute sha256 for every entry in `artifact_hashes.json`.

    Returns a list of problems - empty means every artifact matches its pinned
    hash. The manifest keys are repo-relative (`final_model/x`); only the file
    name is used, so the directory can be moved or renamed without breaking the
    pin. `artifact_hashes.json` is not in its own manifest, by construction.
    """
    d = Path(directory) if directory else model_dir()
    manifest_path = d / "artifact_hashes.json"
    if not manifest_path.exists():
        return [f"artifact_hashes.json missing from {d}: model provenance "
                f"cannot be established, refusing to load"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"artifact_hashes.json is unreadable: {exc}"]

    problems: list[str] = []
    for key, expected in sorted(manifest.items()):
        path = d / Path(key).name
        if not path.exists():
            problems.append(f"{key}: MISSING from {d}")
            continue
        actual = _sha256(path)
        if actual != str(expected):
            problems.append(f"{key}: sha256 {actual} != pinned {expected}")
    return problems


def require_verified_artifacts(directory: str | Path | None = None) -> None:
    """Raise unless every artifact matches. Runs before any weight is read."""
    problems = verify_artifacts(directory)
    if not problems:
        return
    log.error(
        "SECURITY: %s - refusing to load %s from %s: %s",
        KIND_ARTIFACT_MISMATCH, MODEL_VERSION, directory or model_dir(),
        "; ".join(problems),
    )
    raise ArtifactMismatch(
        f"model artifact verification FAILED for {MODEL_VERSION}: "
        f"{'; '.join(problems)}"
    )


# ------------------------------------------------------------- envelope
@lru_cache(maxsize=4)
def _read_json(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def envelope() -> dict[str, Any]:
    """The declared operating envelope, as data. Empty when absent."""
    return dict(_read_json(str(model_dir() / "model_envelope.json")))


def envelope_rules() -> list[str]:
    """The behavioural rules the model is constrained to, for the trace view."""
    return [str(r) for r in envelope().get("rules", [])]


def check_envelope(variables: Mapping[str, Any]) -> tuple[bool, str]:
    """Is this request inside the model's declared geographic scope?

    The signal is the request's jurisdiction, which `agents/base.py` derives
    from the tenant - not from anything the model or a data field said. An
    unknown jurisdiction is outside the envelope: the model does not get to
    guess where it is.
    """
    scope = str(envelope().get("geographic_scope") or "Andhra Pradesh, India only")
    juris = str(variables.get("jurisdiction") or "").strip()
    if not juris or juris.lower() == "unknown":
        return False, (
            f"jurisdiction is unknown and the model envelope is {scope!r}; "
            f"abstaining rather than assuming the request is in scope"
        )
    if _AP_RE.search(juris):
        return True, ""
    return False, (
        f"jurisdiction {juris!r} is outside the model envelope ({scope}); "
        f"the model abstains and the deterministic path answers instead - "
        f"nothing was extrapolated to a region this model was not trained on"
    )


# --------------------------------------------------------------- registry
def register() -> str | None:
    """Insert / refresh the `model_version` row for this adapter.

    AI Trace joins `agent_run.model_version` to this row, so the envelope, the
    base model, the adapter checkpoint and the pinned artifact hash are all
    visible next to any claim the model produced. No-ops when the model
    directory is absent - the system must survive this model not existing.
    """
    d = model_dir()
    env = envelope()
    if not env:
        return None
    manifest_path = d / "artifact_hashes.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    selected = _read_json(str(d / "selected_model.json"))

    row = dict(env)
    row.update({
        "kind": "peft-lora-adapter",
        "base_model": env.get("base_model") or BASE_MODEL,
        "adapter_checkpoint": selected.get("best_checkpoint", "checkpoint-818"),
        "eval_loss": selected.get("best_metric_value"),
        "artifact_sha256": manifest.get("final_model/adapter_model.safetensors", ""),
        "artifact_manifest_entries": len(manifest),
        "runtime": "cpu/torch, greedy decoding (temperature 0)",
        "authority": "analysis only - not a source of truth, not a policy "
                     "authority, cannot authorize or execute an action",
    })
    try:
        db.run(
            "INSERT OR IGNORE INTO model_version(id,name,kind,version,envelope,"
            "registered_at,status) VALUES(?,?,?,?,?,?,?)",
            REGISTRY_ID, MODEL_NAME, "llm", MODEL_VERSION, db.jdump(row),
            db.now_iso(), "active",
        )
        db.run("UPDATE model_version SET envelope=?, version=?, status='active' "
               "WHERE id=?", db.jdump(row), MODEL_VERSION, REGISTRY_ID)
    except sqlite3.Error as exc:      # registry is telemetry, not the ledger
        log.warning("model_version registration failed: %s", exc)
        return None
    return REGISTRY_ID


def record_envelope_decision(
    *, tenant_id: str, workflow_id: str, incident_id: str | None,
    agent_id: str, in_envelope: bool, reason: str,
) -> None:
    """Write the envelope decision where an operator can see it.

    Both outcomes are recorded, not just the breach: the AI Trace view shows
    what the model is constrained to (the five rules) on every call, and shows
    the abstention with its reason when the request fell outside.
    """
    register()
    env = envelope()
    payload = {
        "model_version": MODEL_VERSION,
        "model_name": MODEL_NAME,
        "base_model": env.get("base_model") or BASE_MODEL,
        "geographic_scope": env.get("geographic_scope", ""),
        "rules": envelope_rules(),
        "limitations": [str(x) for x in env.get("limitations", [])],
        "in_envelope": in_envelope,
        "reason": reason,
        "agent_id": agent_id,
        "action_taken": ("model invoked" if in_envelope else
                         "ABSTAINED - downgraded to the deterministic path, "
                         "nothing extrapolated"),
    }
    if not in_envelope:
        log.warning("out of envelope for %s: %s", agent_id, reason)
    if not tenant_id:
        return
    try:
        audit.append(
            tenant_id, workflow_id, MODEL_NAME, "model",
            KIND_ENVELOPE_OK if in_envelope else KIND_ENVELOPE_BREACH,
            incident_id, payload,
        )
    except (sqlite3.Error, ValueError) as exc:
        # telemetry: a logging failure must not take down an incident response.
        log.warning("envelope telemetry not recorded: %s", exc)


# --------------------------------------------------------------- loading
_LOADED: tuple[Any, Any] | None = None
_LOAD_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None


def available() -> tuple[bool, str]:
    """(ready, why-not). Cheap: no weights are touched and nothing downloads."""
    d = model_dir()
    if not d.is_dir():
        return False, f"local model directory not found: {d}"
    if not (d / "adapter_config.json").exists():
        return False, f"no LoRA adapter in {d}"
    # find_spec, not import: probing must not pay the multi-second cost of
    # importing transformers on a request that is about to go elsewhere.
    for package in ("transformers", "peft"):
        if importlib.util.find_spec(package) is None:
            return False, (f"local backend not installed: no module named "
                           f"{package!r} (pip install -r services/api/requirements.txt)")
    return True, ""


def load() -> tuple[Any, Any]:
    """(tokenizer, model). Lazy: the first call pays, import time never does.

    Base weights come from the local Hugging Face cache. If they are not there
    this raises rather than starting a 3GB download inside a request - run
    `python scripts/warm_model.py` once instead.
    """
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    with _LOAD_LOCK:
        if _LOADED is not None:
            return _LOADED
        d = model_dir()
        require_verified_artifacts(d)      # supply chain gate, before weights

        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        base_name = str(envelope().get("base_model") or BASE_MODEL)
        log.info("loading %s + adapter %s on cpu", base_name, MODEL_VERSION)
        tok = AutoTokenizer.from_pretrained(str(d))
        if not getattr(tok, "chat_template", None):
            tok.chat_template = (d / "chat_template.jinja").read_text(encoding="utf-8")
        try:
            base = AutoModelForCausalLM.from_pretrained(
                base_name, dtype=torch.float32,
                local_files_only=not _may_download(),
            )
        except OSError as exc:
            # The serving path never downloads. Say so in the words an operator
            # can act on - this string ends up in `agent_run.output.reason`.
            raise RuntimeError(
                f"base model {base_name} is not in the local Hugging Face cache, "
                f"and serving never downloads it. Run `python scripts/warm_model.py` "
                f"once (~3GB). Underlying error: {exc}"
            ) from exc
        model = PeftModel.from_pretrained(base, str(d))
        model.eval()
        _LOADED = (tok, model)
        log.info("local model ready: %s", MODEL_VERSION)
        return _LOADED


def unload() -> None:
    """Drop the loaded weights. Used by tests and by a config change."""
    global _LOADED
    _LOADED = None


# ------------------------------------------------------------- generation
def generate(system: str, user: str, *, new_tokens: int, budget_s: float
             ) -> tuple[str, int, int]:
    """(text, tokens_in, tokens_out). Greedy - temperature 0, no sampling.

    Deterministic decoding is what makes an audit replay of this backend
    reproduce the same words. `max_time` stops the loop from inside, so an
    abandoned call releases the CPU instead of burning a core to the end.
    """
    import torch

    tok, model = load()
    prompt = tok.apply_chat_template(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        tokenize=False, add_generation_prompt=True,
    )
    inputs = tok(prompt, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=new_tokens,
            do_sample=False, temperature=None, top_p=None, top_k=None,
            max_time=budget_s,
            pad_token_id=tok.pad_token_id or tok.eos_token_id,
        )
    prompt_len = int(inputs["input_ids"].shape[1])
    fresh = out[0][prompt_len:]
    return tok.decode(fresh, skip_special_tokens=True), prompt_len, int(fresh.shape[0])


def _extract_json(text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    """First JSON object in the reply, schema-required keys present.

    A 1.5B model has no structured-output mode, so this is where a malformed
    answer becomes an exception - and an exception is how the gateway degrades
    to the deterministic generator. Nothing is patched up or guessed at.
    """
    start = text.find("{")
    if start < 0:
        raise ValueError(
            f"local model returned no JSON object: {text.strip()[:200]!r}")
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        # Carry the offending text into `agent_run.output.reason`. A malformed
        # answer from a 1.5B model is a normal event, and an operator watching
        # the degradation rate needs to see WHAT it said, not just that it
        # failed. Nothing is repaired here - a broken answer is not an answer.
        around = text[start:][max(0, exc.pos - 80):exc.pos + 80]
        raise ValueError(f"{exc}; around the failure: {around!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("local model returned JSON that is not an object")
    missing = [k for k in schema.get("required", []) if k not in parsed]
    if missing:
        raise ValueError(f"local model output missing required keys: {missing}")
    return parsed


def _blocking_complete(system: str, user: str, schema: Mapping[str, Any],
                       new_tokens: int, budget_s: float
                       ) -> tuple[dict[str, Any], str, int, int]:
    text, ti, to = generate(system, user, new_tokens=new_tokens, budget_s=budget_s)
    return _extract_json(text, schema), text, ti, to


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auralis-llm")
    return _EXECUTOR


def complete_json(
    system: str, user: str, schema: Mapping[str, Any], *,
    new_tokens: int | None = None, budget_s: float | None = None,
) -> tuple[dict[str, Any], str, int, int]:
    """(parsed, raw_text, tokens_in, tokens_out) or raise. Never blocks forever.

    ponytail: one worker thread, so two concurrent requests serialise and an
    abandoned generation still holds the lane until `max_time` ends it. Ceiling
    is throughput, not correctness - a caller that timed out has already been
    answered by the deterministic path. Upgrade path: a process pool, when this
    stops being a single-operator console.
    """
    limit = float(budget_s if budget_s is not None else timeout_s())
    fut = _executor().submit(
        _blocking_complete, system, user, schema,
        int(new_tokens if new_tokens is not None else max_new_tokens()), limit,
    )
    try:
        return fut.result(timeout=limit)
    except FutureTimeout:
        fut.cancel()
        raise LocalModelTimeout(
            f"local model exceeded its {limit:g}s wall-clock budget; "
            f"degrading to the deterministic path"
        ) from None
