"""Auralis API. Coordinator-owned: lanes A-F must not edit this file.

Run from the repo root:
    python -m uvicorn services.api.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import traceback
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = os.environ.get("AURALIS_DB", str(REPO_ROOT / "auralis.db"))


class PolicyDenied(Exception):
    """Raised by the tool gateway. Rendered as 403 with the exact rule id."""

    def __init__(self, rule_id: str, reason: str, detail: Any = None):
        self.rule_id = rule_id
        self.reason = reason
        self.detail = detail
        super().__init__(f"{rule_id}: {reason}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.api.core import db

    db.init_db(DB_PATH)
    # Seeding is idempotent, so a cold start always has a demo-ready city.
    try:
        from services.api.core import seed

        seed.ensure_seeded()
    except Exception:  # pragma: no cover - seeding is best-effort at boot
        traceback.print_exc()
    yield


app = FastAPI(
    title="Auralis Autonomous City API",
    version="3.0.0",
    description=(
        "Evidence-grounded, policy-bounded, auditable urban intelligence. "
        "The LLM is never the source of truth; policy lives outside the model; "
        "the tool gateway is the only path from plan to effect."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-Id"],
)


@app.middleware("http")
async def correlation_id(request: Request, call_next: Callable):
    cid = request.headers.get("X-Correlation-Id") or f"cor_{uuid.uuid4().hex[:12]}"
    request.state.correlation_id = cid
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = cid
    return response


def _error(status: int, code: str, message: str, detail: Any, cid: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "detail": detail,
                "correlation_id": cid,
            }
        },
        headers={"X-Correlation-Id": cid},
    )


@app.exception_handler(PolicyDenied)
async def _policy_denied(request: Request, exc: PolicyDenied):
    # A denial is not a server error. It is the safety architecture working,
    # and the UI renders the rule id and reason verbatim.
    cid = getattr(request.state, "correlation_id", "-")
    return _error(403, "policy_denied", exc.reason, {"rule_id": exc.rule_id, "detail": exc.detail}, cid)


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError):
    cid = getattr(request.state, "correlation_id", "-")
    return _error(422, "invalid_request", str(exc), None, cid)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    cid = getattr(request.state, "correlation_id", "-")
    return _error(exc.status_code, "http_error", str(exc.detail), None, cid)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    cid = getattr(request.state, "correlation_id", "-")
    traceback.print_exc()
    return _error(500, "internal_error", "unexpected server error", str(exc), cid)


# ------------------------------------------------------------ principal auth
def get_principal(x_auralis_principal: str | None = Header(default=None)) -> dict[str, Any]:
    """Resolve the calling identity. Humans and workloads share one model.

    Least privilege: an unknown or revoked principal is rejected here, before
    any router logic runs.
    """
    from services.api.core import db

    if not x_auralis_principal:
        raise HTTPException(status_code=401, detail="X-Auralis-Principal header required")
    row = db.get_conn().execute(
        "SELECT * FROM principal WHERE id = ?", (x_auralis_principal,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown principal")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="principal revoked")
    return dict(row)


@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version}


@app.get("/v1/readiness")
def readiness() -> dict[str, Any]:
    """Drives the real numbers in the web pre-loader. No fake progress."""
    from services.api.core import db

    checks: dict[str, bool] = {}
    conn = db.get_conn()
    try:
        checks["database"] = conn.execute("SELECT 1").fetchone() is not None
    except Exception:
        checks["database"] = False
    for label, sql in (
        ("evidence_index", "SELECT COUNT(*) c FROM evidence"),
        ("twin", "SELECT COUNT(*) c FROM asset"),
        ("policy_engine", "SELECT COUNT(*) c FROM policy_bundle WHERE active = 1"),
        ("tool_registry", "SELECT COUNT(*) c FROM tool_manifest"),
    ):
        try:
            checks[label] = conn.execute(sql).fetchone()["c"] > 0
        except Exception:
            checks[label] = False
    ready = all(checks.values())
    return {"ready": ready, "checks": checks, "llm_key_present": bool(os.environ.get("ANTHROPIC_API_KEY"))}


def _register_routers() -> None:
    """Attach the v1 surface. Import here so a lane still building does not
    take down the whole API during development."""
    from services.api.routers import api as api_router

    app.include_router(api_router.router)


_register_routers()
