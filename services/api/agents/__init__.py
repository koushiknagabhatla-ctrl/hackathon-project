"""Auralis AI decision fabric (lane C).

The model is never the source of truth and never the policy authority. It
summarises evidence other code verified and drafts plans from a catalogue other
code handed it. Forecasts are deterministic numeric Python. Everything here
runs with the LLM switched off, and that is a supported production mode, not a
degraded curiosity - `degraded=True` says which path produced an answer.

Public surface (what the routers and lane A's repo.py call):

    coordinator.assess(incident_id, principal)             -> dict
    coordinator.build_candidate_plans(incident_id, principal) -> [plan, plan]
    llm_gateway.cost_report(workflow_id=None)              -> ops metrics
    base.unsupported_claim_rate(workflow_id=None)          -> measured rate
"""

from . import base, coordinator, llm_gateway  # noqa: F401
from .base import unsupported_claim_rate  # noqa: F401
from .llm_gateway import cost_report, sanitize, screen  # noqa: F401

__all__ = [
    "base", "coordinator", "llm_gateway",
    "cost_report", "sanitize", "screen", "unsupported_claim_rate",
]
