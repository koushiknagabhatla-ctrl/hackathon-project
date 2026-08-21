"""Municipal Analytics & Executive Intelligence API Router.

Surfaces operational KPIs, SLA compliance rates, and department performance.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from services.api.auth import get_principal
from services.api.core import analytics

router = APIRouter(prefix="/v1/analytics", tags=["Municipal Analytics & Executive KPIs"])


@router.get("/overview")
def get_analytics_overview_endpoint(
    principal: dict = Depends(get_principal),
) -> Any:
    """Get full city analytics, incident resolution times, SLA performance, and AI gateway metrics."""
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    return analytics.get_city_analytics_overview(tenant_id)
