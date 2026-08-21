"""Suite-wide hermeticity.

The local fine-tuned backend (`agents/local_model.py`) is real: given a warmed
Hugging Face cache it will load 1.5B parameters and run CPU inference. A test
run must not depend on whether the operator happened to run
`scripts/warm_model.py`, and must never download weights or reach the network.

So the whole suite pins the routing order to the two backends that are
mockable, and `tests/test_local_model.py` opts back in per test with
`monkeypatch.setenv`, against fixtures and fakes only.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def pin_llm_backend() -> None:
    os.environ["AURALIS_LLM_BACKEND"] = "anthropic,deterministic"
