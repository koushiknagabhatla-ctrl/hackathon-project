"""Authoritative Andhra Pradesh Geospatial Dataset & Real Urban City Registry.

Contains accurate geospatial coordinates, administrative districts, municipal corporations,
population metrics, and elevation tiers for all major cities and urban centers across
Andhra Pradesh.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("auralis.geo_cities")


@dataclass(frozen=True)
class IndianCity:
    id: str
    name: str
    state: str
    district: str
    lat: float
    lon: float
    population: int
    tier: str  # "Tier 1" | "Tier 2" | "Tier 3"
    is_capital: bool
    zone: str  # "Coastal Andhra" | "Rayalaseema" | "Capital Region" | "North Coastal"
    elevation_m: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "district": self.district,
            "lat": self.lat,
            "lon": self.lon,
            "population": self.population,
            "tier": self.tier,
            "is_capital": self.is_capital,
            "zone": self.zone,
            "elevation_m": self.elevation_m,
        }

    def to_geojson_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": {
                "type": "Point",
                "coordinates": [self.lon, self.lat],
            },
            "properties": {
                "id": self.id,
                "name": self.name,
                "state": self.state,
                "district": self.district,
                "population": self.population,
                "tier": self.tier,
                "is_capital": self.is_capital,
                "zone": self.zone,
                "elevation_m": self.elevation_m,
            },
        }


# Authoritative Andhra Pradesh Urban Cities & District Centers
CITIES: list[IndianCity] = [
    # ─── CAPITAL REGION & METROPOLITAN CENTERS ───
    IndianCity("ap_vja", "Vijayawada", "Andhra Pradesh", "NTR / Krishna", 16.5062, 80.6480, 1723000, "Tier 1", False, "Capital Region", 11),
    IndianCity("ap_amr", "Amaravati", "Andhra Pradesh", "Guntur / CRDA", 16.5417, 80.5158, 280000, "Tier 1", True, "Capital Region", 15),
    IndianCity("ap_vzk", "Visakhapatnam", "Andhra Pradesh", "Visakhapatnam", 17.6868, 83.2185, 2358000, "Tier 1", False, "North Coastal", 5),
    IndianCity("ap_gtr", "Guntur", "Andhra Pradesh", "Guntur", 16.3067, 80.4365, 873000, "Tier 2", False, "Capital Region", 33),

    # ─── RAYALASEEMA CITIES ───
    IndianCity("ap_tpt", "Tirupati", "Andhra Pradesh", "Tirupati", 13.6288, 79.4192, 510000, "Tier 2", False, "Rayalaseema", 162),
    IndianCity("ap_knl", "Kurnool", "Andhra Pradesh", "Kurnool", 15.8281, 78.0373, 560000, "Tier 2", False, "Rayalaseema", 273),
    IndianCity("ap_kdp", "Kadapa", "Andhra Pradesh", "YSR Kadapa", 14.4673, 78.8242, 420000, "Tier 2", False, "Rayalaseema", 138),
    IndianCity("ap_atp", "Anantapur", "Andhra Pradesh", "Anantapuramu", 14.6819, 77.6006, 460000, "Tier 2", False, "Rayalaseema", 335),
    IndianCity("ap_ndl", "Nandyal", "Andhra Pradesh", "Nandyal", 15.4786, 78.4836, 230000, "Tier 3", False, "Rayalaseema", 203),
    IndianCity("ap_pdt", "Proddatur", "Andhra Pradesh", "YSR Kadapa", 14.7527, 78.5523, 217000, "Tier 3", False, "Rayalaseema", 150),
    IndianCity("ap_ctr", "Chittoor", "Andhra Pradesh", "Chittoor", 13.2172, 79.1003, 190000, "Tier 3", False, "Rayalaseema", 300),
    IndianCity("ap_hnp", "Hindupur", "Andhra Pradesh", "Sri Sathya Sai", 13.8290, 77.4920, 180000, "Tier 3", False, "Rayalaseema", 621),
    IndianCity("ap_mdp", "Madanapalle", "Andhra Pradesh", "Annamayya", 13.5560, 78.5030, 180000, "Tier 3", False, "Rayalaseema", 695),
    IndianCity("ap_adn", "Adoni", "Andhra Pradesh", "Kurnool", 15.6322, 77.2728, 185000, "Tier 3", False, "Rayalaseema", 435),
    IndianCity("ap_dmv", "Dharmavaram", "Andhra Pradesh", "Sri Sathya Sai", 14.4137, 77.7126, 130000, "Tier 3", False, "Rayalaseema", 345),
    IndianCity("ap_ptp", "Puttaparthi", "Andhra Pradesh", "Sri Sathya Sai", 14.1670, 77.8115, 65000, "Tier 3", False, "Rayalaseema", 475),
    IndianCity("ap_ryc", "Rayachoti", "Andhra Pradesh", "Annamayya", 14.0573, 78.7523, 118000, "Tier 3", False, "Rayalaseema", 380),
    IndianCity("ap_alg", "Allagadda", "Andhra Pradesh", "Nandyal", 15.1333, 78.5167, 85000, "Tier 3", False, "Rayalaseema", 210),

    # ─── COASTAL ANDHRA CITIES ───
    IndianCity("ap_kkd", "Kakinada", "Andhra Pradesh", "Kakinada", 16.9891, 82.2475, 520000, "Tier 2", False, "Coastal Andhra", 2),
    IndianCity("ap_rjy", "Rajahmundry", "Andhra Pradesh", "East Godavari", 17.0005, 81.8040, 540000, "Tier 2", False, "Coastal Andhra", 14),
    IndianCity("ap_nel", "Nellore", "Andhra Pradesh", "SPSR Nellore", 14.4426, 79.9865, 600000, "Tier 2", False, "Coastal Andhra", 19),
    IndianCity("ap_elr", "Eluru", "Andhra Pradesh", "Eluru", 16.7107, 81.0952, 250000, "Tier 3", False, "Coastal Andhra", 22),
    IndianCity("ap_ogl", "Ongole", "Andhra Pradesh", "Prakasam", 15.5057, 80.0499, 252000, "Tier 3", False, "Coastal Andhra", 10),
    IndianCity("ap_mtm", "Machilipatnam", "Andhra Pradesh", "Krishna", 16.1875, 81.1389, 170000, "Tier 3", False, "Coastal Andhra", 4),
    IndianCity("ap_tnl", "Tenali", "Andhra Pradesh", "Guntur", 16.2430, 80.6400, 190000, "Tier 3", False, "Coastal Andhra", 11),
    IndianCity("ap_bvm", "Bhimavaram", "Andhra Pradesh", "West Godavari", 16.5449, 81.5212, 175000, "Tier 3", False, "Coastal Andhra", 7),
    IndianCity("ap_tpg", "Tadepalligudem", "Andhra Pradesh", "West Godavari", 16.8142, 81.5268, 130000, "Tier 3", False, "Coastal Andhra", 34),
    IndianCity("ap_gdv", "Gudivada", "Andhra Pradesh", "Krishna", 16.4410, 80.9926, 140000, "Tier 3", False, "Coastal Andhra", 6),
    IndianCity("ap_nrp", "Narasaraopet", "Andhra Pradesh", "Palnadu", 16.2360, 80.0500, 120000, "Tier 3", False, "Coastal Andhra", 55),
    IndianCity("ap_bpt", "Bapatla", "Andhra Pradesh", "Bapatla", 15.9042, 80.4676, 95000, "Tier 3", False, "Coastal Andhra", 5),
    IndianCity("ap_mkp", "Markapur", "Andhra Pradesh", "Prakasam", 15.5976, 79.2708, 100000, "Tier 3", False, "Coastal Andhra", 145),
    IndianCity("ap_kvl", "Kavali", "Andhra Pradesh", "SPSR Nellore", 14.9132, 79.9926, 90000, "Tier 3", False, "Coastal Andhra", 15),

    # ─── NORTH COASTAL ANDHRA ───
    IndianCity("ap_vzm", "Vizianagaram", "Andhra Pradesh", "Vizianagaram", 18.1067, 83.3956, 290000, "Tier 3", False, "North Coastal", 66),
    IndianCity("ap_skm", "Srikakulam", "Andhra Pradesh", "Srikakulam", 18.2949, 83.8938, 160000, "Tier 3", False, "North Coastal", 10),
    IndianCity("ap_pvp", "Parvathipuram", "Andhra Pradesh", "Parvathipuram Manyam", 18.7833, 83.4333, 75000, "Tier 3", False, "North Coastal", 120),
    IndianCity("ap_ank", "Anakapalli", "Andhra Pradesh", "Anakapalli", 17.6913, 83.0039, 140000, "Tier 3", False, "North Coastal", 26),
]

_CITY_MAP: dict[str, IndianCity] = {c.id: c for c in CITIES}


def list_cities(
    state_filter: str | None = None,
    tier_filter: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> list[IndianCity]:
    """Filter and search cities across Andhra Pradesh."""
    results = CITIES
    if tier_filter and tier_filter.lower() != "all":
        results = [c for c in results if c.tier.lower() == tier_filter.lower()]
    if query:
        q = query.lower().strip()
        results = [
            c for c in results
            if q in c.name.lower() or q in c.district.lower() or q in c.zone.lower()
        ]
    return results[:limit]


def get_city(city_id: str) -> IndianCity | None:
    """Get single city by unique ID."""
    return _CITY_MAP.get(city_id)


def find_city_by_name(name: str) -> IndianCity | None:
    """Find an Andhra Pradesh city by name or alias (case-insensitive fuzzy match)."""
    if not name:
        return None
    target = name.strip().lower()
    # Exact match first
    for c in CITIES:
        if c.name.lower() == target:
            return c
    # Partial match
    for c in CITIES:
        if target in c.name.lower() or c.name.lower() in target:
            return c
    return None


def get_cities_geojson(
    state_filter: str | None = None,
    tier_filter: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Generate RFC 7946 GeoJSON FeatureCollection for Andhra Pradesh cities."""
    cities = list_cities(state_filter=state_filter, tier_filter=tier_filter, query=query, limit=100)
    return {
        "type": "FeatureCollection",
        "features": [c.to_geojson_feature() for c in cities],
    }
