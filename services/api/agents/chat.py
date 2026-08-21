"""Auralis AI Chat Orchestrator.

The conversational AI layer that connects the Auralis LLM to all city services
via tool calling. This is NOT an isolated chatbot — it has access to real data
through the tool system.

Architecture:
    User Message → Intent Detection → Tool Selection → Service Execution
    → Result Collection → LLM Narration → Response

The orchestrator:
  - Maintains conversation context per session
  - Detects intent and selects appropriate tools
  - Calls real services (weather, incidents, routing, etc.)
  - Uses the LLM to synthesize natural-language responses from tool results
  - Falls back to deterministic responses when LLM is unavailable
  - Never invents information — always grounded in tool results
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Generator

import httpx

from services.api.core import db

from . import chat_tools

log = logging.getLogger("auralis.chat")

# ──────────────────────────────────────────────────── Configuration

MAX_SESSIONS = 500
MAX_HISTORY_PER_SESSION = 50
MAX_TOOL_CALLS_PER_TURN = 5
CHAT_MODEL = os.environ.get("AURALIS_CHAT_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
CHAT_MAX_TOKENS = 1500
CHAT_TIMEOUT_S = 30.0


# ──────────────────────────────────────────────────── Session Store

@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system" | "tool_result"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_results:
            d["tool_results"] = self.tool_results
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ChatSession:
    id: str
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_active: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    context: dict[str, Any] = field(default_factory=dict)

    def add_message(self, msg: ChatMessage) -> None:
        self.messages.append(msg)
        self.last_active = datetime.now(UTC).isoformat()
        # Trim old messages
        if len(self.messages) > MAX_HISTORY_PER_SESSION:
            self.messages = self.messages[-MAX_HISTORY_PER_SESSION:]


# LRU session store
_sessions: OrderedDict[str, ChatSession] = OrderedDict()


def get_or_create_session(session_id: str | None = None) -> ChatSession:
    if session_id and session_id in _sessions:
        _sessions.move_to_end(session_id)
        return _sessions[session_id]
    sid = session_id or f"chat_{uuid.uuid4().hex[:12]}"
    session = ChatSession(id=sid)
    _sessions[sid] = session
    # Evict oldest sessions
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)


def delete_session(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None


def list_sessions() -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "message_count": len(s.messages),
            "created_at": s.created_at,
            "last_active": s.last_active,
        }
        for s in _sessions.values()
    ]


# ──────────────────────────────────────────────────── System Prompt

SYSTEM_PROMPT = """You are Auralis AI, the intelligent assistant for Auralis City — an AI-powered civic intelligence platform for Vijayawada, Andhra Pradesh, India.

Your role:
- Help citizens with civic information, incident reports, weather, traffic, routing, and emergency guidance
- Help city operators monitor and manage urban infrastructure and incidents
- Answer questions using REAL data from city systems via your tools
- NEVER invent or fabricate information — always use tool results
- If information is unavailable, say so honestly

Your personality:
- Professional yet approachable
- Clear and concise
- Proactive in suggesting helpful actions
- Empathetic during emergencies

You have access to these tools — use them when the user's question requires real data:
- get_weather: Current weather conditions
- search_incidents: Find active incidents nearby
- get_incident_details: Get full incident information
- create_civic_report: Report civic issues (potholes, garbage, flooding, etc.)
- get_city_status: Overall city operations summary
- search_nearby_services: Find hospitals, fire stations, police, etc.
- get_emergency_info: Emergency preparedness guidance
- get_traffic_status: Current traffic conditions
- search_city_knowledge: Search verified municipal bylaws, property tax rules, flood SOPs, and citizen charters

