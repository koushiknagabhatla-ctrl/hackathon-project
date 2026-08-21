"""Chat-callable tool wrappers that bridge the LLM tool-calling interface
to existing Auralis services.

Each tool:
  - Has a typed schema for the LLM to fill
  - Validates inputs
  - Calls the real service
  - Returns structured results the LLM can narrate

No tool invents data. If a service is unavailable, the tool returns an
explicit error result the LLM must communicate honestly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("auralis.chat.tools")

# ──────────────────────────────────────────────────── Tool Definitions
# Each definition is a dict the LLM sees as a function it can call.
# `handler` is the Python callable the orchestrator dispatches to.

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_weather",
        "description": (
            "Get current live weather conditions for a location. "
            "Returns temperature, humidity, wind, rain, and weather description."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Latitude of the location"},
                "longitude": {"type": "number", "description": "Longitude of the location"},
            },
            "required": [],
        },
    },
    {
        "name": "search_incidents",
        "description": (
            "Search for active incidents (accidents, floods, road blockages, etc.) "
            "near a location or matching a query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text (e.g. 'accidents', 'flooding')"},
                "latitude": {"type": "number", "description": "Center latitude for proximity search"},
                "longitude": {"type": "number", "description": "Center longitude for proximity search"},
                "radius_m": {"type": "number", "description": "Search radius in meters (default 5000)"},
                "state": {"type": "string", "description": "Filter by state: detected, assessing, closed, etc."},
            },
            "required": [],
        },
    },
    {
        "name": "get_incident_details",
        "description": "Get full details of a specific incident including evidence, claims, and timeline.",
        "parameters": {
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "The incident ID (e.g. inc_abc123)"},
            },
            "required": ["incident_id"],
        },
    },
    {
        "name": "create_civic_report",
        "description": (
            "Create a new civic issue report from a citizen. "
            "Reports things like potholes, garbage, broken streetlights, flooding, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue_type": {
                    "type": "string",
                    "description": "Type of issue",
                    "enum": [
                        "pothole", "garbage", "flooding", "waterlogging",
                        "road_blockage", "broken_streetlight", "water_problem",
                        "infrastructure_damage", "traffic_problem", "fire",
                        "accident", "public_safety", "other",
                    ],
                },
                "description": {"type": "string", "description": "Description of the issue"},
                "latitude": {"type": "number", "description": "Location latitude"},
                "longitude": {"type": "number", "description": "Location longitude"},
                "severity": {
                    "type": "string",
                    "description": "Severity level",
                    "enum": ["low", "medium", "high", "critical"],
                },
            },
            "required": ["issue_type", "description"],
        },
    },
    {
        "name": "get_city_status",
        "description": (
            "Get the current overall city status: active incident count, "
            "weather summary, system health, and operational metrics."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_nearby_services",
        "description": (
            "Find nearby public services and facilities like hospitals, "
            "fire stations, police stations, schools, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_type": {
                    "type": "string",
                    "description": "Type of service to search for",
                    "enum": [
                        "hospital", "fire_station", "police_station",
                        "school", "pharmacy", "gas_station", "atm",
                    ],
                },
                "latitude": {"type": "number", "description": "Search center latitude"},
                "longitude": {"type": "number", "description": "Search center longitude"},
                "radius_m": {"type": "number", "description": "Search radius in meters (default 3000)"},
            },
            "required": ["service_type"],
        },
    },
    {
        "name": "get_emergency_info",
        "description": (
            "Get emergency preparedness information and guidance for a specific "
            "type of emergency (flooding, earthquake, fire, accident, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emergency_type": {
                    "type": "string",
                    "description": "Type of emergency",
                    "enum": [
                        "flooding", "earthquake", "fire", "cyclone",
                        "accident", "chemical_spill", "heatwave", "general",
                    ],
                },
            },
            "required": ["emergency_type"],
        },
    },
    {
        "name": "get_traffic_status",
        "description": (
            "Get current traffic conditions for a location or road segment. "
            "Shows congestion levels and affected roads."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Location latitude"},
                "longitude": {"type": "number", "description": "Location longitude"},
            },
            "required": [],
        },
    },
    {
        "name": "search_city_knowledge",
        "description": (
            "Search verified city knowledge, municipal bylaws, flood SOPs, "
            "property tax payment guidelines, citizen charters, and emergency protocols."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The civic question or topic to search"},
                "category": {
                    "type": "string",
                    "description": "Optional category filter",
                    "enum": [
                        "disaster_management",
                        "municipal_services",
                        "civic_bylaws",
                        "emergency_directory",
                        "traffic_infrastructure",
                    ],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_safe_route",
        "description": (
            "Calculate an optimal driving route between two points with dynamic hazard avoidance "
            "(avoiding active floods, road blockages, and accidents)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origin_lat": {"type": "number", "description": "Origin latitude"},
                "origin_lon": {"type": "number", "description": "Origin longitude"},
                "dest_lat": {"type": "number", "description": "Destination latitude"},
                "dest_lon": {"type": "number", "description": "Destination longitude"},
                "avoid_hazards": {"type": "boolean", "description": "Avoid known hazards (default true)"},
            },
            "required": ["origin_lat", "origin_lon", "dest_lat", "dest_lon"],
        },
    },
]


# ──────────────────────────────────────────────────── Tool Handlers

DEFAULT_LAT = 16.5062  # Vijayawada
DEFAULT_LON = 80.6480


def handle_get_weather(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Fetch live weather from the weather connector."""
    lat = args.get("latitude", context.get("latitude", DEFAULT_LAT))
    lon = args.get("longitude", context.get("longitude", DEFAULT_LON))
    try:
        from services.api.connectors.weather import fetch_live_weather
        result = fetch_live_weather(lat=lat, lon=lon, principal="p_operator")
        return {"status": "ok", "weather": result}
    except Exception as exc:
        log.warning("Weather tool failed: %s", exc)
        return {"status": "error", "error": f"Weather service unavailable: {exc}"}


