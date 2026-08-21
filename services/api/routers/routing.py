"""Routing & Traffic Intelligence API Router.

Surfaces dynamic hazard-avoidance routing and urban corridor traffic status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.auth import get_principal
from services.api.connectors import routing, traffic

router = APIRouter(prefix="/v1", tags=["Routing & Traffic Intelligence"])


class RouteRequestIn(BaseModel):
    origin_lat: float = Field(..., ge=-90.0, le=90.0, description="Origin latitude")
    origin_lon: float = Field(..., ge=-180.0, le=180.0, description="Origin longitude")
    dest_lat: float = Field(..., ge=-90.0, le=90.0, description="Destination latitude")
    dest_lon: float = Field(..., ge=-180.0, le=180.0, description="Destination longitude")
    avoid_hazards: bool = Field(default=True, description="Avoid active flood, accident, and road blockage zones")


@router.post("/routes/safe")
def calculate_route_endpoint(
    body: RouteRequestIn,
    principal: dict = Depends(get_principal),
) -> Any:
    """Calculate an optimal driving route with dynamic hazard avoidance.

    If active incidents (accidents, floods, fallen trees) intersect the path,
    calculates an automated detour avoiding the hazard zone.
    """
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    try:
        route = routing.calculate_safe_route(
            origin=(body.origin_lat, body.origin_lon),
            dest=(body.dest_lat, body.dest_lon),
            avoid_hazards=body.avoid_hazards,
            tenant_id=tenant_id,
        )
        return route.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Routing calculation failed: {exc}")


@router.get("/traffic/corridors")
def list_traffic_corridors_endpoint(
    principal: dict = Depends(get_principal),
) -> Any:
    """Get real-time traffic speeds, Level of Service (LOS), and delays across major city corridors."""
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    corridors = traffic.get_corridor_status(tenant_id)
    return {"corridors": corridors, "count": len(corridors)}
