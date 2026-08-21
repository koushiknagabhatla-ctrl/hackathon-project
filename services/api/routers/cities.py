"""CitySense Pan-India Geospatial Intelligence API Router.

Surfaces authoritative real Indian cities, GeoJSON cluster layers,
state filters, and city-level telemetry for all 28 States and 8 UTs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from services.api.core import geo_cities

router = APIRouter(prefix="/v1/cities", tags=["CitySense Pan-India Geospatial"])


@router.get("")
def list_cities_endpoint(
    state: str | None = Query(default=None, description="Filter by Indian State or Union Territory"),
    tier: str | None = Query(default=None, description="Filter by Tier (Tier 1, Tier 2, Tier 3)"),
    q: str | None = Query(default=None, description="Search query by city or district name"),
    limit: int = Query(default=300, ge=1, le=500),
) -> Any:
    """List real Indian cities with administrative metadata, coordinates, and populations."""
    cities = geo_cities.list_cities(state_filter=state, tier_filter=tier, query=q, limit=limit)
    return {
        "count": len(cities),
        "total_available": len(geo_cities.CITIES),
        "cities": [c.to_dict() for c in cities],
    }


@router.get("/geojson")
def get_cities_geojson_endpoint(
    state: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> Any:
    """Get RFC 7946 GeoJSON FeatureCollection of Indian cities for MapLibre clustering."""
    return geo_cities.get_cities_geojson(state_filter=state, tier_filter=tier, query=q)


@router.get("/states")
def list_states_endpoint() -> Any:
    """List all 28 Indian States and 8 Union Territories with city counts."""
    counts: dict[str, int] = {}
    for c in geo_cities.CITIES:
        counts[c.state] = counts.get(c.state, 0) + 1

    return {
        "count": len(geo_cities.INDIAN_STATES_AND_UTS),
        "states": [
            {"name": s, "city_count": counts.get(s, 0)}
            for s in sorted(geo_cities.INDIAN_STATES_AND_UTS)
        ],
    }


@router.get("/{city_id}")
def get_city_endpoint(city_id: str) -> Any:
    """Get precise geospatial and administrative details for a specific Indian city."""
    city = geo_cities.get_city(city_id)
    if not city:
        raise HTTPException(status_code=404, detail=f"City {city_id} not found in Indian registry")
    return city.to_dict()
