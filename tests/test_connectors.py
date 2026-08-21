"""Connectors, tested WITHOUT the network.

Every test here monkeypatches `registry.get_json`, which is the single outbound
seam in the connector package. Nothing resolves a hostname, opens a socket or
depends on an API key being present on the machine running the suite.

The payloads below are RECORDED response shapes, taken from real probes of the
live endpoints (USGS 2026-08-21, HTTP 200; OpenWeatherMap and Overpass from
their published response documents). They are fixtures, not observations - they
exist to prove the failure paths behave, not to say anything about the world.

What is asserted is the governing rule, four ways:

  * a timeout reports UNAVAILABLE with the last verified timestamp, and writes
    no evidence - it never substitutes a value;
  * a missing credential reports UNCONFIGURED, which is a resting state and
    not an error;
  * a cache hit is judged against the ORIGINAL upstream timestamp and reported
    stale, never re-stamped as current;
  * a source that gives us no observation time does not get one from our clock.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from services.api.connectors import air_quality, osm_gis, registry, seismic, weather
from services.api.core import db

TENANT = "ten_conn"
PRINCIPAL = "p_conn_operator"
LAT, LON = 16.5062, 80.6480


# ------------------------------------------------------------------ fixtures
def _ago(minutes: int) -> tuple[int, str]:
    """(epoch_ms, expected ISO) `minutes` in the past.

    The `all_day` feed only ever carries the last 24 hours, and ingest
    quarantines anything older than that as clock skew. Pinning a literal epoch
    into the fixture would make these tests start failing on a calendar date,
    which teaches people to ignore them.
    """
    t = (datetime.now(UTC) - timedelta(minutes=minutes)).replace(microsecond=0)
    return int(t.timestamp() * 1000), t.strftime("%Y-%m-%dT%H:%M:%SZ")


NEAR_MS, NEAR_ISO = _ago(55)
FAR_MS, FAR_ISO = _ago(20)
FEED_MS, FEED_ISO = _ago(1)

# Recorded from https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/
# all_day.geojson (HTTP 200, api 2.7.0). Two features: one inside the default
# 1000 km radius of Vijayawada, one in California that must be filtered out.
USGS_FEED: dict[str, Any] = {
    "type": "FeatureCollection",
    "metadata": {
        "generated": FEED_MS,
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
        "title": "USGS All Earthquakes, Past Day",
        "status": 200, "api": "2.7.0", "count": 2,
    },
    "features": [
        {
            "type": "Feature", "id": "us_fixture_near",
            "properties": {
                "mag": 4.6, "place": "Bay of Bengal, offshore Andhra Pradesh",
                "time": NEAR_MS, "updated": NEAR_MS + 600000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us_fixture_near",
                "magType": "mb", "status": "reviewed", "tsunami": 0,
                "sig": 325, "net": "us", "type": "earthquake",
            },
            # ~150 km east of Vijayawada, well inside the radius
            "geometry": {"type": "Point", "coordinates": [82.0, 16.4, 33.0]},
        },
        {
            "type": "Feature", "id": "ci_fixture_far",
            "properties": {
                "mag": 0.84, "place": "19 km NE of Little Lake, CA",
                "time": FAR_MS, "updated": FAR_MS + 211000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/ci_fixture_far",
                "magType": "ml", "status": "automatic", "tsunami": 0,
                "sig": 11, "net": "ci", "type": "earthquake",
            },
            "geometry": {"type": "Point", "coordinates": [-117.73, 36.04, 1.9]},
        },
    ],
}

# OpenWeatherMap /data/2.5/weather, with the `dt` observation time REMOVED.
OWM_NO_DT: dict[str, Any] = {
    "coord": {"lon": 80.648, "lat": 16.5062},
    "weather": [{"description": "light rain"}],
    "main": {"temp": 29.1, "humidity": 82, "pressure": 1004},
    "wind": {"speed": 3.6, "deg": 240},
    "rain": {"1h": 2.4},
    "name": "Vijayawada",
}

OVERPASS_OK: dict[str, Any] = {
    "version": 0.6,
    "generator": "Overpass API 0.7.62",
    "osm3s": {"timestamp_osm_base": "2026-08-21T09:00:00Z",
              "copyright": "The data included in this document is from "
                           "www.openstreetmap.org."},
    "elements": [
        {"type": "node", "id": 1111, "lat": 16.5100, "lon": 80.6400,
         "tags": {"power": "substation", "name": "Fixture Substation"}},
        # no lat/lon and no center: cannot be placed, must be skipped not guessed
        {"type": "way", "id": 2222, "tags": {"highway": "primary"}},
    ],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh DB, fresh cache dir, and no credentials leaking in from the box."""
    monkeypatch.setenv("AURALIS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("AURALIS_TENANT_ID", TENANT)
    for var in ("OPENAQ_API_KEY", "OPENWEATHER_API_KEY",
                "INDIAWRIS_API_URL", "INDIAWRIS_API_KEY",
                "CWC_FFS_API_URL", "CWC_FFS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(registry, "TENANT_ID", TENANT)

    db.init_db(tmp_path / "connectors.db")
    db.run("INSERT INTO tenant(id,name,jurisdiction,created_at) VALUES(?,?,?,?)",
           TENANT, "Vijayawada", "Andhra Pradesh, IN", "2026-08-21T00:00:00Z")
    db.run("INSERT INTO principal(id,tenant_id,display_name,role,trust_domain,status) "
           "VALUES(?,?,?,?,?,?)",
           PRINCIPAL, TENANT, "Connector Poller", "operator", "prod", "active")
    yield
    db.init_db(":memory:")


def _seam(monkeypatch, result: Any, error: str | None = None):
    """Replace the ONE outbound call in the connector package."""
    calls: list[dict[str, Any]] = []

    def fake_get_json(url, params=None, headers=None, timeout=15.0,
                      method="GET", data=None):
        calls.append({"url": url, "params": params, "method": method})
        return result, error

    monkeypatch.setattr(registry, "get_json", fake_get_json)
    return calls


def _forbid_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a connector reached the network")

    monkeypatch.setattr(registry, "get_json", boom)


# ============================================================ USGS seismic
def test_seismic_ingests_real_provenance_and_filters_by_radius(monkeypatch):
    calls = _seam(monkeypatch, USGS_FEED)

    out = seismic.fetch_seismic(LAT, LON, principal=PRINCIPAL)

    assert calls[0]["url"] == seismic.FEED_URL
    assert out["status"] == "ok"
    assert out["events_in_feed"] == 2
    assert out["events_outside_radius"] == 1, "the California quake must be dropped"
    assert [e["usgs_id"] for e in out["events"]] == ["us_fixture_near"]

    ev_id = out["events"][0]["evidence_id"]
    row = db.q1("SELECT * FROM evidence WHERE id=?", ev_id)
    # Trust tier is COPIED from the registry's connector row, never inferred.
    assert row["trust_tier"] == "certified", "USGS is certified, not statutory"
    assert row["evidence_class"] == "observation"
    assert row["observed_at"] == "2026-08-21T09:33:20Z"

    value = db.jload(row["value_json"], {})
    assert value["metric"] == "seismic" and value["value"] == 4.6
    payload = value["payload"]
    assert payload["usgs_id"] == "us_fixture_near"
    assert payload["source_url"].startswith("https://earthquake.usgs.gov/")
    assert "National Center for Seismology" in payload["authority_note"]


def test_seismic_labels_an_automatic_solution_as_revisable(monkeypatch):
    _seam(monkeypatch, USGS_FEED)
    out = seismic.fetch_seismic(LAT, LON, radius_km=20000.0, principal=PRINCIPAL)

    automatic = next(e for e in out["events"] if e["usgs_id"] == "ci_fixture_far")
    assert automatic["review_status"] == "automatic"
    row = db.q1("SELECT * FROM evidence WHERE id=?", automatic["evidence_id"])
    note = db.jload(row["value_json"], {})["payload"]["revision_note"]
    assert "may change" in note


def test_seismic_reports_no_events_rather_than_a_zero(monkeypatch):
    """The feed answered and there was nothing here. That is a finding."""
    _seam(monkeypatch, USGS_FEED)

    out = seismic.fetch_seismic(LAT, LON, radius_km=1.0, principal=PRINCIPAL)

    assert out["status"] == "no_events"
    assert out["events"] == []
    assert "magnitude" not in json.dumps(out).lower() or out["events"] == []
    assert db.scalar("SELECT COUNT(*) FROM evidence") == 0
    assert "None" not in out["message"]


def test_seismic_timeout_is_unavailable_not_fabricated(monkeypatch):
    # one genuine success first, so there IS a last verified time to report
    _seam(monkeypatch, USGS_FEED)
    seismic.fetch_seismic(LAT, LON, principal=PRINCIPAL)
    before = db.scalar("SELECT COUNT(*) FROM evidence")
    assert before == 1

    _seam(monkeypatch, None, "ConnectTimeout: timed out after 20.0s")
    out = seismic.fetch_seismic(LAT, LON, principal=PRINCIPAL)

    assert out["status"] == "unavailable"
    assert out["fabricated"] is False
    assert "ConnectTimeout" in out["error"]
    assert out["last_verified_at"], "a gap must name the last time we had data"
    assert "Last verified reading was at" in out["message"]
    assert "events" not in out and "magnitude" not in out
    assert db.scalar("SELECT COUNT(*) FROM evidence") == before, (
        "a failed fetch must not mint evidence")


def test_seismic_never_seen_says_so(monkeypatch):
    _seam(monkeypatch, None, "ConnectError: no route to host")
    out = seismic.fetch_seismic(LAT, LON, principal=PRINCIPAL)
    assert out["last_verified_at"] is None
    assert "never returned data" in out["message"]


def test_seismic_skips_a_feature_with_no_time_rather_than_stamping_one(monkeypatch):
    feed = json.loads(json.dumps(USGS_FEED))
    feed["features"][0]["properties"]["time"] = None
    _seam(monkeypatch, feed)

    out = seismic.fetch_seismic(LAT, LON, principal=PRINCIPAL)

    assert out["status"] == "no_events"
    assert out["events_unusable"] == 1
    assert db.scalar("SELECT COUNT(*) FROM event") == 0


# ================================================================== OpenAQ
def test_air_quality_without_a_key_is_unconfigured_not_broken(monkeypatch):
    _forbid_network(monkeypatch)   # unconfigured must not even try

    out = air_quality.fetch_air_quality(LAT, LON, principal=PRINCIPAL)

    assert out["status"] == "unconfigured"
    assert out["required_env"] == ["OPENAQ_API_KEY"]
    assert out["fabricated"] is False
    assert "explore.openaq.org/register" in out["message"]
    assert "readings" not in out


def test_air_quality_trust_tier_is_aggregator_not_statutory():
    source = registry.get("conn_openaq")
    assert source.trust_tier == "verified", (
        "OpenAQ relays CPCB; it is not CPCB. A statutory tier here would "
        "silently raise the precedence this evidence wins in conflicts.")
    assert "aggregator" in source.note.lower()


# ============================================================== weather
def test_openmeteo_is_verified_not_statutory():
    assert registry.get("conn_openmeteo").trust_tier == "verified"
    assert "not IMD" in registry.get("conn_openmeteo").note


def test_openweathermap_with_no_observation_time_is_unavailable(monkeypatch):
    """AUDIT FIX. This path used to stamp `datetime.now()` on a reading whose
    real observation time was unknown, which is a stale value presented as
    current - the exact failure the governing rule names."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "fixture-key-not-a-real-credential")
    _seam(monkeypatch, OWM_NO_DT)

    out = weather.fetch_openweathermap(LAT, LON, principal=PRINCIPAL)

    assert out["status"] == "unavailable"
    assert "no observation time" in out["error"]
    assert db.scalar("SELECT COUNT(*) FROM evidence") == 0


def test_openmeteo_ingests_the_upstream_observation_time(monkeypatch):
    _seam(monkeypatch, {
        "latitude": 16.5, "longitude": 80.65, "elevation": 23.0,
        "current_units": {"temperature_2m": "°C", "rain": "mm"},
        "current": {"time": "2026-08-21T09:15", "interval": 900,
                    "temperature_2m": 29.4, "relative_humidity_2m": 81,
                    "rain": 0.5, "precipitation": 0.5, "surface_pressure": 1003.2,
                    "wind_speed_10m": 12.4, "weather_code": 61},
    })

    out = weather.fetch_open_meteo(LAT, LON, principal=PRINCIPAL)

    assert out["status"] == "ok"
    assert out["observed_at"] == "2026-08-21T09:15:00Z"
    # 0.5 mm over a 900 s bucket is 2 mm/h, not 0.5 mm/h.
    assert out["rain_rate_mm_h"] == 2.0
    row = db.q1("SELECT * FROM evidence WHERE id=?", out["evidence_id"])
    assert row["observed_at"] == "2026-08-21T09:15:00Z"
    assert row["trust_tier"] == "verified"
    assert db.jload(row["value_json"], {})["payload"]["source_note"] == (
        "aggregated national met services; not IMD")


# ============================================================ Overpass / OSM
def test_osm_failure_reports_the_last_verified_time_and_writes_nothing(monkeypatch):
    _seam(monkeypatch, OVERPASS_OK)
    first = osm_gis.fetch_osm_infrastructure(tenant_id=TENANT)
    assert first["status"] == "ok" and first["assets_synced"] == 1
    assert first["osm_extract_at"] == "2026-08-21T09:00:00Z"
    assert first["skipped_no_geometry"] == 1, "an unplaceable element is skipped"

    _seam(monkeypatch, None, "ReadTimeout: overpass took too long")
    out = osm_gis.fetch_osm_infrastructure(tenant_id=TENANT)

    assert out["status"] == "unavailable"
    assert out["last_verified_at"], "AUDIT FIX: the gap must name the last success"
    assert out["trust_tier"] == "crowdsourced"
    assert db.scalar("SELECT COUNT(*) FROM asset") == 1, (
        "a failed sync must not add or remove assets")


def test_osm_resync_does_not_clobber_operator_state(monkeypatch):
    """AUDIT FIX. The old INSERT OR REPLACE reset desired/reported state on
    every sync, silently discarding what an operator had set."""
    _seam(monkeypatch, OVERPASS_OK)
    osm_gis.fetch_osm_infrastructure(tenant_id=TENANT)
    db.run("UPDATE asset SET desired_state=? WHERE id=?",
           db.jdump({"breaker": "open"}), "osm_n_1111")

    osm_gis.fetch_osm_infrastructure(tenant_id=TENANT)

    row = db.q1("SELECT * FROM asset WHERE id=?", "osm_n_1111")
    assert db.jload(row["desired_state"], {}) == {"breaker": "open"}
    assert db.jload(row["current_state"], {})["osm_id"] == 1111


# =============================================================== registry
def test_a_success_with_no_upstream_time_does_not_borrow_our_clock():
    """AUDIT FIX. `record()` used to fall back to now() for `last_upstream_at`,
    which conflates 'we called at T' with 'the source observed at T'."""
    registry.record("conn_usgs_seismic", ok=True, upstream_at=None, detail="0 events")
    st = registry.status("conn_usgs_seismic")

    assert st["last_attempt_ok"] is True
    assert st["last_success_at"], "we did successfully call it"
    assert st["last_upstream_at"] is None, "the source reported no observation time"


def test_a_failure_leaves_the_last_verified_time_untouched():
    registry.record("conn_openmeteo", ok=True, upstream_at="2026-08-21T09:15:00Z")
    registry.record("conn_openmeteo", ok=False, detail="ConnectTimeout")

    st = registry.status("conn_openmeteo")
    assert st["last_attempt_ok"] is False
    assert st["last_upstream_at"] == "2026-08-21T09:15:00Z"
    assert st["last_success_at"], "the earlier success is still the last one"


def test_a_stale_cache_entry_is_reported_stale_against_the_upstream_time():
    registry.cache_put("k", {"v": 1}, upstream_at="2020-01-01T00:00:00Z")
    entry = registry.cache_get("k", max_age_s=3600)

    assert entry["stale"] is True
    assert entry["upstream_at"] == "2020-01-01T00:00:00Z"
    assert entry["age_s"] > 3600
    assert entry["payload"] == {"v": 1}


def test_health_never_calls_a_source_fresh_without_a_real_success():
    for entry in registry.health():
        if not entry["last_success_at"]:
            assert entry["fresh"] is False
            assert entry["state"] in ("unconfigured", "never_fetched")


def test_every_ingesting_source_has_a_contract_and_a_registry_row():
    """An unrecognised event kind gets NO quality validation, which silently
    weakens the pipeline. Every kind a connector emits must be in CONTRACTS."""
    from services.api.core import ingest

    for kind in ("rainfall", "river_discharge", "air_quality", "seismic"):
        contract = ingest.CONTRACTS[kind]
        assert contract["required"], f"{kind} declares no required field"
        assert contract.get("numeric"), f"{kind} declares no plausibility range"

    registry.ensure_connectors(TENANT)
    for source in registry.SOURCES:
        if source.ingests:
            row = db.q1("SELECT * FROM connector WHERE id=?", source.id)
            assert row is not None, f"{source.id} has no connector row"
            assert row["trust_tier"] == source.trust_tier


def test_an_impossible_magnitude_is_quarantined_not_stored_as_fact(monkeypatch):
    feed = json.loads(json.dumps(USGS_FEED))
    feed["features"][0]["properties"]["mag"] = 42.0   # outside [-2, 10]
    _seam(monkeypatch, feed)

    out = seismic.fetch_seismic(LAT, LON, principal=PRINCIPAL)

    event = out["events"][0]
    assert event["quarantined"] is True
    assert "impossible value" in event["reason"]
    assert event["evidence_id"] is None, "a quarantined event mints no evidence"
