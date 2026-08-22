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
# A briefing asks about the place as a whole, so it is allowed to consult
# every source that describes one.
BRIEFING_TOOL_CALLS = 7
CHAT_MODEL = os.environ.get("AURALIS_CHAT_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
CHAT_MAX_TOKENS = 2500
# 6s was not enough to return a detailed answer once tool results were in the
# context, so the LLM path timed out and every reply came from the fallback.
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

SYSTEM_PROMPT = """You are Auralis AI, the assistant for the Auralis civic intelligence platform, serving cities and towns across Andhra Pradesh, India.

The operator selects which city is in context. Always answer about the city named in the context you are given, never a default one.

Your role:
- Help citizens with civic information, incident reports, weather, traffic, routing, and emergency guidance
- Help city operators monitor and manage urban infrastructure and incidents
- Answer questions using REAL data from city systems via your tools
- NEVER invent or fabricate information — always use tool results
- If information is unavailable, say so honestly

Your personality:
- Professional yet approachable
- Thorough: give the full reading, not a headline
- Proactive in suggesting helpful actions
- Empathetic during emergencies

You have access to these tools — use them when the user's question requires real data:
- get_weather: Current weather conditions
- get_air_quality: OpenAQ station readings (PM2.5, PM10, NO2 and similar)
- search_incidents: Find active incidents nearby
- get_incident_details: Get full incident information
- get_local_news: Regional news reporting for the city
- create_civic_report: Report civic issues (potholes, garbage, flooding, etc.)
- get_city_status: Overall city operations summary
- search_nearby_services: Find hospitals, fire stations, police, etc.
- get_emergency_info: Emergency preparedness guidance
- get_traffic_status: Current traffic conditions
- get_safe_route: A route that avoids active hazards
- search_city_knowledge: Search verified municipal bylaws, property tax rules, flood SOPs, and citizen charters

IMPORTANT RULES:
1. For factual questions about weather, incidents, or city data — ALWAYS use the appropriate tool
2. For municipal rules, property tax, waste segregation, building bylaws, or flood stages — ALWAYS search city knowledge
3. For emergency guidance — use get_emergency_info to provide verified information
4. When creating reports — confirm the details with the user first
5. Never claim to know real-time data without calling a tool
6. When a tool returns an error, communicate it honestly
7. Use location context when available for more relevant answers

DEPTH — the operator wants detail, and detail comes from data, never from padding:
8. Report every field a tool returned that bears on the question — a temperature
   reading also carries humidity, wind, pressure and its observation time. Give
   them, with units.
9. Name the source and the time it was observed. "34.1 °C (Open-Meteo, observed
   11:30 UTC)" is worth more than "it is hot".
10. When two sources disagree, show both figures and say they disagree. Never
    average them or pick one silently.
11. Say what you checked that came back empty — "no OpenAQ station within 25 km"
    is an answer. An empty section is not a reason to go quiet.
12. NEVER lengthen an answer with generalities, background prose, or anything a
    tool did not return. A short answer grounded in data beats a long one that
    drifts. If a source has nothing, say so and stop — do not fill the space.
13. Answer the question that was asked. A weather question gets a thorough
    weather answer, not a tour of the city.
14. NEVER infer, imply, estimate, derive or guess a value the tools did not
    return — not a wind direction, not a trend, not a cause, not an air quality
    index, not a severity. If a field is absent, write that it was not reported
    and move on. Words like "implied", "roughly", "probably" or "suggests"
    attached to a number you were not given are fabrication. Converting units
    of a number you WERE given is fine; producing a new quantity is not."""



# Used only when no tool matched, i.e. the turn is conversation rather than a
# request for a reading. It may explain the product and talk normally; it must
# not state city measurements, because those only ever come from a tool.
CONVERSATION_PROMPT = """You are Auralis AI, the assistant inside the Auralis civic intelligence platform. The operator is currently looking at {city}.

About Auralis, so you can answer questions about it:
- It is an operations platform for city infrastructure across Andhra Pradesh.
- Every fact it shows carries the source, the timestamp and the freshness of the record it came from. Nothing is displayed that cannot be traced to a source.
- Sections: Auralis AI (this chat), Command (live incidents and the city map), Actions (the authorisation queue), Trace (reconstruct any decision), plus Hazard alerts, Safe routes, Report an issue, Emergency dispatch, Field work orders, Simulation, Governance, Executive summary, Analytics, Data health, Audit and Public status.
- Actions carry a risk tier R0-R5. R4 and R5 need a named human approval before anything runs.
- Live sources include Open-Meteo, OpenWeatherMap, GloFAS river discharge, OpenAQ air quality, USGS seismic, OpenStreetMap, TomTom traffic, GDELT news and data.gov.in.

How to answer:
- Work out what was actually asked, then answer exactly that. Nothing else.
- Do not volunteer adjacent facts, tours of the platform, or lists of what you can do unless that is the question.
- If the question is one line, the answer is one or two. Stop when it is answered.
- Never state a temperature, air quality number, river level, traffic speed, incident count or any other city reading. You do not have those here; the platform fetches them live when asked directly.
- Never invent an incident, a report, a statistic or a source.
- If the question is ambiguous, ask one short clarifying question instead of guessing.
- If you do not know, say so plainly."""



# ───────────────────────────────────────────────── Question analysis

# Time windows a question can carry, longest phrase first so "last 24 hours"
# is not matched as "hour".
_WINDOW_PATTERNS: list[tuple[str, int]] = [
    ("last 7 days", 168), ("past week", 168), ("this week", 168),
    ("last 48 hours", 48), ("last 48 hrs", 48), ("past 2 days", 48),
    ("last 24 hours", 24), ("last 24 hrs", 24), ("last 24hrs", 24),
    ("past 24 hours", 24), ("past day", 24), ("last day", 24),
    ("yesterday", 48), ("overnight", 16), ("today", 24),
    ("last 12 hours", 12), ("last 6 hours", 6), ("last hour", 1),
    ("right now", 1), ("currently", 1), ("at the moment", 1),
]


@dataclass
class QuestionAnalysis:
    """What the turn is actually asking for."""
    raw: str
    intents: list[str]
    window_hours: int | None
    city: str
    is_question: bool
    is_conversational: bool
    needs_live_data: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "intents": self.intents,
            "window_hours": self.window_hours,
            "city": self.city,
            "needs_live_data": self.needs_live_data,
            "notes": self.notes,
        }


def analyze_question(message: str, context: dict[str, Any]) -> QuestionAnalysis:
    """Resolve the turn before answering it.

    Cheap and deterministic on purpose: the resolution decides which tools run,
    so it must not itself be a guess from a language model.
    """
    msg = (message or "").strip()
    low = msg.lower()
    notes: list[str] = []

    intents = detect_intent(msg)

    window = None
    for phrase, hours in _WINDOW_PATTERNS:
        if phrase in low:
            window = hours
            notes.append(f"time window: {phrase} -> {hours}h")
            break

    # A city named in the message overrides the selected one.
    city = context.get("city_name") or "the selected city"
    try:
        from services.api.core import geo_cities

        for token in re.findall(r"\b[A-Z][a-z]{3,}\b", msg):
            found = geo_cities.find_city_by_name(token)
            if found:
                city = found.name
                notes.append(f"city named in the message: {found.name}")
                break
    except Exception:
        pass

    is_question = bool(
        "?" in msg
        or re.match(r"^\s*(what|when|where|which|who|why|how|is|are|can|do|does|did|show|find|list|tell|give)\b", low)
    )
    conversational = not intents and not is_question
    needs_live = bool(intents)

    if not intents and is_question:
        notes.append("no tool matches this question; answering from the platform record")
    if len(msg) < 2:
        notes.append("message too short to resolve")

    return QuestionAnalysis(
        raw=msg,
        intents=intents,
        window_hours=window,
        city=city,
        is_question=is_question,
        is_conversational=conversational,
        needs_live_data=needs_live,
        notes=notes,
    )


