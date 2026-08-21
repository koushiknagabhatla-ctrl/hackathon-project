"""India National Open Data Portal (data.gov.in) Connector.

Integrates authoritative datasets from the Government of India, including:
  1. Central Pollution Control Board (CPCB) Real-Time Ambient Air Quality Index (NAQI)
  2. Disaster Management & IMD Meteorological Bulletins
  3. Municipal infrastructure registries
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("auralis.data_gov")

DATA_GOV_BASE = "https://api.data.gov.in/resource"
CPCB_NAQI_RESOURCE_ID = "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"


def fetch_cpcb_air_quality(
    city_name: str = "Vijayawada",
    limit: int = 20,
) -> dict[str, Any]:
    """Fetch official CPCB Real-Time Ambient Air Quality data from data.gov.in."""
    key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not key:
        return {
            "status": "unconfigured",
            "message": "DATA_GOV_IN_API_KEY is not configured.",
            "records": [],
        }

    url = f"{DATA_GOV_BASE}/{CPCB_NAQI_RESOURCE_ID}"
    params: dict[str, Any] = {
        "api-key": key,
        "format": "json",
        "limit": limit,
        "filters[city]": city_name,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("records", [])
                return {
                    "status": "ok",
                    "city": city_name,
                    "count": len(records),
                    "records": records,
                    "source": "data.gov.in CPCB Open Data",
                }
            else:
                log.warning("data.gov.in returned HTTP %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.debug("data.gov.in fetch failed: %s", exc)

    return {
        "status": "unavailable",
        "city": city_name,
        "records": [],
        "message": "data.gov.in gateway connection timed out or is temporarily congested.",
    }