IMPORTANT RULES:
1. For factual questions about weather, incidents, or city data — ALWAYS use the appropriate tool
2. For municipal rules, property tax, waste segregation, building bylaws, or flood stages — ALWAYS search city knowledge
3. For emergency guidance — use get_emergency_info to provide verified information
4. When creating reports — confirm the details with the user first
5. Never claim to know real-time data without calling a tool
6. When a tool returns an error, communicate it honestly
7. Keep responses concise but informative
8. Use location context when available for more relevant answers"""


# ──────────────────────────────────────────────────── Intent Detection

def detect_intent(message: str) -> list[str]:
    """Detect which tools might be needed based on the user message.

    Returns a list of suggested tool names. The LLM makes the final decision,
    but this guides the deterministic fallback path.
    """
    msg = message.lower()
    tools = []

    weather_words = {"weather", "rain", "temperature", "wind", "humidity", "forecast",
                     "storm", "hot", "cold", "sunny", "cloudy", "monsoon", "cyclone"}
    incident_words = {"accident", "incident", "crash", "collision", "fire", "flood",
                      "emergency", "hazard", "danger", "blockage", "damage"}
    report_words = {"report", "complaint", "pothole", "garbage", "broken", "streetlight",
                    "water problem", "infrastructure", "issue", "problem"}
    traffic_words = {"traffic", "congestion", "jam", "road", "route", "commute", "drive"}
    emergency_words = {"emergency", "help", "what should i do", "safety", "evacuation",
                       "flooding", "earthquake", "fire safety", "first aid", "rescue"}
    service_words = {"hospital", "fire station", "police", "pharmacy", "school", "nearby",
                     "closest", "nearest", "where is", "find"}
    status_words = {"city status", "how is the city", "overview", "summary", "what's happening",
                    "what is happening", "situation", "update"}
    knowledge_words = {"tax", "property tax", "bylaw", "rule", "guideline", "prakasam barrage",
                       "discharge", "cusecs", "budameru", "segregation", "penalty", "fine",
                       "charter", "sla", "certificate", "license", "how to pay", "how do i pay"}

    if any(w in msg for w in weather_words):
        tools.append("get_weather")
    if any(w in msg for w in incident_words):
        tools.append("search_incidents")
    if any(w in msg for w in report_words):
        tools.append("create_civic_report")
    if any(w in msg for w in traffic_words):
        tools.append("get_traffic_status")
    if any(w in msg for w in emergency_words):
        tools.append("get_emergency_info")
    if any(w in msg for w in service_words):
        tools.append("search_nearby_services")
    if any(w in msg for w in status_words):
        tools.append("get_city_status")
    if any(w in msg for w in knowledge_words):
        tools.append("search_city_knowledge")

    return tools


# ──────────────────────────────────────────────────── LLM Interaction

def _build_anthropic_messages(session: ChatSession, user_message: str) -> list[dict[str, Any]]:
    """Build the Anthropic messages array from session history."""
    messages = []
    # Include recent history for context (last 10 messages)
    for msg in session.messages[-10:]:
        if msg.role in ("user", "assistant"):
            messages.append({"role": msg.role, "content": msg.content})
    # Add the current user message
    messages.append({"role": "user", "content": user_message})
    return messages


def _build_tool_definitions() -> list[dict[str, Any]]:
    """Convert our tool definitions to Anthropic's tool format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in chat_tools.TOOL_DEFINITIONS
    ]