def handle_search_incidents(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Search active incidents from the repo."""
    from services.api.core import db, repo

    tenant_id = context.get("tenant_id", "ten_vijayawada")
    state = args.get("state")
    try:
        incidents = repo.list_incidents(tenant_id, state=state, limit=20)
        results = []
        for inc in incidents:
            item = {
                "id": inc.id,
                "title": inc.title,
                "type": inc.incident_class,
                "severity": inc.severity,
                "state": inc.state,
                "opened_at": inc.opened_at,
            }
            if inc.geometry:
                item["location"] = inc.geometry.get("coordinates")
            results.append(item)

        # Filter by proximity if lat/lon provided
        lat = args.get("latitude")
        lon = args.get("longitude")
        radius = args.get("radius_m", 5000)
        if lat is not None and lon is not None:
            import math
            def _dist(coords: list) -> float:
                if not coords or len(coords) < 2:
                    return float("inf")
                R = 6371000.0
                p1, p2 = math.radians(lat), math.radians(coords[1])
                dp = math.radians(coords[1] - lat)
                dl = math.radians(coords[0] - lon)
                a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
                return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

            results = [
                r for r in results
                if r.get("location") and _dist(r["location"]) <= radius
            ]

        # Filter by query text if provided
        query = args.get("query", "").lower()
        if query:
            results = [
                r for r in results
                if query in r.get("title", "").lower()
                or query in r.get("type", "").lower()
                or query in r.get("severity", "").lower()
            ]

        return {
            "status": "ok",
            "count": len(results),
            "incidents": results[:10],
        }
    except Exception as exc:
        log.warning("Incident search failed: %s", exc)
        return {"status": "error", "error": f"Incident search failed: {exc}"}


def handle_get_incident_details(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Get detailed incident information."""
    from services.api.core import repo

    incident_id = args.get("incident_id")
    if not incident_id:
        return {"status": "error", "error": "incident_id is required"}

    tenant_id = context.get("tenant_id", "ten_vijayawada")
    try:
        detail = repo.incident_detail(incident_id)
        if detail is None:
            return {"status": "error", "error": f"Incident {incident_id} not found"}

        return {
            "status": "ok",
            "incident": {
                "id": detail.incident.id,
                "title": detail.incident.title,
                "type": detail.incident.incident_class,
                "severity": detail.incident.severity,
                "state": detail.incident.state,
                "opened_at": detail.incident.opened_at,
                "closed_at": detail.incident.closed_at,
                "location": detail.incident.geometry,
                "detector": detail.incident.detector,
            },
            "evidence_count": len(detail.evidence),
            "evidence_summary": [
                {"id": e.id, "source": e.source, "trust_tier": e.trust_tier, "statement": e.statement}
                for e in detail.evidence[:5]
            ],
            "claims_count": len(detail.claims),
            "conflicts_count": len(detail.conflicts),
            "forecasts_count": len(detail.forecasts),
        }
    except Exception as exc:
        log.warning("Incident detail failed: %s", exc)
        return {"status": "error", "error": f"Failed to fetch incident details: {exc}"}


def handle_create_civic_report(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Create a civic issue report via the ingest pipeline."""
    from services.api.core import ingest
    from services.api.models import EventIn

    issue_type = args.get("issue_type", "other")
    description = args.get("description", "")
    lat = args.get("latitude", context.get("latitude", DEFAULT_LAT))
    lon = args.get("longitude", context.get("longitude", DEFAULT_LON))
    severity = args.get("severity", "medium")

    try:
        now = datetime.now(UTC).isoformat()
        event = EventIn(
            connector_id="conn_open311",
            kind="civic_report",
            event_time=now,
            payload={
                "issue_type": issue_type,
                "description": description,
                "severity": severity,
                "channel": "auralis_chat",
                "report_text": description,
            },
            geometry={"type": "Point", "coordinates": [lon, lat]},
        )
        result = ingest.ingest_event(event, "p_operator")
        return {
            "status": "ok",
            "report_created": True,
            "event_id": result.id,
            "evidence_id": result.evidence_id,
            "incident_id": result.incident_id,
            "message": f"Your {issue_type.replace('_', ' ')} report has been submitted and is being processed.",
        }
    except Exception as exc:
        log.warning("Civic report creation failed: %s", exc)
        return {"status": "error", "error": f"Failed to create report: {exc}"}


def handle_get_city_status(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Get overall city operational status."""
    from services.api.core import db, repo

    tenant_id = context.get("tenant_id", "ten_vijayawada")
    try:
        # Count active incidents by severity
        incidents = repo.list_incidents(tenant_id, limit=200)
        active = [i for i in incidents if i.state != "closed"]
        by_severity = {}
        for inc in active:
            by_severity[inc.severity] = by_severity.get(inc.severity, 0) + 1

        # Get weather summary
        weather_summary = "unavailable"
        try:
            from services.api.connectors.weather import fetch_live_weather
            w = fetch_live_weather(lat=DEFAULT_LAT, lon=DEFAULT_LON, principal="p_operator")
            sources = w.get("sources", {})
            for src_name, src_data in sources.items():
                if src_data.get("status") == "ok":
                    obs = src_data.get("observations", {})
                    temp = obs.get("temperature_2m", {}).get("value")
                    rain = obs.get("precipitation", {}).get("value", 0)
                    weather_summary = f"{temp}°C" if temp is not None else "available"
                    if rain and rain > 0:
                        weather_summary += f", {rain}mm rain"
                    break
        except Exception:
            pass

        return {
            "status": "ok",
            "city": "Vijayawada",
            "active_incidents": len(active),
            "incidents_by_severity": by_severity,
            "total_incidents_recorded": len(incidents),
            "weather": weather_summary,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:
        log.warning("City status failed: %s", exc)
        return {"status": "error", "error": f"City status unavailable: {exc}"}


def handle_search_nearby_services(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Search for nearby services using the digital twin asset data."""
    from services.api.core import db

    service_type = args.get("service_type", "hospital")
    lat = args.get("latitude", context.get("latitude", DEFAULT_LAT))
    lon = args.get("longitude", context.get("longitude", DEFAULT_LON))

    # Map user-friendly types to asset kinds in the twin
    kind_map = {
        "hospital": ("hospital", "medical"),
        "fire_station": ("fire_station",),
        "police_station": ("police_station",),
        "school": ("school",),
        "pharmacy": ("pharmacy",),
        "gas_station": ("fuel_station",),
        "atm": ("atm",),
    }
    kinds = kind_map.get(service_type, (service_type,))

    try:
        results = []
        for kind in kinds:
            rows = db.q(
                "SELECT id, name, kind, geometry FROM asset WHERE kind=? LIMIT 20",
                kind,
            )
            for r in rows:
                from services.api.core.db import jload
                geom = jload(r["geometry"], {})
                results.append({
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["kind"],
                    "location": geom.get("coordinates"),
                })

        if not results:
            return {
                "status": "ok",
                "count": 0,
                "services": [],
                "message": f"No {service_type.replace('_', ' ')}s found in the city database. "
                           "Try searching for hospitals, fire stations, or police stations.",
            }

        return {
            "status": "ok",
            "count": len(results),
            "services": results[:10],
        }
    except Exception as exc:
        log.warning("Service search failed: %s", exc)
        return {"status": "error", "error": f"Service search failed: {exc}"}


def handle_get_emergency_info(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Return curated emergency preparedness guidance."""
    emergency_type = args.get("emergency_type", "general")

    # Curated, verified emergency information (not LLM-generated)
    EMERGENCY_GUIDES: dict[str, dict[str, Any]] = {
        "flooding": {
            "title": "Flood Emergency Preparedness",
            "immediate_actions": [
                "Move to higher ground immediately if water is rising",
                "Do not walk, swim, or drive through flood waters",
                "Stay away from power lines and electrical wires",
                "If trapped, go to the highest level of the building",
                "Signal for help and call emergency services (112)",
            ],
            "preparation": [
                "Keep emergency supplies: water, food, flashlight, first aid kit",
                "Know your evacuation routes",
                "Keep important documents in waterproof containers",
                "Charge your phone and keep a portable charger ready",
            ],
            "emergency_contacts": {
                "NDRF": "011-26107953",
                "Emergency": "112",
                "Flood Helpline": "1070",
            },
        },
        "earthquake": {
            "title": "Earthquake Safety Guide",
            "immediate_actions": [
                "DROP, COVER, and HOLD ON",
                "If indoors, stay away from windows, heavy furniture, and fixtures",
                "If outdoors, move to an open area away from buildings",
                "If driving, pull over to the side of the road",
                "After shaking stops, check for injuries and damage",
            ],
            "preparation": [
                "Secure heavy items that could fall",
                "Practice earthquake drills",
                "Keep emergency supplies ready",
                "Identify safe spots in each room",
            ],
            "emergency_contacts": {"Emergency": "112", "NDMA": "011-26701728"},
        },
        "fire": {
            "title": "Fire Emergency Guide",
            "immediate_actions": [
                "Call 101 (Fire) or 112 immediately",
                "Alert everyone in the building",
                "Use stairs, never elevators",
                "Stay low to avoid smoke inhalation",
                "If clothes catch fire: STOP, DROP, and ROLL",
                "Do not re-enter the building",
            ],
            "preparation": [
                "Install and maintain smoke detectors",
                "Keep fire extinguishers accessible",
                "Plan and practice escape routes",
                "Never leave cooking unattended",
            ],
            "emergency_contacts": {"Fire Service": "101", "Emergency": "112"},
        },
        "cyclone": {
            "title": "Cyclone Preparedness Guide",
            "immediate_actions": [
                "Stay indoors and away from windows",
                "Listen to official weather updates",
                "If asked to evacuate, do so immediately",
                "Turn off gas, electricity, and water mains",
                "Store drinking water and food supplies",
            ],
            "preparation": [
                "Secure loose outdoor items",
                "Reinforce windows and doors",
                "Prepare an emergency kit",
                "Know the nearest cyclone shelter",
            ],
            "emergency_contacts": {"Emergency": "112", "IMD Cyclone Warning": "1800-180-1717"},
        },
        "accident": {
            "title": "Road Accident Response Guide",
            "immediate_actions": [
                "Call 112 for emergency services",
                "Do not move injured persons unless in immediate danger",
                "Turn on hazard lights and set up warning triangles",
                "Provide first aid if trained",
                "Note vehicle numbers and take photos for evidence",
            ],
            "emergency_contacts": {"Emergency": "112", "Ambulance": "108", "Police": "100"},
        },
        "chemical_spill": {
            "title": "Chemical Spill Emergency Guide",
            "immediate_actions": [
                "Evacuate the area immediately",
                "Move upwind from the spill",
                "Do not touch or inhale fumes",
                "Call emergency services (112)",
                "Remove contaminated clothing",
            ],
            "emergency_contacts": {"Emergency": "112", "Poison Control": "1800-599-2711"},
        },
        "heatwave": {
            "title": "Heatwave Safety Guide",
            "immediate_actions": [
                "Stay indoors during peak heat (12 PM - 3 PM)",
                "Drink plenty of water frequently",
                "Wear light, loose-fitting clothing",
                "Never leave children or pets in parked vehicles",
                "Seek medical help if experiencing heatstroke symptoms",
            ],
            "emergency_contacts": {"Emergency": "112", "Ambulance": "108"},
        },
        "general": {
            "title": "General Emergency Preparedness",
            "immediate_actions": [
                "Stay calm and assess the situation",
                "Call emergency services (112)",
                "Follow official instructions and announcements",
                "Help others if safe to do so",
            ],
            "emergency_contacts": {
                "Emergency": "112",
                "Police": "100",
                "Fire": "101",
                "Ambulance": "108",
                "Disaster Helpline": "1070",
                "Women Helpline": "1091",
            },
        },
    }

    guide = EMERGENCY_GUIDES.get(emergency_type, EMERGENCY_GUIDES["general"])
    return {"status": "ok", "emergency_type": emergency_type, "guide": guide}


def handle_get_traffic_status(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Get current traffic conditions from incident data."""
    from services.api.core import db, repo

    tenant_id = context.get("tenant_id", "ten_vijayawada")
    try:
        # Get traffic-related incidents
        incidents = repo.list_incidents(tenant_id, limit=50)
        traffic_incidents = [
            i for i in incidents
            if i.state != "closed"
            and i.incident_class in (
                "traffic_flow", "traffic_emergency", "road_traffic_incident",
                "accident", "road_blockage",
            )
        ]

        congestion_areas = []
        for inc in traffic_incidents:
            area = {
                "incident_id": inc.id,
                "type": inc.incident_class,
                "severity": inc.severity,
                "title": inc.title,
            }
            if inc.geometry:
                area["location"] = inc.geometry.get("coordinates")
            congestion_areas.append(area)

        overall = "clear"
        if len(traffic_incidents) > 5:
            overall = "heavy"
        elif len(traffic_incidents) > 2:
            overall = "moderate"
        elif len(traffic_incidents) > 0:
            overall = "light"

        return {
            "status": "ok",
            "overall_traffic": overall,
            "affected_areas": len(congestion_areas),
            "congestion_details": congestion_areas[:10],
        }
    except Exception as exc:
        log.warning("Traffic status failed: %s", exc)
        return {"status": "error", "error": f"Traffic status unavailable: {exc}"}


def handle_search_city_knowledge(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Search verified city knowledge using the RAG semantic retrieval engine."""
    from services.api.core import rag

    query = args.get("query", "")
    if not query:
        return {"status": "error", "error": "Search query is required"}

    category = args.get("category")
    try:
        results = rag.search_knowledge(query, top_k=3, category_filter=category)
        if not results:
            return {
                "status": "ok",
                "count": 0,
                "passages": [],
                "message": "No specific city bylaws or documentation matched this query.",
            }

        passages = []
        for r in results:
            passages.append({
                "title": r.chunk.title,
                "section": r.chunk.section,
                "category": r.chunk.category,
                "content": r.chunk.content,
                "score": r.score,
                "citation": f"{r.chunk.title} > {r.chunk.section}",
            })

        return {
            "status": "ok",
            "count": len(passages),
            "passages": passages,
        }
    except Exception as exc:
        log.warning("RAG knowledge search failed: %s", exc)
        return {"status": "error", "error": f"City knowledge search failed: {exc}"}


def handle_get_safe_route(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Calculate safe driving route with dynamic hazard avoidance."""
    from services.api.connectors import routing

    origin_lat = args.get("origin_lat", context.get("latitude", DEFAULT_LAT))
    origin_lon = args.get("origin_lon", context.get("longitude", DEFAULT_LON))
    dest_lat = args.get("dest_lat", 16.5180)  # Default: Vijayawada Rly Station
    dest_lon = args.get("dest_lon", 80.6200)
    avoid_hazards = args.get("avoid_hazards", True)
    tenant_id = context.get("tenant_id", "ten_vijayawada")

    try:
        route = routing.calculate_safe_route(
            origin=(float(origin_lat), float(origin_lon)),
            dest=(float(dest_lat), float(dest_lon)),
            avoid_hazards=bool(avoid_hazards),
            tenant_id=tenant_id,
        )
        return {
            "status": "ok",
            "distance_km": route.distance_km,
            "duration_min": route.duration_min,
            "hazard_avoidance": route.hazard_avoidance,
            "hazards_avoided_count": len(route.hazards_avoided),
            "hazards_avoided": [h.get("title", h.get("type", "Hazard")) for h in route.hazards_avoided],
            "risk_level": route.risk_level,
            "steps_count": len(route.steps),
            "first_few_steps": [s.instruction for s in route.steps[:3]],
        }
    except Exception as exc:
        log.warning("Route tool failed: %s", exc)
        return {"status": "error", "error": f"Safe route calculation failed: {exc}"}


# ──────────────────────────────────────────────────── Handler Registry

TOOL_HANDLERS: dict[str, Any] = {
    "get_weather": handle_get_weather,
    "search_incidents": handle_search_incidents,
    "get_incident_details": handle_get_incident_details,
    "create_civic_report": handle_create_civic_report,
    "get_city_status": handle_get_city_status,
    "search_nearby_services": handle_search_nearby_services,
    "get_emergency_info": handle_get_emergency_info,
    "get_traffic_status": handle_get_traffic_status,
    "search_city_knowledge": handle_search_city_knowledge,
    "get_safe_route": handle_get_safe_route,
}


def execute_tool(tool_name: str, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name. Returns structured result or error."""
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"status": "error", "error": f"Unknown tool: {tool_name}"}
    try:
        return handler(args, context)
    except Exception as exc:
        log.exception("Tool execution failed: %s", tool_name)
        return {"status": "error", "error": f"Tool {tool_name} failed: {exc}"}
