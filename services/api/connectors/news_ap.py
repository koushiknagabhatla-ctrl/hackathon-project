"""Andhra Pradesh news retrieval. Google News RSS (no key) + GDELT as backup.

Retrieval only: headlines are returned verbatim with outlet and timestamp.
Casualty figures, causes and names are the outlet's words, never derived here.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from services.api.connectors import registry

log = logging.getLogger("auralis.connectors.news_ap")

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

# Every query is pinned to the state so the feed cannot drift to another
# region that happens to share a city name (there is a Rajahmundry in fiction
# and a Guntur in none, but "Palamaner" and "Nagari" are not unique globally).
STATE_ANCHOR = "Andhra Pradesh"

# Topic vocabularies. Kept explicit rather than free-text so the caller cannot
# accidentally ask the index a leading question.
TOPICS: dict[str, str] = {
    "incidents": "accident OR crash OR collision OR mishap OR killed OR injured",
    "disaster": "flood OR cyclone OR landslide OR earthquake OR fire OR rescue",
    "civic": "municipal OR corporation OR civic OR water supply OR power cut OR road works",
    "traffic": "traffic OR highway OR roadblock OR diversion OR congestion",
    "health": "hospital OR outbreak OR dengue OR disease OR health department",
    "all": "",
}

CACHE_TTL_S = 300  # news moves, but not every second; five minutes is honest


@dataclass
class NewsItem:
    title: str
    outlet: str
    published_at: str | None
    url: str
    query_topic: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    # RSS titles arrive as "Headline text - Outlet Name"
    return re.sub(r"\s+", " ", text).strip()


def _split_outlet(title: str, rss_source: str) -> tuple[str, str]:
    """Google News appends ' - Outlet' to the headline. Separate them.

    The <source> element is authoritative when present; the suffix is only used
    to trim the headline, never to invent an outlet name.
    """
    outlet = _clean(rss_source)
    if outlet and title.endswith(f" - {outlet}"):
        return title[: -(len(outlet) + 3)].strip(), outlet
    m = re.match(r"^(.*) - ([^-]{2,40})$", title)
    if m:
        return m.group(1).strip(), outlet or m.group(2).strip()
    return title, outlet


def _parse_pubdate(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(UTC).isoformat()
    except Exception:
        return None


def _google_news(query: str, topic: str, limit: int, scan: int = 80) -> list[NewsItem]:
    url = (
        f"{GOOGLE_NEWS_RSS}?q={urllib.parse.quote(query)}"
        "&hl=en-IN&gl=IN&ceid=IN:en"
    )
    with httpx.Client(timeout=25, follow_redirects=True,
                      headers={"User-Agent": registry.USER_AGENT}) as c:
        r = c.get(url)
        r.raise_for_status()
        root = ET.fromstring(r.content)

    items: list[NewsItem] = []
    for node in root.findall(".//item")[:scan]:
        raw_title = _clean(node.findtext("title"))
        if not raw_title:
            continue
        src_node = node.find("{*}source")
        rss_source = src_node.text if src_node is not None else ""
        headline, outlet = _split_outlet(raw_title, rss_source or "")
        items.append(
            NewsItem(
                title=headline,
                outlet=outlet or "unattributed",
                published_at=_parse_pubdate(node.findtext("pubDate")),
                url=_clean(node.findtext("link")),
                query_topic=topic,
            )
        )
    return items


def _gdelt(query: str, topic: str, limit: int) -> list[NewsItem]:
    """Secondary index. GDELT rate-limits aggressively; a 429 is not an error
    worth surfacing, it just means this index had nothing to add right now."""
    try:
        with httpx.Client(timeout=25, headers={"User-Agent": registry.USER_AGENT}) as c:
            r = c.get(GDELT_DOC, params={
                "query": query, "mode": "artlist", "maxrecords": limit,
                "format": "json", "sort": "datedesc",
            })
        if r.status_code != 200:
            return []
        arts = r.json().get("articles", [])
    except Exception as exc:  # includes non-JSON throttle pages
        log.debug("GDELT unavailable: %s", exc)
        return []

    out: list[NewsItem] = []
    for a in arts:
        seen = a.get("seendate", "")
        iso = None
        if len(seen) >= 15:  # 20260821T134500Z
            try:
                iso = datetime.strptime(seen[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC).isoformat()
            except Exception:
                iso = None
        out.append(NewsItem(
            title=_clean(a.get("title")),
            outlet=_clean(a.get("domain")) or "unattributed",
            published_at=iso,
            url=a.get("url", ""),
            query_topic=topic,
        ))
    return out


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    """Two outlets covering one event are two reports, and both are kept.
    Only the identical headline from the identical outlet is a duplicate."""
    seen: set[tuple[str, str]] = set()
    out: list[NewsItem] = []
    for it in items:
        key = (it.title.lower()[:90], it.outlet.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def fetch_news(
    city_name: str | None = None,
    topic: str = "incidents",
    limit: int = 8,
    within_hours: int | None = None,
) -> dict[str, Any]:
    """Return recent reporting for a city (or the state), newest first.

    Never raises for an empty result: "nothing was reported" and "the index
    could not be read" are different answers and both are said plainly.
    """
    topic_key = topic if topic in TOPICS else "incidents"
    terms = TOPICS[topic_key]

    place = (city_name or "").strip()
    if place and place.lower() not in ("national", "all_india", ""):
        query = f'"{place}" ({terms})'.strip() if terms else f'"{place}" {STATE_ANCHOR}'
        scope = f"{place}, {STATE_ANCHOR}"
    else:
        query = f'"{STATE_ANCHOR}" ({terms})'.strip() if terms else f'"{STATE_ANCHOR}"'
        scope = STATE_ANCHOR

    cache_key = f"news:{scope}:{topic_key}:{limit}:{within_hours}"
    cached = registry.cache_get(cache_key, CACHE_TTL_S)
    if cached is not None and not cached.get("stale"):
        return cached["payload"]

    items: list[NewsItem] = []
    index_error: str | None = None
    try:
        items.extend(_google_news(query, topic_key, limit, scan=80))
    except Exception as exc:
        index_error = f"{type(exc).__name__}: {exc}"
        log.warning("Google News index unavailable: %s", exc)

    if len(items) < limit:
        items.extend(_gdelt(query, topic_key, limit))

    items = _dedupe(items)

    if within_hours:
        cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
        kept = []
        for it in items:
            if not it.published_at:
                continue  # undated reporting cannot be placed in a window
            try:
                if datetime.fromisoformat(it.published_at) >= cutoff:
                    kept.append(it)
            except Exception:
                continue
        items = kept

    items.sort(key=lambda i: i.published_at or "", reverse=True)
    items = items[:limit]

    result = {
        "status": "ok" if items or not index_error else "unavailable",
        "scope": scope,
        "topic": topic_key,
        "within_hours": within_hours,
        "count": len(items),
        "items": [i.to_dict() for i in items],
        "index_error": index_error,
        "fetched_at": datetime.now(UTC).isoformat(),
        "attribution_note": (
            "Headlines are reproduced as published. Casualty figures, causes and "
            "names are the reporting outlet's, not this platform's."
        ),
    }
    if items:
        # The newest headline is the upstream stamp: freshness is judged on
        # when the reporting happened, not on when we happened to read it.
        registry.cache_put(cache_key, result, items[0].published_at)
    return result