def _call_anthropic_chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call the Anthropic API for chat completion."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("no_api_key")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    body: dict[str, Any] = {
        "model": CHAT_MODEL,
        "max_tokens": CHAT_MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools

    with httpx.Client(timeout=CHAT_TIMEOUT_S) as client:
        resp = client.post(ANTHROPIC_API_URL, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()


def _extract_response(api_result: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Extract text and tool calls from Anthropic response."""
    text_parts = []
    tool_calls = []

    for block in api_result.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block["text"])
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "name": block["name"],
                "arguments": block.get("input", {}),
            })

    return "\n".join(text_parts), tool_calls


def _execute_tool_calls(
    tool_calls: list[dict[str, Any]], context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Execute each tool call and return results."""
    results = []
    for tc in tool_calls[:MAX_TOOL_CALLS_PER_TURN]:
        result = chat_tools.execute_tool(tc["name"], tc["arguments"], context)
        results.append({
            "tool_use_id": tc["id"],
            "name": tc["name"],
            "result": result,
        })
    return results


# ──────────────────────────────────────────────────── Deterministic Fallback

def _deterministic_response(
    user_message: str,
    intents: list[str],
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate a response using deterministic tool calls when LLM is unavailable.

    This is the fallback that always works — no API key needed.
    """
    tool_calls = []
    tool_results = []

    if not intents:
        # General greeting or unknown intent
        return (
            "Hello! I'm **Auralis AI**, your civic intelligence assistant for Vijayawada. "
            "I can help you with:\n\n"
            "🌤️ **Weather** — current conditions and forecasts\n"
            "🚨 **Incidents** — active accidents, floods, emergencies\n"
            "📝 **Report Issues** — potholes, garbage, infrastructure damage\n"
            "🚗 **Traffic** — road conditions and congestion\n"
            "🏥 **Nearby Services** — hospitals, fire stations, police\n"
            "⚠️ **Emergency Guidance** — safety procedures and contacts\n"
            "📊 **City Status** — overall city operations\n\n"
            "How can I help you today?",
            [],
            [],
        )

    # Execute the detected tools
    for tool_name in intents[:MAX_TOOL_CALLS_PER_TURN]:
        args = _infer_tool_args(tool_name, user_message, context)
        result = chat_tools.execute_tool(tool_name, args, context)
        tc_id = f"det_{uuid.uuid4().hex[:8]}"
        tool_calls.append({"id": tc_id, "name": tool_name, "arguments": args})
        tool_results.append({"tool_use_id": tc_id, "name": tool_name, "result": result})

    # Synthesize a response from tool results
    response_parts = []
    city_name = context.get("city_name", "the selected city")
    for tr in tool_results:
        result = tr["result"]
        name = tr["name"]
        for tc in tool_calls:
            if tc.get("id") == tr.get("tool_use_id") and tc.get("arguments", {}).get("city_name"):
                city_name = tc["arguments"]["city_name"]
                break

        if result.get("status") == "error":
            response_parts.append(f"⚠️ {result.get('error', 'Service unavailable')}")
            continue

        if name == "get_weather":
            weather = result.get("weather", {})
            sources = weather.get("sources", {}) if isinstance(weather, dict) else {}
            sources_dict = (
                sources
                if isinstance(sources, dict)
                else {f"src_{i}": s for i, s in enumerate(sources)}
                if isinstance(sources, list)
                else {}
            )
            parsed_weather = False
            for src_name, src_data in sources_dict.items():
                if isinstance(src_data, dict) and src_data.get("status") == "ok":
                    temp = src_data.get("temperature_c")
                    humidity = src_data.get("humidity_pct")
                    rain = src_data.get("rain_rate_mm_h", 0)
                    wind = src_data.get("wind_speed_kph")
                    observed = src_data.get("observed_at", "")
                    provider = src_data.get("source_provider", "Live Telemetry Feed")

                    parts = []
                    if temp is not None:
                        parts.append(f"🌡️ **Temperature:** {temp}°C")
                    if humidity is not None:
                        parts.append(f"💧 **Relative Humidity:** {humidity}%")
                    if wind is not None:
                        parts.append(f"💨 **Wind Speed:** {wind} km/h")
                    if rain is not None and rain > 0:
                        parts.append(f"🌧️ **Precipitation:** {rain} mm/h")
                    else:
                        parts.append("☀️ **Conditions:** Clear / No Precipitation")

                    parts.append(f"📡 **Verified Source:** {provider}")

                    obs_str = f" as of {observed[:16].replace('T', ' ')} UTC" if observed else ""
                    response_parts.append(
                        f"**Current Verified Weather in {city_name}**{obs_str}:\n\n"
                        + "\n".join(parts)
                    )
                    parsed_weather = True
                    break

            if not parsed_weather and isinstance(weather, dict) and "temperature" in weather:
                temp = weather.get("temperature")
                hum = weather.get("humidity", "--")
                response_parts.append(f"**Current Weather in {city_name}:**\n\n🌡️ **Temperature:** {temp}°C\n💧 **Humidity:** {hum}%")
                parsed_weather = True

            if not parsed_weather:
                response_parts.append(f"Weather data for {city_name} is currently unavailable.")

        elif name == "search_incidents":
            count = result.get("count", 0)
            incidents = result.get("incidents", [])
            if count == 0:
                response_parts.append(f"✅ No active incidents found in {city_name}.")
            else:
                lines = [f"🚨 **{count} active incident(s) found in {city_name}:**\n"]
                for inc in incidents[:5]:
                    sev_emoji = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}.get(inc.get("severity"), "⚪")
                    lines.append(
                        f"{sev_emoji} **{inc.get('title', 'Untitled')}** "
                        f"— {inc.get('severity', '?').upper()} ({inc.get('state', '?')})"
                    )
                response_parts.append("\n".join(lines))

        elif name == "get_city_status":
            active = result.get("active_incidents", 0)
            by_sev = result.get("incidents_by_severity", {})
            weather = result.get("weather", "unavailable")
            sev_parts = [f"{k}: {v}" for k, v in by_sev.items()]
            response_parts.append(
                f"📊 **Vijayawada City Status**\n\n"
                f"🚨 **Active Incidents:** {active}\n"
                + (f"  Breakdown: {', '.join(sev_parts)}\n" if sev_parts else "")
                + f"🌤️ **Weather:** {weather}\n"
                + f"🕐 **Updated:** {result.get('timestamp', 'now')[:16]}"
            )

        elif name == "get_traffic_status":
            overall = result.get("overall_traffic", "unknown")
            emoji = {"clear": "🟢", "light": "🟡", "moderate": "🟠", "heavy": "🔴"}.get(overall, "⚪")
            affected = result.get("affected_areas", 0)
            response_parts.append(
                f"🚗 **Traffic Status:** {emoji} {overall.upper()}\n"
                f"📍 **Affected Areas:** {affected}"
            )
            details = result.get("congestion_details", [])
            if details:
                for d in details[:3]:
                    response_parts.append(
                        f"  • {d.get('title', 'Unknown')} — {d.get('severity', '?').upper()}"
                    )

        elif name == "get_emergency_info":
            guide = result.get("guide", {})
            title = guide.get("title", "Emergency Information")
            actions = guide.get("immediate_actions", [])
            contacts = guide.get("emergency_contacts", {})
            response_parts.append(f"⚠️ **{title}**\n")
            if actions:
                response_parts.append("**Immediate Actions:**")
                for i, action in enumerate(actions, 1):
                    response_parts.append(f"  {i}. {action}")
            if contacts:
                response_parts.append("\n**Emergency Contacts:**")
                for name_c, number in contacts.items():
                    response_parts.append(f"  📞 **{name_c}:** {number}")

        elif name == "create_civic_report":
            if result.get("report_created"):
                response_parts.append(
                    f"✅ **Report Submitted Successfully!**\n\n"
                    f"{result.get('message', 'Your report is being processed.')}"
                )
            else:
                response_parts.append(f"❌ Failed to create report: {result.get('error', 'Unknown error')}")

        elif name == "search_nearby_services":
            services = result.get("services", [])
            count = result.get("count", 0)
            if count == 0:
                response_parts.append(result.get("message", "No services found nearby."))
            else:
                response_parts.append(f"📍 **{count} nearby service(s) found:**\n")
                for svc in services[:5]:
                    response_parts.append(f"  • **{svc.get('name', 'Unknown')}** ({svc.get('type', '')})")

        elif name == "search_city_knowledge":
            passages = result.get("passages", [])
            if not passages:
                response_parts.append(result.get("message", "No matching municipal bylaws or documents found."))
            else:
                lines = ["📚 **Verified City Knowledge & Documentation:**\n"]
                for p in passages[:2]:
                    lines.append(f"**{p.get('title')}** — *{p.get('section')}*")
                    lines.append(f"{p.get('content')}\n")
                response_parts.append("\n".join(lines))

    if not response_parts:
        response_parts.append(
            "I processed your request but couldn't generate a specific response. "
            "Could you rephrase your question?"
        )

    return "\n\n".join(response_parts), tool_calls, tool_results


def _infer_tool_args(tool_name: str, message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Infer tool arguments from the user message for deterministic mode."""
    args: dict[str, Any] = {}

    # Check if a specific Indian city is mentioned in the query text
    from services.api.core import geo_cities
    target_city = None
    clean_msg = message.replace("?", " ").replace(",", " ").replace(".", " ").replace("!", " ")
    for token in clean_msg.split():
        if len(token) >= 3:
            found = geo_cities.find_city_by_name(token)
            if found:
                target_city = found
                break

    if target_city:
        args["latitude"] = target_city.lat
        args["longitude"] = target_city.lon
        args["city_name"] = target_city.name
    elif context.get("latitude") and context.get("longitude"):
        args["latitude"] = context["latitude"]
        args["longitude"] = context["longitude"]
        args["city_name"] = context.get("city_name", "Selected City")
    elif context.get("city_name"):
        args["city_name"] = context["city_name"]
        found = geo_cities.find_city_by_name(context["city_name"])
        if found:
            args["latitude"] = found.lat
            args["longitude"] = found.lon

    if tool_name in ("search_incidents", "search_city_knowledge"):
        args["query"] = message

    elif tool_name == "get_emergency_info":
        msg = message.lower()
        for etype in ["flooding", "earthquake", "fire", "cyclone", "accident",
                      "chemical_spill", "heatwave"]:
            if etype in msg or etype.replace("_", " ") in msg:
                args["emergency_type"] = etype
                break
        else:
            args["emergency_type"] = "general"

    elif tool_name == "search_nearby_services":
        msg = message.lower()
        for stype in ["hospital", "fire_station", "police_station", "pharmacy",
                      "school", "gas_station"]:
            if stype.replace("_", " ") in msg or stype in msg:
                args["service_type"] = stype
                break
        else:
            args["service_type"] = "hospital"

    elif tool_name == "create_civic_report":
        msg = message.lower()
        for itype in ["pothole", "garbage", "flooding", "waterlogging",
                      "road_blockage", "broken_streetlight", "fire", "accident"]:
            if itype.replace("_", " ") in msg or itype in msg:
                args["issue_type"] = itype
                break
        else:
            args["issue_type"] = "other"
        args["description"] = message

    return args


# ──────────────────────────────────────────────────── Main Chat Function

@dataclass
class ChatResponse:
    session_id: str
    message: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    model: str
    degraded: bool
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "message": self.message,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "model": self.model,
            "degraded": self.degraded,
            "timestamp": self.timestamp,
        }


def _local_custom_llm_chat(
    session: ChatSession,
    user_message: str,
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str] | None:
    """Execute response synthesis through the user's fine-tuned Auralis AP Urban LLM."""
    try:
        from services.api.core import custom_llm
        if not custom_llm.is_model_available():
            return None

        intents = detect_intent(user_message)
        det_text, tool_calls, tool_results = _deterministic_response(user_message, intents, context)

        city_label = context.get("city_name", "the selected city")
        system_prompt = (
            f"You are the Auralis AI civic intelligence assistant for {city_label}. "
            "Your task is to provide clear, helpful, accurate civic responses to citizens. "
            "Strict rules: Never invent fake facts or unauthorized actions. Ground your answer in the verified data provided below.\n\n"
            f"[VERIFIED REAL-TIME DATA & SYSTEM KNOWLEDGE FOR {city_label.upper()}]\n{det_text}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        generated = custom_llm.generate_response(messages, max_new_tokens=400, temperature=0.2)
        if generated:
            return generated, tool_calls, tool_results, "Auralis-AP-Urban-1.5B (Local)"
        return None
    except Exception as exc:
        log.warning("Local custom LLM inference skipped: %s", exc)
        return None


def chat(
    user_message: str,
    session_id: str | None = None,
    city_name: str | None = None,
    city_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    principal_id: str = "p_operator",
) -> ChatResponse:
    """Process a user message and return a response with dynamic multi-city resolution.

    This is the main entry point for the chat system. It:
    1. Gets or creates a session
    2. Resolves active city context or extracted city from message
    3. Detects intent from the message
    4. Tries the local custom fine-tuned LLM (Auralis AP Urban Intelligence)
    5. Tries Anthropic Claude tool calling if configured
    6. Falls back to deterministic tool execution if LLM unavailable
    7. Returns a structured response
    """
    from services.api.core import geo_cities

    # Resolve coordinates if city_id or city_name is provided
    resolved_city = None
    if city_id:
        resolved_city = geo_cities.get_city(city_id)
    elif city_name:
        resolved_city = geo_cities.find_city_by_name(city_name)

    if resolved_city:
        city_name = resolved_city.name
        if latitude is None or longitude is None:
            latitude = resolved_city.lat
            longitude = resolved_city.lon

    session = get_or_create_session(session_id)
    context = {
        "tenant_id": f"ten_{city_name.lower().replace(' ', '_')}" if city_name else "ten_ap_urban",
        "city_name": city_name or "Vijayawada",
        "city_id": city_id,
        "principal_id": principal_id,
        "latitude": latitude or 16.5062,
        "longitude": longitude or 80.6480,
    }
    session.context.update({k: v for k, v in context.items() if v is not None})

    # Record user message
    session.add_message(ChatMessage(role="user", content=user_message))

    # 1. Try Local Custom LLM first
    local_res = _local_custom_llm_chat(session, user_message, context)
    if local_res:
        response_text, tool_calls, tool_results, model = local_res
        degraded = False
    else:
        # 2. Try Anthropic Claude API path
        try:
            response_text, tool_calls, tool_results, model = _llm_chat(session, user_message, context)
            degraded = False
        except Exception as exc:
            log.info("LLM chat unavailable (%s), using deterministic path", exc)
            intents = detect_intent(user_message)
            response_text, tool_calls, tool_results = _deterministic_response(
                user_message, intents, context
            )
            model = "deterministic"
            degraded = True

    # Record assistant response
    session.add_message(ChatMessage(
        role="assistant",
        content=response_text,
        tool_calls=tool_calls if tool_calls else None,
        tool_results=tool_results if tool_results else None,
        metadata={"model": model, "degraded": degraded},
    ))

    return ChatResponse(
        session_id=session.id,
        message=response_text,
        tool_calls=tool_calls,
        tool_results=tool_results,
        model=model,
        degraded=degraded,
    )


def _llm_chat(
    session: ChatSession,
    user_message: str,
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Execute the LLM chat path with tool calling."""
    messages = _build_anthropic_messages(session, user_message)
    tools = _build_tool_definitions()

    # First call — LLM decides whether to use tools
    api_result = _call_anthropic_chat(messages, tools)
    text, tool_calls = _extract_response(api_result)

    all_tool_calls = list(tool_calls)
    all_tool_results: list[dict[str, Any]] = []

    # If the LLM wants to use tools, execute them and send results back
    if tool_calls and api_result.get("stop_reason") == "tool_use":
        tool_results = _execute_tool_calls(tool_calls, context)
        all_tool_results.extend(tool_results)

        # Build the follow-up messages with tool results
        # Add the assistant's response (with tool_use blocks)
        messages.append({"role": "assistant", "content": api_result["content"]})

        # Add tool results
        tool_result_content = [
            {
                "type": "tool_result",
                "tool_use_id": tr["tool_use_id"],
                "content": json.dumps(tr["result"], default=str),
            }
            for tr in tool_results
        ]
        messages.append({"role": "user", "content": tool_result_content})

        # Second call — LLM narrates the results
        api_result2 = _call_anthropic_chat(messages, tools)
        text2, tool_calls2 = _extract_response(api_result2)

        # Handle a second round of tool calls (rare but possible)
        if tool_calls2 and api_result2.get("stop_reason") == "tool_use":
            tool_results2 = _execute_tool_calls(tool_calls2, context)
            all_tool_calls.extend(tool_calls2)
            all_tool_results.extend(tool_results2)

            messages.append({"role": "assistant", "content": api_result2["content"]})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["tool_use_id"],
                        "content": json.dumps(tr["result"], default=str),
                    }
                    for tr in tool_results2
                ],
            })
            api_result3 = _call_anthropic_chat(messages)
            text, _ = _extract_response(api_result3)
            model = api_result3.get("model", CHAT_MODEL)
        else:
            text = text2
            model = api_result2.get("model", CHAT_MODEL)
    else:
        model = api_result.get("model", CHAT_MODEL)

    return text, all_tool_calls, all_tool_results, model


# ──────────────────────────────────────────────────── Streaming Chat

def chat_stream(
    user_message: str,
    session_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    principal_id: str = "p_operator",
) -> Generator[str, None, None]:
    """Stream a chat response as Server-Sent Events.

    Yields SSE-formatted strings. Falls back to non-streaming if the
    streaming API is unavailable.
    """
    # For now, wrap the synchronous chat in a streaming format
    # A full streaming implementation would use Anthropic's streaming API
    try:
        yield f"event: thinking\ndata: {json.dumps({'status': 'processing'})}\n\n"

        result = chat(
            user_message=user_message,
            session_id=session_id,
            latitude=latitude,
            longitude=longitude,
            principal_id=principal_id,
        )

        # Stream tool calls as they happen
        if result.tool_calls:
            for tc in result.tool_calls:
                yield f"event: tool_call\ndata: {json.dumps({'tool': tc['name'], 'args': tc.get('arguments', {})})}\n\n"

        if result.tool_results:
            for tr in result.tool_results:
                yield f"event: tool_result\ndata: {json.dumps({'tool': tr['name'], 'status': tr['result'].get('status', 'ok')})}\n\n"

        # Stream the final response
        response_data = result.to_dict()
        yield f"event: message\ndata: {json.dumps(response_data)}\n\n"

        yield f"event: done\ndata: {json.dumps({'session_id': result.session_id})}\n\n"

    except Exception as exc:
        log.exception("Chat stream failed")
        yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
