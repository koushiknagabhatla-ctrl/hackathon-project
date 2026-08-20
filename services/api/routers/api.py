"""The /v1 surface. Coordinator-owned: lanes A-F must not edit this file.

Routers are thin. All logic lives in core/* (lanes A and B) and agents/*
(lane C). Imports are function-local so a lane still under construction cannot
take down the whole API during development.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from services.api.main import PolicyDenied, get_principal
from services.api.models import (
    ApprovalRequest,
    EventAccepted,
    EventIn,
    ExecuteRequest,
    SimulationRequest,
)

router = APIRouter(prefix="/v1")


# --------------------------------------------------------------- ingestion
@router.post("/events", response_model=EventAccepted)
def post_event(body: EventIn, principal: dict = Depends(get_principal)) -> EventAccepted:
    from services.api.core import ingest

    return ingest.ingest_event(body, principal)


# --------------------------------------------------------------- incidents
@router.get("/incidents")
def list_incidents(
    principal: dict = Depends(get_principal),
    state: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_incidents(principal["tenant_id"], state=state)


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import repo

    detail = repo.incident_detail(principal["tenant_id"], incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return detail


@router.post("/incidents/{incident_id}/assess")
def assess_incident(incident_id: str, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    """Run the specialist agents. Falls back to deterministic synthesis when
    the LLM path is unavailable; `degraded` says which happened."""
    from services.api.agents import coordinator

    return coordinator.assess(incident_id, principal)


# ------------------------------------------------------------------- plans
@router.get("/incidents/{incident_id}/plans")
def list_plans(incident_id: str, principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_plans(principal["tenant_id"], incident_id)


@router.post("/incidents/{incident_id}/plans")
def create_plans(incident_id: str, principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.agents import coordinator

    return coordinator.build_candidate_plans(incident_id, principal)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import repo

    plan = repo.plan_detail(principal["tenant_id"], plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@router.post("/plans/{plan_id}/approve")
def approve(
    plan_id: str, body: ApprovalRequest, principal: dict = Depends(get_principal)
) -> dict[str, Any]:
    from services.api.core import gateway

    return gateway.record_approval(plan_id, body, principal)


# ----------------------------------------------------------------- actions
@router.get("/actions")
def list_actions(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_actions(principal["tenant_id"])


@router.post("/actions/{action_id}/execute")
def execute_action(
    action_id: str, body: ExecuteRequest, principal: dict = Depends(get_principal)
) -> dict[str, Any]:
    """The single action path. Every gate in core/gateway.py runs here."""
    from services.api.core import gateway

    return gateway.execute(action_id, principal, body.idempotency_key)


@router.post("/actions/{action_id}/rollback")
def rollback_action(action_id: str, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import verify

    return verify.rollback(action_id, principal)


# ---------------------------------------------------------- evidence/claims
@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import repo

    ev = repo.get_evidence(principal["tenant_id"], evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    return ev


@router.get("/claims")
def list_claims(
    incident_id: str | None = Query(default=None), principal: dict = Depends(get_principal)
) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_claims(principal["tenant_id"], incident_id)


@router.get("/conflicts")
def list_conflicts(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_conflicts(principal["tenant_id"])


# -------------------------------------------------------------------- twin
@router.get("/twin/query")
def twin_query(
    asset_id: str, depth: int = Query(default=2, ge=1, le=6), principal: dict = Depends(get_principal)
) -> dict[str, Any]:
    from services.api.core import twin

    return twin.query(asset_id, depth, principal["tenant_id"])


@router.get("/twin/snapshot")
def twin_snapshot(at: str | None = None, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import twin

    return twin.snapshot(at, principal["tenant_id"])


@router.get("/twin/assets")
def twin_assets(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_assets(principal["tenant_id"])


# ------------------------------------------------------------------- audit
@router.get("/audit/verify")
def audit_verify(principal: dict = Depends(get_principal)) -> dict[str, Any]:
    """Recompute the whole hash chain. Proof, not assertion."""
    from services.api.core import audit

    return audit.verify_chain(principal["tenant_id"]).model_dump()


@router.get("/audit/{workflow_id}")
def audit_workflow(workflow_id: str, principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.audit_slice(principal["tenant_id"], workflow_id)


@router.get("/audit/{workflow_id}/export")
def audit_export(workflow_id: str, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    """The JSON the Audit screen downloads and Replay rebuilds a timeline from.
    Reconstruction must be possible from this payload ALONE."""
    from services.api.core import audit

    return audit.export_workflow(workflow_id, principal["tenant_id"])


# ------------------------------------------------------------------ policy
@router.get("/policies/decisions")
def policy_decisions(
    limit: int = Query(default=100, le=500), principal: dict = Depends(get_principal)
) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_policy_decisions(principal["tenant_id"], limit)


@router.get("/policies/bundle")
def policy_bundle(principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import policy

    return policy.active_bundle()


# ------------------------------------------------------------------- tools
@router.get("/tools")
def list_tools(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    """Manifest visibility is itself a policy decision: a principal never sees
    a tool it is not authorized for."""
    from services.api.tools import registry

    return registry.manifest_for(principal)


# -------------------------------------------------------------- simulation
@router.post("/simulations")
def run_simulation(body: SimulationRequest, principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import simulator

    return simulator.run(body, principal)


@router.get("/simulations")
def list_simulations(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_simulations()


# ------------------------------------------------------- health / metrics
@router.get("/data-health")
def data_health(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.data_health(principal["tenant_id"])


@router.get("/metrics/ops")
def ops_metrics(principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import repo

    return repo.ops_metrics(principal["tenant_id"])


# ------------------------------------------------------------------- admin
@router.post("/admin/agents/{agent_id}/revoke")
def revoke_agent(
    agent_id: str, body: dict[str, Any], principal: dict = Depends(get_principal)
) -> dict[str, Any]:
    """Kill switch. R4-gated, dual control, audited."""
    from services.api.core import gateway

    return gateway.revoke_agent(agent_id, principal, body.get("second_approver_id"), body.get("reason"))


# ------------------------------------------------------------------ public
@router.get("/public/status")
def public_status() -> dict[str, Any]:
    """Unauthenticated by design. Verified incidents only, redacted, with a
    deliberate disclosure delay. Never raw operational detail."""
    from services.api.core import repo

    return repo.public_status()


# ------------------------------------------------------------------- field
@router.get("/field/work-orders")
def list_work_orders(principal: dict = Depends(get_principal)) -> list[dict[str, Any]]:
    from services.api.core import repo

    return repo.list_work_orders(principal["tenant_id"], principal["id"])


@router.post("/field/work-orders/{wo_id}")
def update_work_order(
    wo_id: str, body: dict[str, Any], principal: dict = Depends(get_principal)
) -> dict[str, Any]:
    """Field sync is a governed event source, not a backdoor: it writes through
    the same audit path as anything else."""
    from services.api.core import repo

    return repo.update_work_order(wo_id, body, principal)


# -------------------------------------------------------------------- demo
@router.post("/demo/reset")
def demo_reset(principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import simulator

    return simulator.reset(principal)


@router.post("/demo/step")
def demo_step(body: dict[str, Any], principal: dict = Depends(get_principal)) -> dict[str, Any]:
    from services.api.core import simulator

    return simulator.step(body.get("to_offset_s"), principal)


# ------------------------------------------------------------------ stream
@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE. Deliberately chosen over WebSocket: one-way server push is all this
    needs, and it survives proxies and reconnects for free."""
    from services.api.core import repo

    async def gen():
        last_seq = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                events, last_seq = repo.poll_stream(last_seq)
                for ev in events:
                    yield f"event: {ev['kind']}\ndata: {json.dumps(ev)}\n\n"
            except Exception as exc:  # keep the stream alive on a transient error
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
