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

import dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
dotenv.load_dotenv(REPO_ROOT / ".env")
DB_PATH = os.environ.get("AURALIS_DB", str(REPO_ROOT / "auralis.db"))


from services.api.auth import PolicyDenied, get_principal


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

    # Warm the local model off the request path. Loading takes tens of seconds
    # on CPU; doing it lazily inside the first chat turn would stall that turn
    # and silently push it onto the deterministic path instead.
    try:
        from services.api.core import custom_llm

        custom_llm.trigger_background_load()
    except Exception:  # pragma: no cover - the chat path degrades on its own
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

# Origins are configured, not wildcarded. `https?://.*` accepted every site on
# the internet, which with allow_credentials is exactly what CORS exists to stop.
# Set AURALIS_ALLOWED_ORIGINS to a comma-separated list in production.
_DEV_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
_configured = [
    o.strip() for o in os.environ.get("AURALIS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
_allow_origins = _configured or _DEV_ORIGINS
# Vercel preview deployments get a new subdomain per build, so they are matched
# by pattern rather than listed. Only enabled when a production origin is set.
_allow_regex = r"https://.*\.vercel\.app" if _configured else None

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_allow_regex,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-Id"],
)


from services.api.security import security_middleware

# Registered before correlation_id, so it ends up OUTERMOST: a throttled or
# unauthenticated request is rejected before any handler work happens.
app.middleware("http")(security_middleware)


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




@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "Auralis Autonomous City API",
        "version": app.version,
        "status": "online",
        "web_ui": "http://localhost:3000",
        "command_center": "http://localhost:3000/command",
        "interactive_docs": "http://localhost:8000/docs",
        "health": "http://localhost:8000/v1/health",
    }


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
    """Attach the v1 surface, emergency incident response, chat, civic reports, routing, alerts, analytics, and cities."""
    from services.api.routers import alerts as alerts_router
    from services.api.routers import analytics as analytics_router
    from services.api.routers import api as api_router
    from services.api.routers import chat as chat_router
    from services.api.routers import cities as cities_router
    from services.api.routers import emergency as emergency_router
    from services.api.routers import reports as reports_router
    from services.api.routers import routing as routing_router

    app.include_router(api_router.router)
    app.include_router(emergency_router.router)
    app.include_router(chat_router.router)
    app.include_router(reports_router.router)
    app.include_router(routing_router.router)
    app.include_router(alerts_router.router)
    app.include_router(analytics_router.router)
    app.include_router(cities_router.router)


_register_routers()