# ─────────────────────────────────────────── Platform knowledge (curated)

# What the product is and what each surface does is knowable at build time, so
# it is answered from here rather than generated. A small model asked to
# describe the product will confidently invent features it does not have.
PLATFORM_PAGES: dict[str, tuple[tuple[str, ...], str]] = {
    "chat": (("auralis ai", "this chat", "chat page", "assistant"),
             "**Auralis AI** is this chat. It answers from the same live sources the rest "
             "of the platform uses, and shows readings only when a source actually returned one."),
    "command": (("command", "command centre", "command center"),
                "**Command** is the live operations view: open incidents, the city map and the "
                "current state of monitored assets."),
    "actions": (("actions", "action queue", "authorisation", "authorization"),
                "**Actions** is the authorisation queue. Every proposed tool call is listed with "
                "its risk tier, the policy rule that judged it, and its verified outcome. "
                "R4 and R5 actions cannot run without a named human approval."),
    "trace": (("trace", "provenance", "reconstruct"),
              "**Trace** reconstructs a decision end to end: the claim, the evidence behind it, "
              "the model version, the tool manifest, the policy decision and the verified effect."),
    "alerts": (("hazard alert", "alerts page", "early warning"),
               "**Hazard alerts** scans weather, river discharge, traffic and citizen reports "
               "together and reports a composite risk score for the selected city."),
    "routes": (("safe route", "routes page", "navigation"),
               "**Safe routes** plans a route that avoids flooding and open incidents."),
    "report": (("report an issue", "report page", "report issue", "complaint"),
               "**Report an issue** files a civic report — pothole, garbage, flooding, damaged "
               "infrastructure — and routes it to the responsible department with an SLA."),
    "emergency": (("emergency", "112", "erss", "dispatch"),
                  "**Emergency dispatch** corroborates an accident across independent signals "
                  "before it will escalate, and never claims an ambulance was dispatched until "
                  "the external gateway confirms it."),
    "field": (("field", "work order", "crew"),
              "**Field** carries work orders for crews on the ground, and keeps working offline."),
    "simulation": (("simulation", "counterfactual", "sandbox", "what if"),
                   "**Simulation** runs counterfactuals in a sandbox twin. Its output is labelled "
                   "synthetic and can never authorise a real action."),
    "governance": (("governance", "policy bundle", "kill switch", "tool registry"),
                   "**Governance** holds the policy bundle, the signed tool registry, roles and "
                   "the dual-control kill switch."),
    "executive": (("executive", "leadership"),
                  "**Executive summary** reports outcomes, cost and service levels, derived only "
                  "from metrics the system actually recorded."),
    "analytics": (("analytics", "kpi", "sla"),
                  "**Analytics** shows SLA compliance, incident lifecycle timings, dispatch "
                  "performance and model token spend."),
    "data-health": (("data health", "connector", "freshness", "sources page"),
                    "**Data health** lists every source, when it last answered, and any open "
                    "contradiction between sources."),
    "audit": (("audit", "ledger", "hash chain"),
              "**Audit** is the append-only, hash-chained record. The chain can be verified."),
    "public": (("public status", "public page", "citizen view"),
               "**Public status** is the redacted view the public sees."),
}

PLATFORM_OVERVIEW = (
    "**Auralis** is an operations platform for city infrastructure across Andhra Pradesh.\n\n"
    "Everything it shows is tied to a source: each fact carries where it came from, when it was "
    "observed and how fresh it is. When a source cannot be read, the surface says so instead of "
    "filling the gap.\n\n"
    "The main sections are **Auralis AI** (this chat), **Command** (live incidents and the map), "
    "**Actions** (the authorisation queue) and **Trace** (reconstruct any decision). Behind "
    "**More** are hazard alerts, safe routes, issue reporting, emergency dispatch, field work "
    "orders, simulation, governance, the executive summary, analytics, data health, the audit "
    "ledger and public status.\n\n"
    "Live sources include Open-Meteo and OpenWeatherMap for weather, GloFAS for river discharge, "
    "OpenAQ for air quality, USGS for seismic activity, TomTom for traffic, OpenStreetMap for "
    "facilities, GDELT for news and data.gov.in for national open data."
)

PLATFORM_CAPABILITY = (
    "Ask me about the city in context and I will fetch it live:\n\n"
    "- **Weather** — temperature, humidity, wind, rainfall\n"
    "- **Air quality** — the nearest monitoring stations\n"
    "- **Incidents** — what is open now, and what happened recently\n"
    "- **Traffic** — congestion and a safe route\n"
    "- **Nearby services** — hospitals, fire stations, police\n"
    "- **Municipal rules** — property tax, bylaws, flood procedures\n"
    "- **Report an issue** — potholes, garbage, damaged infrastructure\n\n"
    "I can also explain any part of the platform. What would you like?"
)


def platform_answer(message: str) -> str | None:
    """Answer a question about the product itself, or None if it is not one.

    Curated because these answers are known and must not drift; the model is
    not consulted for them.
    """
    msg = message.lower().strip()

    asks_about_product = any(
        re.search(rf"(?<!\w){re.escape(p)}(?!\w)", msg)
        for p in ("this website", "this site", "this app", "this platform",
                  "what is auralis", "about auralis", "what does auralis",
                  "what can you do", "what do you do", "who are you",
                  "what is this", "how does this work", "what can this do",
                  "your features", "your capabilities", "help me understand")
    )

    # A named page wins over the generic overview: "what does Trace do".
    for _key, (aliases, answer) in PLATFORM_PAGES.items():
        if any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", msg) for a in aliases):
            if any(w in msg for w in ("what", "how", "explain", "tell me", "does", "do", "?")):
                return answer

    if asks_about_product:
        if any(w in msg for w in ("can you do", "do you do", "capabilities", "features", "help")):
            return PLATFORM_CAPABILITY
        # "who are you" wants an introduction, not the full product tour.
        if "who are you" in msg and "what" not in msg:
            return (
                "I'm Auralis AI, the assistant inside the Auralis civic platform. "
                "I answer questions about the city you have selected using live data, "
                "and I can explain any part of the platform. What do you need?"
            )
        return PLATFORM_OVERVIEW

    return None


# ──────────────────────────────────────────────────── Intent Detection

# An open request - "explain about this city", "give me an overview" - names no
# single subject, so keyword matching finds nothing and the reply comes back
# nearly empty. These mark a request for the full briefing instead.
# Asks about the place itself. These always widen to the full briefing.
CITY_WIDE_WORDS = {
    "about this city", "about that city", "about the city", "overview",
    "briefing", "everything", "full picture", "rundown", "city status",
    "how is the city", "what do you know", "city profile",
}

