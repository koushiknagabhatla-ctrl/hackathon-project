"""Connector Package."""

from services.api.connectors.air_quality import fetch_air_quality
from services.api.connectors.hydrology import fetch_hydrology, fetch_river_discharge
from services.api.connectors.osm_gis import fetch_osm_infrastructure
from services.api.connectors.seismic import fetch_seismic
from services.api.connectors.weather import fetch_live_weather

__all__ = [
    "fetch_air_quality",
    "fetch_hydrology",
    "fetch_live_weather",
    "fetch_osm_infrastructure",
    "fetch_river_discharge",
    "fetch_seismic",
]
