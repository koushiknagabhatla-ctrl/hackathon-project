"""Warm the local fine-tuned model so the first real request is not a 3GB surprise.

    python scripts/warm_model.py

This is the ONLY place allowed to download base weights. The serving path in
`agents/local_model.py` loads with `local_files_only=True`, so a cold cache
makes the local backend unavailable (and the deterministic path answers) rather
than stalling an incident response behind a download.

Steps, in order, because the order is the point:
  1. verify every artifact against its pinned sha256 - BEFORE any weight loads
  2. download / confirm the base model in the Hugging Face cache
  3. load base + LoRA adapter and register the model_version row
  4. run one tiny greedy generation to prove the whole path works

Exit code 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Must be set before local_model.load() runs: this script is the downloader.
os.environ["AURALIS_LOCAL_MODEL_ALLOW_DOWNLOAD"] = "true"

from services.api.agents import local_model  # noqa: E402
from services.api.core import db  # noqa: E402


def step(n: int, what: str) -> None:
    print(f"\n[{n}/4] {what}", flush=True)


def main() -> int:
    d = local_model.model_dir()
    print("=" * 72)
    print("Auralis local model warm-up")
    print(f"  adapter dir : {d}")
    print(f"  base model  : {local_model.BASE_MODEL}")
    print(f"  version     : {local_model.MODEL_VERSION}")
    print("=" * 72)

    if not d.is_dir():
        print(f"FAIL: adapter directory does not exist: {d}")
        print("      set AURALIS_LOCAL_MODEL_DIR to the model directory.")
        return 1

    step(1, "verifying artifact hashes (supply chain gate)")
    t0 = time.monotonic()
    problems = local_model.verify_artifacts(d)
    if problems:
        print("FAIL: artifact verification failed - the model will NOT load:")
        for p in problems:
            print(f"      - {p}")
        return 1
    print(f"      OK: every pinned sha256 matches ({time.monotonic() - t0:.1f}s)")

    env = local_model.envelope()
    print(f"      envelope: {env.get('geographic_scope', 'unknown')}")
    for rule in local_model.envelope_rules():
        print(f"        rule: {rule}")

    step(2, "fetching the base model into the Hugging Face cache")
    print("      this is a ~3GB download the first time; later runs are instant.")
    try:
        from huggingface_hub import snapshot_download

        path = snapshot_download(local_model.BASE_MODEL)
        print(f"      OK: {path}")
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        print(f"FAIL: could not fetch {local_model.BASE_MODEL}: "
              f"{type(exc).__name__}: {exc}")
        return 1

    step(3, "loading base + LoRA adapter on CPU")
    t0 = time.monotonic()
    try:
        tok, model = local_model.load()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    trainable = sum(p.numel() for p in model.parameters())
    print(f"      OK: loaded in {time.monotonic() - t0:.1f}s, "
          f"{trainable / 1e9:.2f}B parameters, tokenizer={type(tok).__name__}")

    db.init_db(os.environ.get("AURALIS_DB", "./auralis.db"))
    row_id = local_model.register()
    print(f"      registered model_version row: {row_id}")

    step(4, "one greedy generation (proves the serving path end to end)")
    t0 = time.monotonic()
    try:
        text, ti, to = local_model.generate(
            "You are the Auralis analysis layer. Answer with one short sentence. "
            "Cite only evidence given to you.",
            "EVIDENCE ev_1: water level at Budameru gauge is 3.4 m, observed "
            "2026-08-20T09:18:00Z, certified tier.\n"
            "Summarise the verified state in one sentence, citing ev_1.",
            new_tokens=64, budget_s=local_model.timeout_s(),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    dt = time.monotonic() - t0
    print(f"      {ti} prompt tokens -> {to} new tokens in {dt:.1f}s "
          f"({to / dt if dt else 0:.1f} tok/s on CPU)")
    print(f"      sample: {text.strip()[:400]}")

    print("\nPASS - the local backend is warm. "
          "Set AURALIS_LLM_BACKEND=local,deterministic to prefer it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