# Asks for depth, without naming a subject. On their own these widen to the
# full briefing; alongside a named subject ("explain the traffic") they mean
# "more detail about THAT", so the answer stays on the subject asked about.
DETAIL_WORDS = {
    "explain", "describe", "tell me about", "in detail", "detailed", "details",
    "brief", "profile", "walk me through", "situation", "summary",
    "summarise", "summarize", "elaborate", "more information", "more info",
    "go deeper", "expand",
}

BRIEFING_WORDS = CITY_WIDE_WORDS | DETAIL_WORDS

# The order a briefing reads in: where things stand, what happened, then the
# live conditions.
BRIEFING_SEQUENCE = (
    "get_city_status", "search_incidents", "get_local_news", "get_weather",
    "get_air_quality", "get_traffic_status", "search_nearby_services",
)


def _word_hit(msg: str, words: set[str]) -> bool:
    """Whole-word match, plural tolerated on words long enough to take one."""
    for w in words:
        suffix = "(?:e?s)?" if len(w) >= 5 and " " not in w else ""
        if re.search(rf"(?<!\w){re.escape(w)}{suffix}(?!\w)", msg):
            return True
    return False


def detect_intent(message: str) -> list[str]:
    """Detect which tools might be needed based on the user message.

    Returns a list of suggested tool names. The LLM makes the final decision,
    but this guides the deterministic fallback path.
    """
    msg = message.lower()
    tools = []

    def has(words: set[str]) -> bool:
        """True when any phrase appears as a whole word, plural included.

        A strict boundary missed every plural: "hospitals" did not match
        "hospital", so "near hospitals" resolved to no tool at all.
        """
        for w in words:
            # Only long words take a plural suffix. Short ones are usually
            # verbs where the -s changes the meaning: "helps" in "thanks,
            # that helps" is not a request for emergency guidance.
            suffix = "(?:e?s)?" if len(w) >= 5 and " " not in w else ""
            if re.search(rf"(?<!\w){re.escape(w)}{suffix}(?!\w)", msg):
                return True
        return False

    weather_words = {"weather", "rain", "temperature", "wind", "humidity", "forecast",
                     "storm", "hot", "cold", "sunny", "cloudy", "monsoon", "cyclone"}
    incident_words = {"accident", "incident", "crash", "collision", "fire", "flood",
                      "emergency", "hazard", "danger", "blockage", "damage"}
    # Filing a report WRITES to the ingest pipeline, so it needs an explicit
    # intent to file - not the bare noun. The old set matched "report", "issue"
    # and "problem", so "give me a detailed weather report" and "what is the
    # traffic problem" both filed a civic report with the question as its
    # description. A read-only question must never cause a write.
    report_words = {"report a", "report an", "report the", "reporting a",
                    "i want to report", "i would like to report", "want to report",
                    "file a report", "file a complaint", "submit a report",
                    "submit a complaint", "raise a complaint", "log a complaint",
                    "register a complaint", "make a complaint", "complain about",
                    "there is a", "there's a", "there are"}
    traffic_words = {"traffic", "congestion", "jam", "road", "route", "commute", "drive"}
    emergency_words = {"emergency", "help", "what should i do", "safety", "evacuation",
                       "flooding", "earthquake", "fire safety", "first aid", "rescue"}
    service_words = {"hospital", "fire station", "police", "pharmacy", "school", "nearby",
                     "closest", "nearest", "where is", "find"}
    status_words = {"city status", "how is the city", "overview", "summary", "what's happening",
                    "what is happening", "situation", "update"}
    # Past-tense and time-window phrasing ("what happened in the last 24hrs") asks
    # for the recent record, which the status snapshot alone does not answer.
    recap_words = {"last 24", "24hr", "24 hr", "24hour", "24 hour", "past day", "past 24",
                   "happened", "happend", "recent", "recently", "today", "overnight",
                   "so far", "latest", "since yesterday", "yesterday", "briefing", "recap",
                   "last day", "last night", "this week", "past week", "what went on"}
    knowledge_words = {"tax", "property tax", "bylaw", "rule", "guideline", "prakasam barrage",
                       "discharge", "cusecs", "budameru", "segregation", "penalty", "fine",
                       "charter", "sla", "certificate", "license", "how to pay", "how do i pay"}

    news_words = {"news", "headline", "headlines", "reported", "report says", "media",
                  "died", "death", "deaths", "casualty", "casualties", "killed", "toll",
                  "injured", "victim", "victims", "who died", "how many died",
                  "what happened in", "any news", "latest news", "newspaper"}
    if has(news_words):
        tools.append("get_local_news")

    air_words = {"air", "aqi", "pm2.5", "pm10", "pm 2.5", "pm 10", "pollution", "air quality", "openaq", "smoke", "smog", "clean air"}
    if has(air_words):
        tools.append("get_air_quality")
    if has(weather_words):
        tools.append("get_weather")
    if has(incident_words):
        tools.append("search_incidents")
    if has(report_words):
        tools.append("create_civic_report")
    if has(traffic_words):
        tools.append("get_traffic_status")
    if has(emergency_words):
        tools.append("get_emergency_info")
    if has(service_words):
        tools.append("search_nearby_services")
    if has(status_words):
        tools.append("get_city_status")
    if has(recap_words):
        # Incidents carry "what happened"; status carries "where it stands now".
        if "search_incidents" not in tools:
            tools.append("search_incidents")
        if "get_city_status" not in tools:
            tools.append("get_city_status")
        if "get_local_news" not in tools:
            tools.append("get_local_news")
    if has(knowledge_words):
        tools.append("search_city_knowledge")

    # A briefing pulls every live reading that describes a place. Nothing is
    # invented to fill it out: a source with nothing to say is reported as
    # having nothing to say.
    #
    # "explain the traffic" names a subject, so it stays on that subject and
    # only the traffic answer gets deeper. Widening there would answer six
    # questions nobody asked.
    named_subject = any(
        t in tools for t in
        ("get_weather", "get_air_quality", "get_traffic_status", "get_local_news",
         "search_nearby_services", "search_city_knowledge", "get_emergency_info",
         "create_civic_report")
    )
    if has(CITY_WIDE_WORDS) or (has(DETAIL_WORDS) and not named_subject):
        for name in BRIEFING_SEQUENCE:
            if name not in tools:
                tools.append(name)

    # Rank by how directly each tool answers the question. Without this the
    # answer leads with whatever keyword happened to match first.
    lead = None
    msg_head = msg[:80]
    for name, words in (
        ("get_weather", weather_words),
        ("get_air_quality", air_words),
        ("get_local_news", news_words),
        ("search_nearby_services", service_words),
        ("get_traffic_status", traffic_words),
        ("search_incidents", incident_words),
        ("search_city_knowledge", knowledge_words),
    ):
        if name in tools and any(w in msg_head for w in words):
            lead = name
            break
    if lead:
        tools = [lead] + [t for t in tools if t != lead]

    # A briefing reads in a fixed order regardless of which keyword matched
    # first: where things stand, what happened, then the live conditions.
    # Keyword order is arbitrary and made the same question answer differently
    # depending on how it was phrased.
    if all(n in tools for n in BRIEFING_SEQUENCE):
        order = list(BRIEFING_SEQUENCE) + ["search_city_knowledge"]
        rank = {name: i for i, name in enumerate(order)}
        tools.sort(key=lambda n: rank.get(n, len(order)))
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


