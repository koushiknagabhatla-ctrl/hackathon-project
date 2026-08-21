"""Refresh every CONFIGURED connector on its own interval and ingest the result.

Runnable standalone:

    python scripts/poll_connectors.py --once        # one pass, then exit
    python scripts/poll_connectors.py               # loop forever
    python scripts/poll_connectors.py --only conn_usgs_seismic --force

Each source declares its own `poll_interval_s` in `connectors/registry.py`, and
this script honours it: the loop wakes on a short tick and refreshes only the
sources that are actually due, judged against `registry.status()` - which is on
disk, so a restart does not re-hammer a free API tier.

HONEST FAILURE LOGGING. Every pass prints one line per source with its real
outcome, and the outcome vocabulary is the registry's, not a summary of it:

    ok            the source answered and its data was ingested
    no_events     the source answered and had nothing to report (a real answer)
    no_stations   ditto, for a sensor network with no station in range
    unavailable   the source could not be reached; the LAST VERIFIED time is
                  printed alongside, and nothing was substituted for the gap
    unconfigured  no credential was ever supplied; nothing broke
    error         the connector itself raised - a bug, printed with its type

There is no outcome in which this script writes a value that a source did not
return. A failing connector produces a log line and an unchanged database.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.connectors import (  # noqa: E402
    air_quality, hydrology, osm_gis, registry, seismic, weather,
)
from services.api.core import db  # noqa: E402

log = logging.getLogger("auralis.poll")

# source id -> the callable that refreshes it. A source in the registry with no
# entry here is DECLARED BUT NOT IMPLEMENTED, and is reported as such rather
# than being quietly skipped: an unlisted hole is how a gap becomes invisible.
FETCHERS: dict[str, Callable[[], dict[str, Any]]] = {
    "conn_openmeteo": weather.fetch_open_meteo,
    "conn_openweathermap": weather.fetch_openweathermap,
    "conn_openmeteo_flood": hydrology.fetch_river_discharge,
    "conn_openaq": air_quality.fetch_air_quality,
    "conn_usgs_seismic": seismic.fetch_seismic,
    "conn_osm": osm_gis.fetch_osm_infrastructure,
    "conn_indiawris": hydrology.fetch_india_wris,
    "conn_cwc_ffs": hydrology.fetch_cwc_flood_forecast,
}

TICK_S = 30.0


def _now() -> datetime:
    return datetime.now(UTC)


def due(source: registry.Source, force: bool = False) -> bool:
    """Is this source's own interval up? Judged on the persisted last ATTEMPT,
    so a source that is failing backs off on its interval instead of being
    retried on every tick."""
    if force:
        return True
    last = registry.status(source.id).get("last_attempt_at")
    if not last:
        return True
    try:
        return (_now() - registry._parse(last)).total_seconds() >= source.poll_interval_s
    except (ValueError, TypeError):
        return True


def refresh(source_id: str) -> dict[str, Any]:
    """One connector, one refresh. Never raises: a broken connector is a log
    line, not a dead poller."""
    fetch = FETCHERS.get(source_id)
    if fetch is None:
        return {"status": "not_implemented",
                "message": f"{source_id} is declared in the registry but no "
                           f"fetcher is wired to it"}
    try:
        return fetch() or {"status": "error", "error": "connector returned nothing"}
    except Exception as exc:  # noqa: BLE001 - one bad connector must not stop the rest
        log.exception("connector %s raised", source_id)
        registry.record(source_id, ok=False, detail=f"{type(exc).__name__}: {exc}")
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def describe(source: registry.Source, result: dict[str, Any]) -> str:
    """One honest line. A gap names the last time we genuinely had data."""
    status = str(result.get("status", "unknown"))
    detail = ""
    if status == "ok":
        st = registry.status(source.id)
        detail = str(st.get("last_detail") or "")
        upstream = st.get("last_upstream_at")
        # Printed even when it is None: "the source gave us no observation time"
        # is a fact an operator needs, and hiding it invites reading the fetch
        # time as the observation time.
        detail = f"{detail} | upstream_at={upstream or 'NOT REPORTED BY SOURCE'}"
    elif status == "unavailable":
        last = result.get("last_verified_at")
        detail = (f"{result.get('error', '')} | last verified: "
                  f"{last or 'NEVER - this source has never returned data'}")
    elif status == "unconfigured":
        detail = f"set {', '.join(source.env_vars) or '(no vars declared)'}"
    elif status in ("no_events", "no_stations"):
        detail = str(result.get("message", ""))
    else:
        detail = str(result.get("error") or result.get("message") or "")
    return f"  {status.upper():<14} {source.id:<24} {detail}"


def one_pass(only: str | None = None, force: bool = False) -> dict[str, str]:
    """Refresh everything that is configured and due. Returns id -> status."""
    print(f"[{_now().strftime('%Y-%m-%dT%H:%M:%SZ')}] poll pass")
    out: dict[str, str] = {}
    for source in registry.SOURCES:
        if only and source.id != only:
            continue
        if not registry.configured(source.id):
            # A missing credential is a legitimate resting state, and it is
            # printed every pass so the hole stays visible.
            print(describe(source, registry.unconfigured(source.id)))
            out[source.id] = "unconfigured"
            continue
        if not due(source, force):
            out[source.id] = "not_due"
            continue
        result = refresh(source.id)
        print(describe(source, result))
        out[source.id] = str(result.get("status", "unknown"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--only", help="refresh a single registry source id")
    ap.add_argument("--force", action="store_true",
                    help="ignore poll intervals and refresh now")
    ap.add_argument("--tick", type=float, default=TICK_S,
                    help=f"seconds between due-checks in loop mode (default {TICK_S:g})")
    ap.add_argument("--db", help="path to the Auralis SQLite database")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.db:
        db.init_db(args.db)

    known = {s.id for s in registry.SOURCES}
    if args.only and args.only not in known:
        ap.error(f"unknown source id {args.only!r}; known: {', '.join(sorted(known))}")

    print(f"jurisdiction: {registry.JURISDICTION_NAME} "
          f"({registry.JURISDICTION_LAT}, {registry.JURISDICTION_LON})")
    missing = sorted(known - set(FETCHERS))
    if missing:
        print(f"WARNING: declared in the registry with no fetcher: {', '.join(missing)}")

    if args.once:
        one_pass(args.only, args.force)
        return 0

    print(f"looping; tick {args.tick:g}s, per-source intervals from the registry. "
          f"Ctrl-C to stop.")
    force = args.force
    try:
        while True:
            one_pass(args.only, force)
            force = False  # --force applies to the first pass, then intervals rule
            time.sleep(args.tick)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
