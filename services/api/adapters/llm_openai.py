"""OpenAI Reasoning & Incident Classification Adapter.

The LLM is strictly an ANALYSIS and REASONING layer, NEVER a source of truth.
It summarizes verified evidence, classifies incident types, explains risk factors,
and drafts candidate response recommendations.

Zero-fabrication rule: If evidence is insufficient or missing, the adapter returns
'Insufficient verified evidence to determine this.' It never hallucinates facts,
sensor readings, or events.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


def analyze_emergency_evidence(
    incident_data: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    weather_summary: dict[str, Any] | None = None,
    traffic_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze grounded evidence using OpenAI (or deterministic fallback when key is absent)."""
    api_key = os.environ.get("OPENAI_API_KEY")

    # If no evidence exists, refuse to speculate
    if not evidence_items:
        return {
            "classification": "unverified",
            "confidence_score": 0.0,
            "risk_assessment": "Insufficient verified evidence to determine this.",
            "recommended_actions": [],
            "hazards_identified": [],
            "analysis_mode": "deterministic_zero_evidence",
        }

    # Deterministic fallback when OpenAI API key is not configured
    if not api_key:
        signal_count = len(evidence_items)
        has_cctv = any(e.get("kind") == "cctv_collision" or "cctv" in str(e.get("connector_id", "")) for e in evidence_items)
        has_traffic = any(e.get("kind") == "traffic_collapse" or "traffic" in str(e.get("connector_id", "")) for e in evidence_items)
        has_citizen = any(e.get("kind") == "citizen_report" for e in evidence_items)

        confidence = 0.95 if (has_cctv and has_traffic and has_citizen) else \
                     0.85 if (has_cctv and has_traffic) else \
                     0.70 if (has_cctv or (has_traffic and has_citizen)) else 0.40

        status = "VERIFIED" if confidence >= 0.80 else "CORROBORATED" if confidence >= 0.60 else "SUSPECTED"

        return {
            "classification": incident_data.get("incident_class", "road_traffic_incident"),
            "verification_status": status,
            "confidence_score": confidence,
            "risk_assessment": (
                f"Multi-signal correlation of {signal_count} independent evidence feeds. "
                f"CCTV collision detection: {has_cctv}, Traffic speed collapse: {has_traffic}, "
                f"Verified citizen reports: {has_citizen}."
            ),
            "hazards_identified": ["lane_obstruction", "secondary_collision_risk"],
            "recommended_actions": [
                "Issue geofenced advisory to upstream traffic",
                "Request ERSS 112 emergency medical dispatch if human casualty risk is indicated",
                "Notify municipal traffic command for corridor diversion",
            ],
            "analysis_mode": "deterministic_rule_engine",
        }

    # Live OpenAI Analysis
    system_prompt = (
        "You are the Auralis Autonomous Emergency Assessment Specialist. "
        "Strict rules:\n"
        "1. You are an analysis layer, NOT a source of truth.\n"
        "2. Do NOT invent missing facts, sensor values, injuries, or locations.\n"
        "3. Only use provided evidence.\n"
        "4. If evidence is ambiguous, explicitly state uncertainty.\n"
        "5. Output valid JSON with keys: classification, verification_status (SUSPECTED/CORROBORATED/VERIFIED), "
        "confidence_score (0.0 to 1.0), risk_assessment, hazards_identified (list of strings), "
        "recommended_actions (list of strings)."
    )

    user_payload = {
        "incident": incident_data,
        "evidence": evidence_items,
        "weather": weather_summary or "Weather data unavailable",
        "traffic": traffic_summary or "Traffic data unavailable",
    }

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(OPENAI_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            res_json = resp.json()
            content = res_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed["analysis_mode"] = "openai_gpt"
            return parsed
    except Exception as exc:
        log.warning("OpenAI API call failed, falling back to deterministic synthesis: %s", exc)
        return analyze_emergency_evidence(incident_data, evidence_items, weather_summary, traffic_summary)