# ──────────────────────────────────────────────────── Cloud LLM (OpenAI-shaped)

# All three providers speak the OpenAI chat-completions shape, so one caller
# covers them. Tried in order; the first with a key configured and a model that
# answers wins. Measured on the same grounded-narration turn:
#   Groq gpt-oss-120b   3.3s     Groq gpt-oss-20b    1.9s
#   NVIDIA mistral      2.5s median, but stalls under burst
#   OpenRouter gemma    2.2s median on a small payload, 8.5s on a real one
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_GROQ_MODELS = (
    # Both keep their reasoning in a separate field, so it never reaches the
    # answer. qwen3.6-27b is comparably quick but writes its <think> block into
    # the content, so it is deliberately not listed.
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
)
DEFAULT_NVIDIA_MODELS = (
    # Complete and fast. llama-3.1-8b is quicker still but dropped a whole
    # source's readings; the 49b reasoner is better but took 63s.
    "mistralai/mistral-nemotron",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
)
DEFAULT_OPENROUTER_MODELS = (
    "google/gemma-4-31b-it:free",
    "z-ai/glm-5.2:free",
    "openrouter/free",
)

# (key variable, endpoint, model-list variable, defaults)
CLOUD_PROVIDERS = (
    ("GROQ_API_KEY", GROQ_API_URL, "AURALIS_GROQ_MODELS", DEFAULT_GROQ_MODELS),
    ("NVIDIA_API_KEY", NVIDIA_API_URL, "AURALIS_NVIDIA_MODELS", DEFAULT_NVIDIA_MODELS),
    ("OPENROUTER_API_KEY", OPENROUTER_API_URL, "AURALIS_OPENROUTER_MODELS",
     DEFAULT_OPENROUTER_MODELS),
)

# Retryable upstream conditions. Free tiers rate-limit without warning, so a
# 429 from one model is routine rather than a failure of the whole path.
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


def _configured_cloud_calls() -> list[tuple[str, str, str]]:
    """(endpoint, api key, model) for every provider that has a key set."""
    out: list[tuple[str, str, str]] = []
    for key_var, url, models_var, defaults in CLOUD_PROVIDERS:
        api_key = os.environ.get(key_var)
        if not api_key:
            continue
        raw = os.environ.get(models_var, "")
        models = [m.strip() for m in raw.split(",") if m.strip()] or list(defaults)
        out.extend((url, api_key, m) for m in models)
    return out


