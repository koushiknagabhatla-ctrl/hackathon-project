"""Geometry. Shapely (GEOS) + pyproj only — no hand-rolled lat/lon math.

CRS contract for this module:
  * Every GeoJSON dict in or out is **EPSG:4326**, lon/lat in degrees. That is
    what schema.sql stores in the `geometry` TEXT columns.
  * Every distance is **metres on the WGS84 ellipsoid** (pyproj.Geod, geodesic).
  * Metric operations that need a plane (buffering) project into a local
    azimuthal-equidistant CRS centred on the input, then project back. EPSG:3857
    is deliberately NOT used: its scale error is 1/cos(lat), which is ~30% wrong
    at 40 deg latitude for a metre buffer.

Accuracy: `asset.geometry_accuracy_m` is the 1-sigma positional error of a
stored geometry. Distances derived from such geometries carry that error —
combine with `uncertainty_m()` and attach `accuracy_note()` to anything that
gets shown to a human or used as a detection threshold.
"""

from __future__ import annotations

import json
import math
from typing import Any

from pyproj import CRS, Geod, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import nearest_points, transform

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")


def shape_of(geojson: Any):
    """GeoJSON dict / Feature / stored TEXT column / shapely geom -> shapely geom.
    Coordinates are interpreted as EPSG:4326 (lon, lat)."""
    if geojson is None:
        raise ValueError("geometry is required")
    if hasattr(geojson, "geom_type"):
        return geojson
    if isinstance(geojson, (str, bytes)):
        geojson = json.loads(geojson)
    if geojson.get("type") == "Feature":
        geojson = geojson["geometry"]
    return shape(geojson)


def to_geojson(geom) -> dict[str, Any]:
    """shapely geom (EPSG:4326) -> GeoJSON dict."""
    return json.loads(json.dumps(mapping(geom)))


def contains(poly_geojson: Any, point_geojson: Any) -> bool:
    """Topological containment in EPSG:4326. No metric involved, so degrees are
    the correct space for this predicate."""
    return shape_of(poly_geojson).contains(shape_of(point_geojson))


def distance_m(a: Any, b: Any) -> float:
    """Geodesic distance in metres between two EPSG:4326 geometries.

    Point-to-point is exact (pyproj.Geod.inv on the WGS84 ellipsoid). For
    non-point geometries the nearest pair of points is found by GEOS in degree
    space first, which can pick a slightly different pair than a true geodesic
    nearest-point search on very large or elongated shapes — irrelevant at the
    city scale this system works at (<50 km).
    """
    ga, gb = shape_of(a), shape_of(b)
    pa, pb = nearest_points(ga, gb)
    return float(GEOD.inv(pa.x, pa.y, pb.x, pb.y)[2])


def _aeqd(lon: float, lat: float) -> CRS:
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs"
    )


def buffer_m(geojson: Any, metres: float) -> dict[str, Any]:
    """Buffer an EPSG:4326 geometry by `metres`, returning EPSG:4326 GeoJSON.
    Buffering happens in a local azimuthal-equidistant metre CRS centred on the
    geometry's centroid, so the radius is true metres in every direction."""
    geom = shape_of(geojson)
    c = geom.centroid
    crs = _aeqd(c.x, c.y)
    fwd = Transformer.from_crs(WGS84, crs, always_xy=True).transform
    rev = Transformer.from_crs(crs, WGS84, always_xy=True).transform
    return to_geojson(transform(rev, transform(fwd, geom).buffer(metres)))


def centroid(geojson: Any) -> dict[str, Any]:
    """Centroid as EPSG:4326 GeoJSON Point."""
    return to_geojson(shape_of(geojson).centroid)


def uncertainty_m(*accuracy_m: float | None) -> float:
    """Combine 1-sigma positional accuracies in quadrature (RSS)."""
    vals = [float(a) for a in accuracy_m if a]
    return math.sqrt(sum(v * v for v in vals)) if vals else 0.0


def accuracy_note(*accuracy_m: float | None) -> str:
    """Human-readable accuracy caveat for a distance derived from stored
    geometry. Attach wherever `geometry_accuracy_m` was involved."""
    u = uncertainty_m(*accuracy_m)
    if not u:
        return "geodesic WGS84 distance; source geometry accuracy not recorded"
    return f"geodesic WGS84 distance, +/-{u:.1f} m from source geometry accuracy"


def within_m(a: Any, b: Any, metres: float, *accuracy_m: float | None) -> bool:
    """True when a and b are within `metres`, widened by combined source
    geometry accuracy so a threshold is never tighter than the data supports."""
    return distance_m(a, b) <= metres + uncertainty_m(*accuracy_m)


def point(lon: float, lat: float) -> dict[str, Any]:
    """EPSG:4326 Point GeoJSON. lon first — GeoJSON axis order."""
    return {"type": "Point", "coordinates": [lon, lat]}
