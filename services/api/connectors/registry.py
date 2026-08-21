"""Connector registry: who we pull from, whether it is configured, and when it
last genuinely answered.

This is the one place that knows the answer to "is this source real, and is what
we are showing actually from it?". Everything a connector needs to be honest
lives here:

  * SOURCES        - the declared catalogue, with trust tiers assigned honestly
  * configured()   - are the env vars this source needs actually set
  * get_json()     - timeout + one retry + backoff, then give up and say so
  * cache_get/put  - disk cache that carries the ORIGINAL upstream timestamp,
                     so a cache hit can never be displayed as "now"
  * unavailable()  - the failure return shape, carrying the LAST VERIFIED time
  * unconfigured() - the "we were never wired to this" return shape

Trust tier assignment is deliberately conservative. Open-Meteo aggregates
national meteorological services; it is not IMD, so it is `verified` and not
`statutory`. OpenAQ relays CPCB reference monitors for India but is an
aggregator, so it is `verified` too. Inflating a tier here would silently
inflate the precedence of the evidence it mints, which is a safety property.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
TENANT_ID = os.environ.get("AURALIS_TENANT_ID", "ten_vijayawada")

JURISDICTION_LAT = float(os.environ.get("AURALIS_JURISDICTION_LAT", "16.5062"))
JURISDICTION_LON = float(os.environ.get("AURALIS_JURISDICTION_LON", "80.6480"))
JURISDICTION_NAME = os.environ.get("AURALIS_JURISDICTION_NAME", "Vijayawada")

USER_AGENT = "Auralis-CivicIntelligence/1.0 (civic resilience research)"


def cache_dir() -> Path:
    p = Path(os.environ.get("AURALIS_CACHE_DIR", str(REPO_ROOT / "data" / "cache")))
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------- catalogue
@dataclass(frozen=True)
class Source:
    id: str                      # connector row id, and the registry key
    name: str                    # what a human sees on /data-health
    trust_tier: str              # statutory|certified|verified|crowdsourced|unknown
    freshness_sla_s: int         # older than this and it is not "current"
    poll_interval_s: int         # how often poll_connectors.py refreshes it
    endpoint: str                # the real URL we call, for checkable provenance
    env_vars: tuple[str, ...] = ()   # ALL must be set for this to be configured
    licence: str = ""
    note: str = ""               # why this tier, and what the source really is
    ingests: bool = True         # False = writes twin assets, not events


SOURCES: list[Source] = [
    Source(
        id="conn_openmeteo",
        name="Open-Meteo forecast API",
        trust_tier="verified",
        freshness_sla_s=1800,
        poll_interval_s=900,
        endpoint="https://api.open-meteo.com/v1/forecast",
        licence="CC-BY-4.0",
        note=(
            "Aggregates national meteorological services (incl. ECMWF/DWD/NOAA "
            "model output). It is NOT the India Meteorological Department (not IMD), so it "
            "is 'verified', not 'statutory'. Keyless and open."
        ),
    ),
    Source(
        id="conn_openweathermap",
        name="OpenWeatherMap current weather",
        trust_tier="verified",
        freshness_sla_s=1800,
        poll_interval_s=900,
        endpoint="https://api.openweathermap.org/data/2.5/weather",
        env_vars=("OPENWEATHER_API_KEY",),
        licence="CC-BY-SA-4.0 (free tier)",
        note=(
            "Optional second met source. Its purpose is corroboration: when it "
            "disagrees with Open-Meteo beyond tolerance both readings are kept "
            "and an evidence conflict is raised. Values are never averaged."
        ),
    ),
    Source(
        id="conn_openmeteo_flood",
        name="Open-Meteo Flood API (GloFAS river discharge)",
        trust_tier="verified",
        freshness_sla_s=6 * 3600,
        poll_interval_s=3600,
        endpoint="https://flood-api.open-meteo.com/v1/flood",
        licence="CC-BY-4.0",
        note=(
            "GloFAS is a hydrological MODEL, not a gauge. Its evidence is minted "
            "as evidence_class='derived' so no surface can present it as an "
            "observed river reading. Useful for Krishna/Budameru catchment trend, "
            "not a substitute for a CWC gauge."
        ),
    ),
    Source(
        id="conn_openaq",
        name="OpenAQ v3 air quality",
        trust_tier="verified",
        freshness_sla_s=2 * 3600,
        poll_interval_s=1800,
        endpoint="https://api.openaq.org/v3",
        env_vars=("OPENAQ_API_KEY",),
        licence="varies per provider, see OpenAQ licence metadata",
        note=(
            "Aggregates reference-grade government monitors (CPCB in India) and "
            "low-cost sensors. As an aggregator it is 'verified'; the underlying "
            "CPCB station is statutory but we are not reading CPCB directly. "
            "Free API key required: https://explore.openaq.org/register"
        ),
    ),
    Source(
        id="conn_usgs_seismic",
        name="USGS earthquake feed",
        trust_tier="certified",
        freshness_sla_s=2 * 3600,
        poll_interval_s=900,
        endpoint="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
        licence="public domain (US Government)",
        note=(
            "USGS NEIC is a primary authoritative producer of seismic "
            "parameters, so 'certified'. It is NOT the statutory seismic "
            "authority for India (that is the National Center for Seismology / "
            "IMD), so it is deliberately not 'statutory'. Keyless."
        ),
    ),
    Source(
        id="conn_osm",
        name="OpenStreetMap (Overpass API)",
        trust_tier="crowdsourced",
        freshness_sla_s=7 * 24 * 3600,
        poll_interval_s=24 * 3600,
        endpoint="https://overpass-api.de/api/interpreter",
        licence="ODbL 1.0",
        note=(
            "Volunteer-surveyed infrastructure. Every asset carries its OSM "
            "element id and a resolvable openstreetmap.org URL so any claim "
            "about the twin is checkable against the source."
        ),
        ingests=False,
    ),
    Source(
        id="conn_indiawris",
        name="India-WRIS (National Water Informatics Centre)",
        trust_tier="statutory",
        freshness_sla_s=3600,
        poll_interval_s=1800,
        endpoint="https://indiawris.gov.in",
        env_vars=("INDIAWRIS_API_URL", "INDIAWRIS_API_KEY"),
        note=(
            "NOT INTEGRATED. indiawris.gov.in and arc.indiawris.gov.in did not "
            "complete a TCP connection when probed, and no documented public "
            "JSON endpoint for river stage was verified. No response shape has "
            "been guessed. This adapter reports 'unconfigured' until an operator "
            "supplies a real NWIC-issued endpoint and credential."
        ),
    ),
    Source(
        id="conn_cwc_ffs",
        name="CWC Flood Forecasting System",
        trust_tier="statutory",
        freshness_sla_s=3600,
        poll_interval_s=1800,
        endpoint="https://ffs.india-water.gov.in",
        env_vars=("CWC_FFS_API_URL", "CWC_FFS_API_KEY"),
        note=(
            "NOT INTEGRATED. The portal is reachable, but its /iam/api surface "
            "is undocumented and returned a single groundwater well with null "
            "coordinates and no forecast fields when probed. Building a parser "
            "on it would be inventing a contract. Reports 'unconfigured'."
        ),
    ),
    Source(
        id="conn_gdelt",
        name="GDELT Global & Civic Event Intelligence",
        trust_tier="verified",
        freshness_sla_s=3600,
        poll_interval_s=1800,
        endpoint="https://api.gdeltproject.org/api/v2/doc/doc",
        env_vars=("GDELT_API_KEY",),
        licence="GDELT Project Open License",
        note=(
            "Global Database of Events, Language, and Tone. Real-time global and "
            "regional monitoring for natural disasters, civic hazards, and emergency news."
        ),
    ),
    Source(
        id="conn_open311",
        name="Auralis Open311 Civic Reporting Gateway",
        trust_tier="crowdsourced",
        freshness_sla_s=86400,
        poll_interval_s=3600,
        endpoint="internal://civic-reporting",
        licence="Municipal Open311 Protocol",
        note="Standardized municipal civic issue ingest channel.",
    ),
]

BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}


def get(source_id: str) -> Source:
    return BY_ID[source_id]


def configured(source_id: str) -> bool:
    """A source is configured when every env var it declares is non-empty.
    A source that needs no env var is always configured."""
    return all(os.environ.get(v, "").strip() for v in BY_ID[source_id].env_vars)


# ------------------------------------------------------------ last-fetch state
def _status_path(source_id: str) -> Path:
    return cache_dir() / f"{source_id}.status.json"


def record(source_id: str, ok: bool, upstream_at: str | None = None,
           detail: str = "") -> None:
    """Persist the outcome of one fetch attempt. Only a successful attempt moves
    `last_success_at` / `last_upstream_at`; a failure leaves the last verified
    timestamp exactly where it was, which is what `unavailable()` reports.

    `last_upstream_at` is the SOURCE's own stamp and nothing else. A successful
    fetch that carried no upstream timestamp leaves it None rather than
    substituting our clock: "we called at T" and "the source observed at T" are
    different facts, and conflating them is how a stale reading gets displayed
    as current.
    """
    prev = status(source_id)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "source_id": source_id,
        "last_attempt_at": now,
        "last_attempt_ok": ok,
        "last_detail": detail,
        "last_success_at": now if ok else prev.get("last_success_at"),
        "last_upstream_at": (
            upstream_at if ok and upstream_at else prev.get("last_upstream_at")
        ),
    }
    try:
        _status_path(source_id).write_text(json.dumps(body, indent=2), encoding="utf-8")
    except OSError as exc:  # a cache we cannot write is not a reason to fail a fetch
        log.warning("could not record fetch status for %s: %s", source_id, exc)


def status(source_id: str) -> dict[str, Any]:
    try:
        return json.loads(_status_path(source_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def health() -> list[dict[str, Any]]:
    """What /data-health renders: the declared catalogue joined to reality."""
    out = []
    for s in SOURCES:
        st = status(s.id)
        last = st.get("last_success_at")
        age = None
        if last:
            age = int((datetime.now(UTC) - _parse(last)).total_seconds())
        is_conf = configured(s.id)
        out.append({
            "id": s.id,
            "name": s.name,
            "trust_tier": s.trust_tier,
            "configured": is_conf,
            "env_vars": list(s.env_vars),
            "freshness_sla_s": s.freshness_sla_s,
            "poll_interval_s": s.poll_interval_s,
            "endpoint": s.endpoint,
            "licence": s.licence,
            "note": s.note,
            "last_success_at": last,
            "last_upstream_at": st.get("last_upstream_at"),
            "last_attempt_at": st.get("last_attempt_at"),
            "last_attempt_ok": st.get("last_attempt_ok"),
            "last_detail": st.get("last_detail"),
            "age_s": age,
            # `fresh` is a claim about reality, so it demands an actual success
            # inside the SLA. Never configured, never fetched => never fresh.
            "fresh": bool(last) and age is not None and age <= s.freshness_sla_s,
            "state": (
                "unconfigured" if not is_conf
                else "ok" if st.get("last_attempt_ok")
                else "unavailable" if st
                else "never_fetched"
            ),
        })
    return out


def _parse(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# ------------------------------------------------------------------- caching
def _cache_path(key: str) -> Path:
    return cache_dir() / f"cache_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"


def cache_put(key: str, payload: Any, upstream_at: str | None) -> None:
    """Store a response WITH the upstream timestamp it was generated at.

    `upstream_at` is the source's own stamp (Overpass osm3s.timestamp_osm_base,
    an observation time, ...). It is what freshness is judged on later, never
    the time we happened to read the cache.
    """
    body = {
        "key": key,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_at": upstream_at,
        "payload": payload,
    }
    try:
        _cache_path(key).write_text(json.dumps(body), encoding="utf-8")
    except OSError as exc:
        log.warning("could not write cache for %s: %s", key, exc)


def cache_get(key: str, max_age_s: int) -> dict[str, Any] | None:
    """Return the cached entry, or None if there is none.

    The entry ALWAYS carries `stale` and the original `upstream_at`. A caller
    that displays a stale entry as current is the bug this project exists to
    prevent, so the flag is computed here and never left to the caller to guess.
    """
    try:
        body = json.loads(_cache_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ref = body.get("upstream_at") or body.get("fetched_at")
    try:
        age = int((datetime.now(UTC) - _parse(ref)).total_seconds())
    except (ValueError, TypeError):
        return None
    body["age_s"] = age
    body["stale"] = age > max_age_s
    return body


# ---------------------------------------------------------------- http fetch
def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    method: str = "GET",
    data: dict[str, Any] | None = None,
) -> tuple[Any | None, str | None]:
    """One outbound call. Returns (parsed_json, None) or (None, error_string).

    Timeout on every request, exactly one retry with a short backoff, then give
    up. There is no third option: a caller that gets `None` reports unavailable,
    it does not substitute a value.
    """
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last = "no attempt made"
    for attempt in (0, 1):
        if attempt:
            time.sleep(2.0)  # polite backoff; free tiers rate-limit hard
        try:
            with httpx.Client(timeout=timeout, headers=hdrs, follow_redirects=True) as c:
                r = (c.post(url, params=params, data=data) if method == "POST"
                     else c.get(url, params=params))
            if r.status_code == 200:
                return r.json(), None
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 401, 403, 404):
                break  # a credential or contract problem; retrying cannot fix it
        except Exception as exc:  # noqa: BLE001 - any transport failure is 'unavailable'
            last = f"{type(exc).__name__}: {exc}"
    return None, last


# ------------------------------------------------------------ return shapes
def result_base(source_id: str) -> dict[str, Any]:
    s = BY_ID[source_id]
    st = status(source_id)
    return {
        "source_id": s.id,
        "source": s.name,
        "trust_tier": s.trust_tier,
        "endpoint": s.endpoint,
        "last_verified_at": st.get("last_success_at"),
        "last_upstream_at": st.get("last_upstream_at"),
    }


def unavailable(source_id: str, error: str) -> dict[str, Any]:
    """The source could not be reached. We report the gap and the last time we
    genuinely had data. We do not fill it."""
    s = BY_ID[source_id]
    record(source_id, ok=False, detail=error)
    out = result_base(source_id)
    out.update({
        "status": "unavailable",
        "error": error,
        "fabricated": False,
        "message": (
            f"{s.name} could not be reached. No value is shown for this source. "
            + (f"Last verified reading was at {out['last_verified_at']}."
               if out["last_verified_at"] else "This source has never returned data.")
        ),
    })
    return out


def unconfigured(source_id: str, extra: str = "") -> dict[str, Any]:
    """The source was never wired up. Distinct from unavailable: nothing broke,
    there is simply no credential, so there is nothing to report."""
    s = BY_ID[source_id]
    out = result_base(source_id)
    out.update({
        "status": "unconfigured",
        "required_env": list(s.env_vars),
        "fabricated": False,
        "message": (
            f"{s.name} is not configured. Set "
            f"{', '.join(s.env_vars) or '(no variables declared)'} to enable it. "
            f"{extra or s.note}"
        ).strip(),
    })
    return out


# ---------------------------------------------------- connector registration
def ensure_connectors(tenant_id: str | None = None) -> int:
    """Make sure every ingesting source has a `connector` row, so evidence minted
    from it inherits the trust tier declared HERE rather than one guessed at the
    call site. Idempotent; safe to call on every fetch.

    AUDIT NOTE (2026-08-21). This used to read `n += c.rowcount`, but `db.tx()`
    yields a CONNECTION, not a cursor - so on any database where the tenant row
    existed, every connector fetch died with AttributeError before ingesting
    anything. The count now comes from the cursor `execute` returns.
    `tenant_id` also defaults lazily instead of binding the module value at
    import time, so AURALIS_TENANT_ID set after import is still honoured.
    """
    from services.api.core import db

    tenant_id = tenant_id or TENANT_ID
    if db.q1("SELECT id FROM tenant WHERE id=?", tenant_id) is None:
        return 0  # nothing to attach to yet; seeding has not run
    n = 0
    with db.tx() as c:
        for s in SOURCES:
            if not s.ingests:
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO connector(id,tenant_id,name,trust_tier,"
                "contract_version,freshness_sla_s,owner) VALUES(?,?,?,?,?,?,?)",
                (s.id, tenant_id, s.name, s.trust_tier, "1.0.0",
                 s.freshness_sla_s, "connectors"),
            )
            n += cur.rowcount or 0
    return n