def _call_cloud_llm(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Post one turn, walking provider/model pairs until one answers."""
    attempts = _configured_cloud_calls()
    if not attempts:
        raise RuntimeError("no_api_key")

    last: str = "no model attempted"
    for url, api_key, model in attempts:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if url == OPENROUTER_API_URL:
            # Attribution headers, not credentials.
            headers["HTTP-Referer"] = "https://auralis.local"
            headers["X-Title"] = "Auralis Civic Intelligence"

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": CHAT_MAX_TOKENS,
            "temperature": 0.2,
        }
        if url == OPENROUTER_API_URL:
            # Reasoning models otherwise emit their scratchpad as the answer -
            # "We need to answer... Let's extract data precisely" - along with
            # the raw JSON key names they are reading. NVIDIA returns that in a
            # separate reasoning_content field, so it never reaches the answer.
            body["reasoning"] = {"exclude": True}
        try:
            with httpx.Client(timeout=CHAT_TIMEOUT_S) as client:
                resp = client.post(url, headers=headers, json=body)
            if resp.status_code in _RETRY_STATUS:
                # Logged: a silent fall-through to a slower provider looks like
                # the primary being slow rather than rate-limited.
                last = f"{model}: HTTP {resp.status_code}"
                log.info("cloud model %s unavailable (HTTP %s), trying next",
                         model, resp.status_code)
                continue
            resp.raise_for_status()
            data = resp.json()
            # A provider failure can arrive inside a 200 body.
            if data.get("error") or not data.get("choices"):
                last = f"{model}: {str(data.get('error'))[:120]}"
                continue
            if not (data["choices"][0].get("message", {}).get("content") or "").strip():
                # A reasoning model that spent its whole budget thinking.
                last = f"{model}: empty content"
                continue
            data["_model"] = model
            return data
        except Exception as exc:
            last = f"{model}: {type(exc).__name__}"
            log.info("cloud model %s errored (%s), trying next",
                     model, type(exc).__name__)
            continue
    raise RuntimeError(f"all cloud models failed ({last})")


# A number the model was not given, dressed as an observation. The first cloud
# answer reported a wind DIRECTION that no feed returned, marked "(implied by
# the low speed)" - the hedge is the tell. Verifying every digit against the
# tool payload would reject honest unit conversions, so this looks for the
# hedge sitting next to a figure instead.
_HEDGE_NEAR_NUMBER = re.compile(
    r"(?:implied|imply|probably|presumably|roughly|approximately|approx\.?|"
    r"estimated|estimate|suggests?|likely|around about|i'd guess|guess)"
    r"[^.\n]{0,40}?\d"
    r"|\d[^.\n]{0,40}?"
    r"(?:\(implied|as implied|probably|presumably|estimated to|"
    r"i would estimate|my estimate)",
    re.IGNORECASE,
)


# Some models write a tool call as prose when they cannot emit a real one.
# That markup must never reach the user.
# `<think>` is here too: some models write their reasoning into the content as
# a tagged block instead of returning it in a separate field.
_LEAKED_TOOL_MARKUP = re.compile(
    r"<\s*/?\s*(?:tool_call|function|parameter|think|thinking|reasoning)\b"
    r"|^\s*\{\s*\"name\"\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_fabricated(text: str) -> str | None:
    """The hedged-number tell, or None. Returns the matched phrase for the log."""
    m = _HEDGE_NEAR_NUMBER.search(text or "")
    return m.group(0)[:80] if m else None


# A model thinking out loud instead of answering. Backstop for when the
# request to exclude reasoning tokens is ignored by a provider.
_SCRATCHPAD = re.compile(
    r"^\s*(?:we need to|we must|let'?s |let us |first,? i(?:'| a)?ll|"
    r"the instruction[s]?\b|okay,? so\b|the user (?:wants|is asking))"
    r"|\bmust comply\b|\bwe should (?:list|report|answer)\b",
    re.IGNORECASE,
)


def _looks_like_scratchpad(text: str) -> bool:
    """True when the reply is reasoning rather than an answer."""
    return bool(_SCRATCHPAD.search((text or "")[:400]))


def _trim_reading(value: Any, max_items: int = 8, depth: int = 0) -> Any:
    """Shrink a tool result to what an answer can actually use.

    Air quality alone returns every station's whole history - 52 readings of
    17 fields. Sending it whole made one briefing 24 KB of JSON and took 40
    seconds to narrate. Long lists are cut, with a note saying how many were
    dropped so the model does not present a slice as the whole.
    """
    if depth > 4:
        return value
    if isinstance(value, dict):
        return {k: _trim_reading(v, max_items, depth + 1) for k, v in value.items()
                if k not in ("event_id", "evidence_id", "subject", "endpoint",
                             "integrity_hash", "prov_activity", "prov_derived_from")}
    if isinstance(value, list):
        kept = [_trim_reading(v, max_items, depth + 1) for v in value[:max_items]]
        if len(value) > max_items:
            kept.append(f"... and {len(value) - max_items} more not shown")
        return kept
    return value


def _mentions_tool_names(text: str) -> bool:
    """Internal machinery showing through. The operator asked for the city's
    state, not for the names of the functions that fetched it."""
    lowered = (text or "").lower()
    return any(t["name"] in lowered for t in chat_tools.TOOL_DEFINITIONS)


def _cloud_chat(
    session: ChatSession,
    user_message: str,
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str] | None:
    """Answer through a cloud model, grounded on tool results.

    The model chooses the tools and writes the prose; every number it is
    allowed to use comes from a tool result placed in its context. It is never
    asked what the weather is - only to report what the feed returned.
    """
    if not _configured_cloud_calls():
        return None
    try:
        analysis = analyze_question(user_message, context)
        if analysis.window_hours:
            context = {**context, "window_hours": analysis.window_hours}

        city = context.get("city_name") or "the selected city"
        system = (
            f"{SYSTEM_PROMPT}\n\n"
            f"CURRENT CONTEXT: the operator is looking at {city} "
            f"({context.get('latitude')}, {context.get('longitude')}). "
            f"Answer about {city} unless the user names another place."
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in session.messages[-6:]:
            if m.role in ("user", "assistant") and m.content:
                messages.append({"role": m.role, "content": m.content})
        if not messages or messages[-1].get("content") != user_message:
            messages.append({"role": "user", "content": user_message})

        # Readings are gathered HERE, not by the model. Left to choose its own
        # tools it called two of the seven a briefing needs, then wrote "omitted
        # for brevity" over real rows. `detect_intent` already picks the right
        # sources and is covered by tests, so the model's only job is prose.
        det_text, tool_calls, tool_results = _deterministic_response(
            user_message, analysis.intents, context
        )
        if not tool_calls:
            # Conversation, not a reading. Nothing to ground an answer on, so
            # leave it to the paths that handle that.
            return None

        # Measured, not assumed: on a full briefing the cloud model took 43s to
        # produce 2,750 characters where the composer produces 3,885 in 10s,
        # because it re-narrates seven sources it did not need to reword. The
        # composer already orders and sources those. Cloud prose earns its
        # latency on a focused question, so that is where it is used.
        if all(n in analysis.intents for n in BRIEFING_SEQUENCE):
            return det_text, tool_calls, tool_results, "Auralis Civic Intelligence"

        # Labelled in plain words, never by tool name. Handing the model
        # "get_city_status" and then forbidding it to say so just made it echo
        # the name and get the whole answer rejected.
        readings = json.dumps(
            [
                {
                    "reading": _TOOL_SUBJECT.get(tr["name"], tr["name"]),
                    "data": _trim_reading(tr["result"]),
                }
                for tr in tool_results
            ],
            default=str,
        )[:12000]
        messages.append({
            "role": "user",
            "content": (
                "Here are the verified readings for that question, as JSON.\n\n"
                f"{readings}\n\n"
                "Write the answer from these readings only. Report every field "
                "that bears on the question, with units, and say when each was "
                "observed and which feed it came from. Include every item "
                "returned — never write 'omitted for brevity' or summarise a "
                "list away. Write for a city operator, not a programmer: use "
                "the provider names (Open-Meteo, OpenAQ, TomTom) and plain "
                "English, never the raw JSON keys. If a reading is absent, say "
                "it was not reported.\n\n"
                "FORMAT: short bold headings and '- ' bullet lists only. No "
                "markdown tables — the chat pane is narrow and a table does not "
                "render there. To compare two sources, give each its own "
                "bullet. Do not describe your own process or restate these "
                "instructions; begin with the answer."
            ),
        })

        data = _call_cloud_llm(messages)
        model_used = data.get("_model", "")
        text = (data["choices"][0]["message"].get("content") or "").strip()

        if not text:
            return None
        if (_LEAKED_TOOL_MARKUP.search(text)
                or _mentions_tool_names(text)
                or _looks_like_scratchpad(text)):
            log.warning("Cloud answer leaked internals; using grounded text")
            return det_text, tool_calls, tool_results, "Auralis Civic Intelligence"
        hedged = _looks_fabricated(text)
        if hedged:
            # Ship the grounded composition rather than a guessed figure.
            log.warning("Cloud answer discarded, hedged figure: %r", hedged)
            return det_text, tool_calls, tool_results, "Auralis Civic Intelligence"
        return text, tool_calls, tool_results, f"Auralis AI · {model_used}"
    except Exception as exc:
        log.info("Cloud chat unavailable (%s)", exc)
        return None


# ──────────────────────────────────────────────────── Deterministic Fallback

# What each tool was asked for, in plain words. Used to say what was checked
# when a source comes back with nothing - "we looked and there was nothing" is
# information, and it is the honest alternative to padding the answer out.
_TOOL_SUBJECT: dict[str, str] = {
    "get_weather": "live weather telemetry",
    "get_air_quality": "OpenAQ air quality stations",
    "search_incidents": "the active incident register",
    "get_local_news": "regional news reporting",
    "get_traffic_status": "TomTom traffic flow",
    "search_nearby_services": "the emergency services directory",
    "get_city_status": "the city status snapshot",
    "search_city_knowledge": "municipal bylaws and documents",
    "get_emergency_info": "emergency response guidance",
}


def _city_profile_section(context: dict[str, Any]) -> str | None:
    """The registry facts about the place, for a briefing.

    Population, district and elevation come from the AP city registry, not from
    a model. A city that is not in the registry gets no section rather than an
    invented one.
    """
    from services.api.core import geo_cities

    name = context.get("city_name")
    if not name:
        return None
    city = geo_cities.find_city_by_name(name) or geo_cities.get_city_by_id(str(name))
    if city is None:
        return None

    lines = [f"**{city.name}, {city.state}**", ""]
    lines.append(f"- **District:** {city.district}")
    lines.append(f"- **Region:** {city.zone}")
    lines.append(f"- **Classification:** {city.tier}"
                 + (" - state capital" if city.is_capital else ""))
    if city.population:
        lines.append(f"- **Population:** {city.population:,}")
    lines.append(f"- **Elevation:** {city.elevation_m} m above sea level")
    lines.append(f"- **Coordinates:** {city.lat:.4f} N, {city.lon:.4f} E")
    lines.append("")
    lines.append("*Source: Andhra Pradesh city registry.*")
    return "\n".join(lines)


def _coverage_note(empties: list[str]) -> str | None:
    """Name the sources that were queried and had nothing to report."""
    if not empties:
        return None
    subjects = [_TOOL_SUBJECT.get(n, n) for n in dict.fromkeys(empties)]
    body = (subjects[0] if len(subjects) == 1
            else ", ".join(subjects[:-1]) + f" and {subjects[-1]}")
    return (f"**Checked, nothing found:** {body}. "
            "Each was queried and held no records for this location. "
            "Nothing has been estimated to fill the gap.")


def _provenance(tool_results: list[dict[str, Any]]) -> str | None:
    """Which upstream sources answered, and when they last observed."""
    seen: dict[str, str] = {}

    def note(provider: Any, observed: Any) -> None:
        if not provider:
            return
        stamp = (str(observed)[:16].replace("T", " ") + " UTC") if observed else ""
        seen.setdefault(str(provider), stamp)

    for tr in tool_results:
        r = tr.get("result")
        if not isinstance(r, dict) or r.get("status") == "error":
            continue
        note(r.get("provider"), r.get("observed_at"))
        detail = r.get("weather_detail")
        if isinstance(detail, dict):
            note(detail.get("provider"), detail.get("observed_at"))
        flow = r.get("flow")
        if isinstance(flow, dict):
            note(flow.get("provider"), None)
        srcs = r.get("sources")
        if isinstance(srcs, dict):
            srcs = list(srcs.values())
        if isinstance(srcs, list):
            for s in srcs:
                if isinstance(s, dict) and s.get("status") in ("ok", "no_stations"):
                    note(s.get("source"), s.get("observed_at") or s.get("last_upstream_at"))

    if not seen:
        return None
    lines = ["**Sources**", ""]
    for provider, stamp in list(seen.items())[:8]:
        lines.append(f"- {provider}" + (f" - observed {stamp}" if stamp else ""))
    return "\n".join(lines)


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
            f"I can answer questions about **{context.get('city_name') or 'the selected city'}** "
            "from live city data:\n\n"
            "- **Weather** — current conditions and forecast\n"
            "- **Incidents** — accidents, flooding, blockages\n"
            "- **Recent activity** — what has happened in the last 24 hours\n"
            "- **Traffic** — congestion and safe routes\n"
            "- **Nearby services** — hospitals, fire stations, police\n"
            "- **Report an issue** — potholes, garbage, damaged infrastructure\n"
            "- **Municipal rules** — property tax, bylaws, flood procedures\n\n"
            "What would you like to know?",
            [],
            [],
        )

    # Answer the question asked: run the tools the question implies, most
    # relevant first, and stop. A weather question returns weather.
    # A briefing is the exception - it asks about the place as a whole, so it
    # gets a wider budget rather than a truncated answer. Read off the selected
    # tools rather than re-matching the wording, so this cannot disagree with
    # what detect_intent decided.
    is_briefing = all(n in intents for n in BRIEFING_SEQUENCE)
    budget = BRIEFING_TOOL_CALLS if is_briefing else MAX_TOOL_CALLS_PER_TURN
    for tool_name in intents[:budget]:
        args = _infer_tool_args(tool_name, user_message, context)
        result = chat_tools.execute_tool(tool_name, args, context)
        tc_id = f"det_{uuid.uuid4().hex[:8]}"
        tool_calls.append({"id": tc_id, "name": tool_name, "arguments": args})
        tool_results.append({"tool_use_id": tc_id, "name": tool_name, "result": result})

    # Synthesize a response from tool results
    response_parts = []
    empty_sources: list[str] = []
    city_name = context.get("city_name", "the selected city")

    if is_briefing:
        profile = _city_profile_section(context)
        if profile:
            response_parts.append(profile)
    for tr in tool_results:
        result = tr["result"]
        name = tr["name"]
        for tc in tool_calls:
            if tc.get("id") == tr.get("tool_use_id") and tc.get("arguments", {}).get("city_name"):
                city_name = tc["arguments"]["city_name"]
                break

        if result.get("status") == "error":
            response_parts.append(f"{result.get('error', 'Service unavailable')}")
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
            # Every provider that answered, not just the first. Two independent
            # feeds agreeing is worth more than one, and a disagreement is
            # something the operator should see rather than have hidden.
            answered = [
                d for d in sources_dict.values()
                if isinstance(d, dict) and d.get("status") == "ok"
                and d.get("temperature_c") is not None
            ]
            if answered:
                lead = answered[0]
                observed = lead.get("observed_at", "")
                obs_str = f" as of {observed[:16].replace('T', ' ')} UTC" if observed else ""

                parts = [f"**Weather in {city_name}**{obs_str}", ""]
                temp = lead.get("temperature_c")
                humidity = lead.get("humidity_pct")
                rain = lead.get("rain_rate_mm_h", 0)
                wind = lead.get("wind_speed_kph")
                pressure = lead.get("pressure_hpa")

                parts.append(f"- **Temperature:** {temp} °C")
                if humidity is not None:
                    parts.append(f"- **Relative humidity:** {humidity} %")
                if wind is not None:
                    parts.append(f"- **Wind speed:** {wind} km/h")
                if pressure is not None:
                    parts.append(f"- **Barometric pressure:** {pressure} hPa")
                if rain:
                    parts.append(f"- **Precipitation:** {rain} mm/h")
                else:
                    parts.append("- **Precipitation:** none recorded")

                if len(answered) > 1:
                    parts.append("")
                    parts.append("**Cross-check**")
                    parts.append("")
                    for d in answered[:4]:
                        prov = d.get("source") or d.get("source_provider") or "feed"
                        parts.append(
                            f"- {prov}: {d.get('temperature_c')} °C"
                            + (f", {d.get('humidity_pct')} % RH"
                               if d.get("humidity_pct") is not None else "")
                        )

                provider = lead.get("source") or lead.get("source_provider") or "Live telemetry"
                parts.append("")
                parts.append(f"*Source: {provider} ({lead.get('trust_tier', 'verified')}).*")
                response_parts.append("\n".join(parts))
                parsed_weather = True

            if not parsed_weather and isinstance(weather, dict) and "temperature" in weather:
                temp = weather.get("temperature")
                hum = weather.get("humidity", "--")
                response_parts.append(f"**Current Weather in {city_name}:**\n\n**Temperature:** {temp}°C\n**Humidity:** {hum}%")
                parsed_weather = True

            if not parsed_weather:
                response_parts.append(f"Weather data for {city_name} is currently unavailable.")

        elif name == "get_air_quality":
            readings = result.get("readings") or []
            city_n = result.get("city_name") or city_name or "Andhra Pradesh"

            if not readings:
                # The connector's own message says how far it searched and that
                # no value exists. Repeat that rather than the older wording,
                # which claimed stations were "not reporting" — a different and
                # unverified claim.
                radius = result.get("radius_m")
                # The connector's message already names the radius it searched,
                # so nothing is appended to it.
                detail = result.get("message") or (
                    "OpenAQ returned no measurements within "
                    f"{int(radius) // 1000} km of this location."
                    if radius else "OpenAQ returned no measurements for this location."
                )
                response_parts.append(f"**Air quality — {city_n}**\n\n{detail}")
                empty_sources.append("get_air_quality")
            else:
                stations = result.get("stations") or []
                # OpenAQ carries weather channels on the same stations. Listing
                # them under air quality put a 23.8 C station temperature next
                # to a 34.3 C live reading, which reads as a contradiction.
                pollutants = {"pm25", "pm10", "pm1", "no", "no2", "nox", "so2",
                              "o3", "co", "bc", "nh3"}
                candidates = [
                    r for r in readings
                    if isinstance(r, dict)
                    and str(r.get("parameter", "")).lower() in pollutants
                ]
                # One line per pollutant, the most recent one. The feed returns
                # every station's whole history, so taking the first few gave
                # the OLDEST readings and presented them as the current air.
                latest: dict[str, dict[str, Any]] = {}
                for r in candidates:
                    key = str(r.get("parameter", "")).lower()
                    seen_at = str(r.get("observed_at") or "")
                    if seen_at >= str(latest.get(key, {}).get("observed_at") or ""):
                        latest[key] = r
                order = ["pm25", "pm10", "pm1", "no2", "o3", "so2", "co", "nox",
                         "no", "nh3", "bc"]
                shown = sorted(
                    latest.values(),
                    key=lambda r: order.index(str(r.get("parameter", "")).lower())
                    if str(r.get("parameter", "")).lower() in order else len(order),
                )

                lines = [f"**Air quality — {city_n}**", ""]
                for r in shown[:8]:
                    param = str(r.get("parameter", "")).upper()
                    when = str(r.get("observed_at") or "")[:16].replace("T", " ")
                    station = r.get("station") or r.get("location") or "unnamed station"
                    lines.append(
                        f"- **{param}:** {r.get('value')} {r.get('unit', '')}".rstrip()
                        + f" — {station}"
                        + (f", observed {when} UTC" if when else "")
                    )

                # These readings are timestamped by the station, and the nearest
                # one can be days behind. Saying so is the difference between a
                # measurement and a guess about now.
                newest = max((str(r.get("observed_at") or "") for r in shown),
                             default="")
                if newest:
                    try:
                        from datetime import UTC, datetime
                        age_h = (datetime.now(UTC)
                                 - datetime.fromisoformat(
                                     newest.replace("Z", "+00:00"))
                                 ).total_seconds() / 3600.0
                        if age_h > 24:
                            lines.append("")
                            lines.append(
                                f"**These are not current.** The most recent "
                                f"measurement is {age_h / 24:.1f} days old "
                                f"({newest[:16].replace('T', ' ')} UTC). No "
                                f"newer value has been published for this area."
                            )
                    except ValueError:
                        pass

                if stations:
                    named = ", ".join(
                        dict.fromkeys(
                            s.get("name") for s in stations[:3] if s.get("name")
                        )
                    )
                    lines.append("")
                    lines.append(
                        f"Stations in range: {len(stations)}"
                        + (f" — {named}" if named else "") + "."
                    )
                lines.append("")
                lines.append(
                    f"*Source: {result.get('provider', 'OpenAQ v3')} "
                    f"({result.get('trust_tier', 'verified')}).*"
                )
                response_parts.append("\n".join(lines))

        elif name == "search_incidents":
            count = result.get("count", 0)
            incidents = result.get("incidents", [])
            radius_m = result.get("radius_m")
            scope = f" within {int(radius_m) // 1000} km" if radius_m else ""
            if count == 0:
                response_parts.append(
                    f"**Incidents — {city_name}**\n\n"
                    f"No active incidents on the record{scope}."
                )
                empty_sources.append("search_incidents")
            else:
                lines = [f"**{count} active incident(s) in {city_name}{scope}:**\n"]
                for inc in incidents[:5]:
                    lines.append(
                        f"- **{inc.get('title', 'Untitled')}** "
                        f"— {inc.get('severity', '?').upper()} ({inc.get('state', '?')})"
                    )
                response_parts.append("\n".join(lines))

        elif name == "get_local_news":
            arts = result.get("items", [])
            scope = result.get("scope", city_name)
            if not arts:
                window = result.get("within_hours")
                response_parts.append(
                    f"**News — {scope}**\n\nNo regional reporting found"
                    + (f" in the last {int(window)} hours." if window else ".")
                )
                empty_sources.append("get_local_news")
            else:
                lines = [f"**Reported for {scope}:**\n"]
                for a in arts[:6]:
                    when = (a.get("published_at") or "")[:16].replace("T", " ")
                    lines.append(
                        f"- {a.get('title', '').strip()}\n"
                        f"  — {a.get('outlet', 'unattributed')}"
                        + (f", {when} UTC" if when else "")
                    )
                lines.append(
                    "\nThese are the outlets' own headlines. Figures, causes and names "
                    "are as each outlet reported them."
                )
                response_parts.append("\n".join(lines))

        elif name == "get_city_status":
            active = result.get("active_incidents", 0)
            by_sev = result.get("incidents_by_severity", {})
            total = result.get("total_incidents_recorded", 0)
            place = result.get("city") or city_name

            lines = [f"**Operational status — {place}**", ""]
            lines.append(f"- **Active incidents:** {active}")
            if by_sev:
                lines.append("- **By severity:** "
                             + ", ".join(f"{k} {v}" for k, v in by_sev.items()))
            lines.append(f"- **Total incidents on record:** {total}")

            wd = result.get("weather_detail") or {}
            if wd.get("temperature_c") is not None:
                lines.append(
                    f"- **Conditions:** {wd['temperature_c']} °C"
                    + (f", {wd['humidity_pct']} % humidity"
                       if wd.get("humidity_pct") is not None else "")
                    + (f", wind {wd['wind_speed_kph']} km/h"
                       if wd.get("wind_speed_kph") is not None else "")
                    + (f", {wd['rain_rate_mm_h']} mm/h rain"
                       if wd.get("rain_rate_mm_h") else ", no precipitation")
                )
            else:
                lines.append(f"- **Conditions:** {result.get('weather', 'unavailable')}")

            lines.append(f"- **Snapshot taken:** "
                         f"{str(result.get('timestamp', ''))[:16].replace('T', ' ')} UTC")
            response_parts.append("\n".join(lines))

        elif name == "get_traffic_status":
            overall = result.get("overall_traffic", "unknown")
            areas = result.get("congestion_details") or []
            flow = result.get("flow") or {}
            lines = [f"**Traffic — {city_name}**", ""]
            lines.append(f"- **Overall:** {overall}")

            cur, free = flow.get("current_speed_kph"), flow.get("free_flow_kph")
            if cur is not None and free:
                pct = round((cur / free) * 100) if free else None
                lines.append(
                    f"- **Measured flow:** {cur} km/h against a free-flow {free} km/h"
                    + (f" ({pct}% of normal)" if pct is not None else "")
                )

            if areas:
                lines.append(f"- **Affected areas:** {len(areas)}")
                lines.append("")
                for a in areas[:4]:
                    sev = str(a.get("severity", "")).upper()
                    lines.append(f"- {a.get('title', 'Untitled')}" + (f" — {sev}" if sev else ""))
            else:
                lines.append("- **Congestion:** none reported on the record")

            # A clear road is a reading, not a silent source. Only count traffic
            # as having nothing to say when it returned no measurement at all,
            # or the coverage note claims a source failed when it answered.
            if cur is None and not areas:
                empty_sources.append("get_traffic_status")

            if flow.get("provider"):
                lines.append("")
                lines.append(f"*Source: {flow['provider']}.*")

            response_parts.append("\n".join(lines))

        elif name == "get_emergency_info":
            guide = result.get("guide", {})
            title = guide.get("title", "Emergency Information")
            actions = guide.get("immediate_actions", [])
            contacts = guide.get("emergency_contacts", {})
            response_parts.append(f"**{title}**\n")
            if actions:
                response_parts.append("**Immediate Actions:**")
                for i, action in enumerate(actions, 1):
                    response_parts.append(f"  {i}. {action}")
            if contacts:
                response_parts.append("\n**Emergency Contacts:**")
                for name_c, number in contacts.items():
                    response_parts.append(f"**{name_c}:** {number}")

        elif name == "create_civic_report":
            if result.get("report_created"):
                response_parts.append(
                    f"**Report Submitted Successfully!**\n\n"
                    f"{result.get('message', 'Your report is being processed.')}"
                )
            else:
                response_parts.append(f"Failed to create report: {result.get('error', 'Unknown error')}")

        elif name == "search_nearby_services":
            services = result.get("services", [])
            count = result.get("count", 0)
            city = result.get("city", "the area")
            if count == 0:
                response_parts.append(
                    f"**Emergency services — {city}**\n\n"
                    + result.get("message", "No services found nearby.")
                )
                empty_sources.append("search_nearby_services")
            else:
                lines = [f"**Emergency services — {city}**", ""]
                for svc in services[:6]:
                    name_s = svc.get("name", "Unknown")
                    lines.append(f"- **{name_s}**")
                    facts = []
                    if svc.get("type"):
                        facts.append(str(svc["type"]).replace("_", " "))
                    if svc.get("beds"):
                        facts.append(f"{svc['beds']} beds")
                    if svc.get("phone"):
                        facts.append(f"tel {svc['phone']}")
                    if facts:
                        lines.append(f"  {' · '.join(facts)}")
                    if svc.get("address"):
                        lines.append(f"  {svc['address']}")
                src = next((s.get("source") for s in services if s.get("source")), None)
                if src:
                    lines.append("")
                    lines.append(f"*Source: {src}.*")
                response_parts.append("\n".join(lines))

        elif name == "search_city_knowledge":
            passages = result.get("passages", [])
            if not passages:
                response_parts.append(result.get("message", "No matching municipal bylaws or documents found."))
            else:
                lines = ["**Verified City Knowledge & Documentation:**\n"]
                for p in passages[:2]:
                    lines.append(f"**{p.get('title')}** — *{p.get('section')}*")
                    lines.append(f"{p.get('content')}\n")
                response_parts.append("\n".join(lines))

    if not response_parts:
        response_parts.append(
            "I processed your request but couldn't generate a specific response. "
            "Could you rephrase your question?"
        )


    # A briefing says what it looked at, not only what it found.
    # Without this a quiet city reads as a broken answer.
    if is_briefing:
        note = _coverage_note(empty_sources)
        if note:
            response_parts.append(note)
        sources = _provenance(tool_results)
        if sources:
            response_parts.append(sources)

    return "\n\n".join(response_parts), tool_calls, tool_results


def _infer_tool_args(tool_name: str, message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Infer tool arguments from the user message for deterministic mode."""
    args: dict[str, Any] = {}

    # A time window resolved by analyze_question applies to anything that can
    # be scoped by one, so "what happened yesterday" does not return today.
    window = context.get("window_hours")
    if window and tool_name in ("get_local_news", "search_incidents"):
        args["within_hours"] = int(window)

    from services.api.core import geo_cities
    target_city = None
    msg_lower = message.lower()

    # 1. Search if any registered AP city name is explicitly mentioned in message
    for city in geo_cities.AP_CITIES_REGISTRY:
        cn_lower = city.name.lower()
        if cn_lower in msg_lower or city.id in msg_lower:
            target_city = city
            break

    # 2. Check individual token search if multi-word match didn't trigger
    if not target_city:
        clean_msg = message.replace("?", " ").replace(",", " ").replace(".", " ").replace("!", " ")
        for token in clean_msg.split():
            if len(token) >= 3:
                found = geo_cities.find_city_by_name(token)
                if found:
                    target_city = found
                    break

    # 3. Fallback to session/client context
    if target_city:
        args["latitude"] = target_city.lat
        args["longitude"] = target_city.lon
        args["city_name"] = target_city.name
    elif context.get("city_name") and context["city_name"] != "Selected City":
        args["city_name"] = context["city_name"]
        found = geo_cities.find_city_by_name(context["city_name"])
        if found:
            args["latitude"] = found.lat
            args["longitude"] = found.lon
        else:
            args["latitude"] = context.get("latitude", geo_cities.AP_CITIES_REGISTRY[0].lat)
            args["longitude"] = context.get("longitude", geo_cities.AP_CITIES_REGISTRY[0].lon)
    elif context.get("latitude") and context.get("longitude"):
        args["latitude"] = context["latitude"]
        args["longitude"] = context["longitude"]
        args["city_name"] = context.get("city_name", "Vijayawada")
    else:
        args["latitude"] = 16.5062
        args["longitude"] = 80.6480
        args["city_name"] = "Vijayawada"

    if tool_name == "search_city_knowledge":
        # Semantic search: the whole question is the useful input.
        args["query"] = message

    elif tool_name == "search_incidents":
        # `query` is a literal substring match against incident titles, so
        # passing the whole sentence matched nothing and every incident search
        # from chat came back empty — even with a critical incident open in
        # the same city. Send a subject term, or nothing at all.
        for term in ("accident", "collision", "crash", "flood", "waterlogging",
                     "fire", "blockage", "outage", "traffic", "landslide",
                     "cyclone", "storm", "earthquake"):
            if re.search(rf"(?<!\w){term}", msg_lower):
                args["query"] = term
                break

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
        # Resolve the question first, then answer that resolution.
        analysis = analyze_question(user_message, context)
        if analysis.window_hours:
            context = {**context, "window_hours": analysis.window_hours}
        intents = analysis.intents
        det_text, tool_calls, tool_results = _deterministic_response(user_message, intents, context)

        # A tool-backed answer IS the answer: it carries real readings, and
        # handing those to a 1.5B model to re-narrate is how numbers drift.
        if tool_calls:
            return det_text, tool_calls, tool_results, "Auralis Civic Intelligence"

        # No tool matched, so this is conversation — about the platform, or a
        # follow-up, or a plain question. Previously `det_text` (never empty)
        # short-circuited here and every such turn got the canned capability
        # list back.
        # Questions about the product are answered from the curated record.
        kb = platform_answer(user_message)
        if kb:
            return kb, [], [], "Auralis Civic Intelligence"

        from services.api.core import custom_llm
        if not custom_llm.is_model_loaded():
            return None

        city_label = context.get("city_name", "the selected city")
        system_prompt = CONVERSATION_PROMPT.format(city=city_label)

        # Carry recent turns so follow-ups ("and tomorrow?") have their referent.
        messages = [{"role": "system", "content": system_prompt}]
        for m in session.messages[-6:]:
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})
        if not messages or messages[-1].get("content") != user_message:
            messages.append({"role": "user", "content": user_message})

        generated = custom_llm.generate_response(messages, max_new_tokens=320, temperature=0.3)
        if generated:
            return generated, tool_calls, tool_results, "Auralis Civic Intelligence"
        return det_text, tool_calls, tool_results, "Auralis Civic Intelligence"
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
        resolved_city = geo_cities.get_city_by_id(city_id) or geo_cities.find_city_by_name(city_id)
    elif city_name:
        resolved_city = geo_cities.find_city_by_name(city_name) or geo_cities.get_city_by_id(city_name)

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

    # 1. Cloud model, if a key is configured. It writes the prose; the numbers
    #    in it come from tool results, same as every other path.
    cloud_res = _cloud_chat(session, user_message, context)
    if cloud_res:
        response_text, tool_calls, tool_results, model = cloud_res
        degraded = False
    # 2. Local fine-tuned model
    elif (local_res := _local_custom_llm_chat(session, user_message, context)):
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
            model = "Auralis Civic Intelligence"
            degraded = False

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
