"""Civic Issue Reporting & Computer Vision API Router.

Surfaces citizen report ingestion, automated image analysis,
status workflow updates, and reporting analytics.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.auth import get_principal
from services.api.core import civic_report, vision

router = APIRouter(prefix="/v1", tags=["Civic Reports & Vision"])


class VisionAnalyzeIn(BaseModel):
    image: str = Field(..., description="Base64 encoded image or data URL")
    hint_category: str | None = Field(default=None, description="Optional user category hint")


class CivicReportIn(BaseModel):
    category: str = Field(..., description="Civic category (pothole, garbage_overflow, waterlogging, etc.)")
    title: str = Field(default="", description="Short title")
    description: str = Field(..., description="Citizen report description")
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    address: str | None = Field(default=None)
    severity: Literal["low", "medium", "high", "critical"] | None = Field(default=None)
    image: str | None = Field(default=None, description="Optional Base64 encoded image")


class ReportStatusUpdateIn(BaseModel):
    status: Literal["submitted", "verified", "in_progress", "resolved", "rejected"]
    notes: str | None = None


# ─────────────────────────────────────────────────── Vision Endpoints

@router.post("/vision/analyze")
def analyze_image_endpoint(body: VisionAnalyzeIn) -> Any:
    """Analyze a civic photo using Computer Vision & Object/Hazard Detection.

    Returns:
    - primary_category: detected category (e.g. pothole, garbage_overflow, waterlogging)
    - confidence: detection confidence (0.0 to 1.0)
    - severity: estimated severity (low, medium, high, critical)
    - detections: list of bounding boxes with labels and coordinates
    - annotated_image_base64: visual image with drawn bounding boxes
    """
    try:
        res = vision.analyze_image(body.image, hint_category=body.hint_category)
        return res.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Image analysis failed: {exc}")


# ─────────────────────────────────────────────────── Report Endpoints

@router.post("/reports")
def create_report_endpoint(
    body: CivicReportIn,
    principal: dict = Depends(get_principal),
) -> Any:
    """Submit a citizen report with optional photo.

    Automatically triggers visual AI verification, calculates SLA, routes to
    the appropriate municipal department, and checks for spatial duplicates.
    """
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    reported_by = principal.get("id", "citizen_web")

    try:
        report = civic_report.create_civic_report(
            tenant_id=tenant_id,
            category=body.category,
            title=body.title,
            description=body.description,
            latitude=body.latitude,
            longitude=body.longitude,
            address=body.address,
            severity=body.severity,
            image_input=body.image,
            reported_by=reported_by,
        )
        return report
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to submit report: {exc}")


@router.get("/reports")
def list_reports_endpoint(
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    principal: dict = Depends(get_principal),
) -> Any:
    """List civic reports with optional filtering."""
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    reports = civic_report.list_reports(
        tenant_id=tenant_id,
        category=category,
        status=status,
        severity=severity,
        limit=limit,
    )
    return {"reports": reports, "count": len(reports)}


@router.get("/reports/stats/overview")
def get_report_stats_endpoint(
    principal: dict = Depends(get_principal),
) -> Any:
    """Get civic reporting summary analytics."""
    tenant_id = principal.get("tenant_id", "ten_vijayawada")
    return civic_report.get_report_stats(tenant_id)


@router.get("/reports/{report_id}")
def get_report_endpoint(
    report_id: str,
    principal: dict = Depends(get_principal),
) -> Any:
    """Get full details of a specific civic report."""
    report = civic_report.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return report


@router.post("/reports/{report_id}/status")
def update_report_status_endpoint(
    report_id: str,
    body: ReportStatusUpdateIn,
    principal: dict = Depends(get_principal),
) -> Any:
    """Update report workflow status (operator or municipal officer action)."""
    try:
        updated = civic_report.update_report_status(
            report_id=report_id,
            new_status=body.status,
            notes=body.notes,
            principal_id=principal.get("id", "p_operator"),
        )
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Status update failed: {exc}")
