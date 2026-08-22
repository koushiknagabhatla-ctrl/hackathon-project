"""GDELT (Global Database of Events, Language, and Tone) Intelligence Connector.

Queries real-time civic, hazard, infrastructure, and emergency event data
for Vijayawada, Andhra Pradesh, and regional urban sectors.

Uses GDELT Doc 2.0 API and GDELT Cloud Intelligence endpoints to monitor:
  - Natural hazards (floods, cyclones, heatwaves, extreme rain)
  - Civic infrastructure incidents (power outages, road blockages, structural failures)
  - Public safety and emergency news alerts
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from services.api.connectors import registry
from services.api.core import ingest
from services.api.models import EventIn

log = logging.getLogger("auralis.connectors.gdelt")

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_GEO_API = "https://api.gdeltproject.org/api/v2/geo/geo"

DEFAULT_LOCATION = "Vijayawada"
DEFAULT_STATE = "Andhra Pradesh"
DEFAULT_LAT = registry.JURISDICTION_LAT
DEFAULT_LON = registry.JURISDICTION_LON


def get_gdelt_api_key() -> str | None:
    return os.environ.get("GDELT_API_KEY")


def fetch_gdelt_civic_events(
    query_topic: str = "flood OR rain OR accident OR traffic OR infrastructure OR emergency",
    location: str = "Vijayawada OR \"Andhra Pradesh\"",
    max_records: int = 15,
    timespan: str = "7d",
) -> dict[str, Any]:
    """Fetch real-time civic news and emergency events from GDELT."""
    api_key = get_gdelt_api_key()

    search_query = f"({query_topic}) ({location})"
    params = {
        "query": search_query,
        "mode": "artlist",
        "maxrecords": str(max_records),
        "timespan": timespan,
        "format": "json",
        "sort": "DateDesc",
    }

    headers: dict[str, str] = {
        "User-Agent": "Auralis-Civic-Intelligence/1.0",
    }
    if api_key:
        headers["X-API-Key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.get(GDELT_DOC_API, params=params, headers=headers)
            if resp.status_code != 200:
                log.warning("GDELT API returned status %d: %s", resp.status_code, resp.text[:200])
                return {
                    "status": "unavailable",
                    "source": "GDELT Doc API v2",
                    "error": f"HTTP {resp.status_code}",
                    "articles": [],
                }

            data = resp.json()
            articles = data.get("articles", [])
            processed = []
            for art in articles:
                processed.append({
                    "title": art.get("title", "Untitled Event"),
                    "url": art.get("url", ""),
                    "source": art.get("domain", art.get("sourcecountry", "GDELT")),
                    "seendate": art.get("seendate", ""),
                    "language": art.get("language", "English"),
                    "tone": art.get("tone", 0.0),
                    "socialimage": art.get("socialimage", ""),
                })

            return {
                "status": "ok",
                "source": "GDELT Global Intelligence",
                "query": search_query,
                "count": len(processed),
                "articles": processed,
                "queried_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
    except Exception as exc:
        log.warning("GDELT fetch failed: %s", exc)
        return {
            "status": "unavailable",
            "source": "GDELT Global Intelligence",
            "error": str(exc),
            "articles": [],
        }


def ingest_gdelt_feed(principal: str = "p_operator") -> dict[str, Any]:
    """Ingest current GDELT regional alerts into the Auralis event & evidence ledger."""
    res = fetch_gdelt_civic_events()
    if res.get("status") != "ok" or not res.get("articles"):
        return {"ingested": 0, "status": res.get("status", "unavailable")}

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ingested_count = 0

    for art in res["articles"][:5]:
        event_body = {
            "title": art["title"],
            "url": art["url"],
            "source": art["source"],
            "published_at": art.get("seendate", now_iso),
            "tone": art.get("tone", 0.0),
            "channel": "gdelt_news_stream",
        }

        try:
            event = EventIn(
                connector_id="conn_gdelt",
                kind="civic_alert",
                event_time=now_iso,
                payload=event_body,
                geometry={"type": "Point", "coordinates": [DEFAULT_LON, DEFAULT_LAT]},
            )
            # News is a report ABOUT an event, never an observation of one.
            accepted = ingest.ingest_event(event, "p_operator", evidence_class="derived")
            if accepted.accepted and not accepted.deduplicated:
                ingested_count += 1
        except Exception as exc:
            log.warning("GDELT item ingest skipped: %s", exc)

    return {
        "ingested": ingested_count,
        "total_articles": len(res["articles"]),
        "status": "ok",
        "latest_headline": res["articles"][0]["title"] if res["articles"] else None,
    }
