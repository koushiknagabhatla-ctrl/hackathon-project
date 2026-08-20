# 0006 — SQLite + Shapely/GEOS instead of PostgreSQL/PostGIS for the slice

**Status:** Accepted (slice-scoped)

## Context
The obvious municipal-GIS stack is PostgreSQL + PostGIS. This build ships
SQLite. That deserves a plain statement of what is equivalent and what is not,
because "we used SQLite" is otherwise read as "the spatial results are toys".

## Decision
- **Storage engine:** SQLite in WAL mode, schema at `services/api/schema.sql`.
  Geometry is stored as GeoJSON text in EPSG:4326.
- **Geometry engine:** Shapely + GEOS, with pyproj for anything metric — via
  `core/geo.py`, which is the only module allowed to touch coordinates. No
  hand-rolled lat/lon arithmetic anywhere.

### What is genuinely equivalent
PostGIS's spatial predicates *are* GEOS. `ST_Contains`, `ST_Intersects`,
`ST_Distance` and buffering are the same C++ library this build calls through
Shapely. A containment or distance result here is the same result PostGIS
would produce for the same geometries.

`core/geo.py` is in one respect stricter than a careless PostGIS deployment:
distances are geodesic on the WGS84 ellipsoid (`pyproj.Geod.inv`), and metric
buffers project into a local azimuthal-equidistant CRS centred on the input
geometry rather than using EPSG:3857 — whose scale error is `1/cos(lat)`, about
19% wrong at Vijayawada's latitude (16.5°N) and 30% at 40°N. Stored geometries
also carry `geometry_accuracy_m`, combined in quadrature by `uncertainty_m()`
so a proximity threshold is never tighter than the source data supports.

### What is genuinely NOT equivalent
1. **No spatial index.** PostGIS has GiST; this build has none. Spatial
   candidate selection is a table scan plus in-process GEOS. Fine over hundreds
   of assets, wrong over hundreds of thousands.
2. **One writer.** `core/db.py` holds a single module-level connection behind
   a re-entrant lock. Every write serialises. A second uvicorn worker is not
   protected by that lock at all — this build is a single-process deployment.
3. **No spatial SQL.** You cannot push a spatial predicate into a query plan.
   Geometry-filtered joins load rows and filter in Python.
4. **No raster, no topology, no `ST_*` in views**, no PostGIS-native tiling.
5. **No PITR, no streaming replication, no row-level security.** Tenant
   isolation is application-level (a required `tenant_id` argument on every
   `repo.py` list function), not a database guarantee.

## Consequences
- Zero-install demo: `python -m pip install -r requirements.txt` and run. No
  Docker, no database server, no PostGIS extension build.
- Spatial correctness claims hold; spatial *scale* claims do not.
- The swap is contained: `core/db.py` and `core/repo.py` are the only modules
  that speak SQL. `core/geo.py` does not change at all, because GEOS does not
  change.

## Earned-complexity trigger
Swap to PostgreSQL + PostGIS at the **first** of:
- **more than one API worker process** (i.e. any real concurrency — the single
  in-process write lock stops being a correctness mechanism);
- **>50k assets or >5M evidence rows**, where the absent spatial index and the
  table-scan candidate selection dominate query time;
- **any requirement for point-in-time recovery, replication, or database-
  enforced tenant isolation** — all three are compliance requirements, not
  performance ones (see `docs/compliance-map.md`);
- **>20 writes/second sustained** at ingest.

Migration scope: reimplement `core/db.py` and `core/repo.py`, move the
`geometry` TEXT columns to `geography(4326)`, add GiST indexes. `core/geo.py`,
`core/policy.py`, `core/gateway.py`, `core/risk.py` and every agent are
untouched.
