"""Chat API Router.

Surfaces the Auralis AI chat interface as REST + SSE streaming endpoints.
Every request goes through the same auth path as the rest of the API.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.api.auth import get_principal

router = APIRouter(prefix="/v1/chat", tags=["Auralis AI Chat"])


class ChatMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: str | None = None
    city_name: str | None = None
    city_id: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)


@router.post("")
def post_chat(body: ChatMessageIn, principal: dict = Depends(get_principal)) -> Any:
    """Send a message to Auralis AI and get a response.

    The AI will:
    - Detect what you need (weather, incidents, reports, etc.)
    - Call the appropriate city services
    - Return a natural-language response grounded in real data

    If the LLM is unavailable, the deterministic path answers using
    the same tools and data — `degraded: true` says which happened.
    """
    from services.api.agents import chat as chat_agent

    result = chat_agent.chat(
        user_message=body.message,
        session_id=body.session_id,
        city_name=body.city_name,
        city_id=body.city_id,
        latitude=body.latitude,
        longitude=body.longitude,
        principal_id=principal.get("id", "p_operator"),
    )
    return result.to_dict()


@router.post("/stream")
def post_chat_stream(body: ChatMessageIn, principal: dict = Depends(get_principal)) -> StreamingResponse:
    """Stream a chat response as Server-Sent Events.

    Events:
    - `thinking`: AI is processing
    - `tool_call`: A tool is being called (with tool name)
    - `tool_result`: Tool result received
    - `message`: The final response
    - `done`: Stream complete
    - `error`: An error occurred
    """
    from services.api.agents import chat as chat_agent

    return StreamingResponse(
        chat_agent.chat_stream(
            user_message=body.message,
            session_id=body.session_id,
            latitude=body.latitude,
            longitude=body.longitude,
            principal_id=principal.get("id", "p_operator"),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
def list_sessions(principal: dict = Depends(get_principal)) -> Any:
    """List active chat sessions."""
    from services.api.agents import chat as chat_agent

    return {"sessions": chat_agent.list_sessions()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, principal: dict = Depends(get_principal)) -> Any:
    """Get conversation history for a session."""
    from services.api.agents import chat as chat_agent

    session = chat_agent.get_session(session_id)
    if session is None:
        return {"error": "Session not found", "session_id": session_id}
    return {
        "session_id": session.id,
        "created_at": session.created_at,
        "last_active": session.last_active,
        "messages": [m.to_dict() for m in session.messages],
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, principal: dict = Depends(get_principal)) -> Any:
    """Clear a chat session."""
    from services.api.agents import chat as chat_agent

    deleted = chat_agent.delete_session(session_id)
    return {"deleted": deleted, "session_id": session_id}


@router.get("/model-status")
def get_chat_model_status() -> Any:
    """Get status of the local fine-tuned Auralis AP Urban Intelligence model."""
    from services.api.core import custom_llm

    return custom_llm.get_model_status()
