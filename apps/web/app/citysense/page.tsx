"use client";

/**
 * CitySense Pan-India Geospatial Intelligence Map — /citysense
 *
 * Visualizes real Indian cities across all 28 States and 8 Union Territories
 * using authoritative coordinates, GPU-accelerated zoom-based clustering,
 * real-time search, state filtering, and interactive city telemetry inspection.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api, useApi } from "@/lib/api";
import { MAP_STYLE, OSM_STYLE } from "@/components/map/CityMap";
import s from "./citysense.module.css";

interface IndianCity {
  id: string;
  name: string;
  state: string;
  district: string;
  lat: number;
  lon: number;
  population: number;
  tier: string;
  is_capital: boolean;
  zone: string;
  elevation_m: number;
}

interface StateInfo {
  name: string;
  city_count: number;
}

const ZONES = ["All", "Capital Region", "Coastal Andhra", "Rayalaseema", "North Coastal"];

export default function CitySensePage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedState, setSelectedState] = useState("All");
  const [selectedZone, setSelectedZone] = useState("All");
  const [selectedCity, setSelectedCity] = useState<IndianCity | null>(null);
  const [cityWeather, setCityWeather] = useState<any>(null);
  const [isLoadingWeather, setIsLoadingWeather] = useState(false);

  const mapHolder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  // Fetch Cities & States from Backend API
  const { data: citiesData, loading: citiesLoading } = useApi<{ count: number; total_available: number; cities: IndianCity[] }>("/v1/cities?limit=100");
  const { data: statesData } = useApi<{ count: number; states: StateInfo[] }>("/v1/cities/states");

  const allCities = citiesData?.cities || [];
  const states = statesData?.states || [];

  // Filtered Cities
  const filteredCities = useMemo(() => {
    return allCities.filter((c) => {
      if (selectedZone !== "All" && c.zone.toLowerCase() !== selectedZone.toLowerCase()) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        return (
          c.name.toLowerCase().includes(q) ||
          c.district.toLowerCase().includes(q) ||
          c.zone.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [allCities, selectedZone, searchQuery]);

  // GeoJSON data structure for clustering
  const geojsonData = useMemo(() => {
    return {
      type: "FeatureCollection" as const,
      features: filteredCities.map((c) => ({
        type: "Feature" as const,
        id: c.id,
        geometry: {
          type: "Point" as const,
          coordinates: [c.lon, c.lat],
        },
        properties: {
          id: c.id,
          name: c.name,
          state: c.state,
          district: c.district,
          population: c.population,
          tier: c.tier,
          is_capital: c.is_capital,
          zone: c.zone,
          elevation_m: c.elevation_m,
        },
      })),
    };
  }, [filteredCities]);

  // Initialize MapLibre GL
  useEffect(() => {
    let map: MapLibreMap | null = null;
    let cancelled = false;

    async function initMap() {
      const maplibregl = await import("maplibre-gl");
      if (cancelled || !mapHolder.current) return;

      map = new maplibregl.Map({
        container: mapHolder.current,
        style: MAP_STYLE,
        center: [80.6480, 16.5062], // Geographical center of Andhra Pradesh (Vijayawada / Amaravati)
        zoom: 7.2,
        minZoom: 6.0,
        maxZoom: 18,
        attributionControl: false,
      });
      mapRef.current = map;

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

      map.on("load", () => {
        if (cancelled || !map) return;

        // 1. Add Clustered GeoJSON Source
        map.addSource("cities-source", {
          type: "geojson",
          data: geojsonData,
          cluster: true,
          clusterMaxZoom: 12,
          clusterRadius: 50,
        });

        // 2. Cluster Circle Layer (Color graded by cluster size)
        map.addLayer({
          id: "clusters",
          type: "circle",
          source: "cities-source",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": [
              "step",
              ["get", "point_count"],
              "#fa8128", // Amber for small clusters
              10,
              "#e06a10", // Orange for medium clusters
              30,
              "#7a3400", // Dark Accent for large clusters
            ],
            "circle-radius": [
              "step",
              ["get", "point_count"],
              18,
              10,
              24,
              30,
              32,
            ],
            "circle-stroke-width": 3,
            "circle-stroke-color": "#ffffff",
          },
        });

        // 3. Cluster Count Label
        map.addLayer({
          id: "cluster-count",
          type: "symbol",
          source: "cities-source",
          filter: ["has", "point_count"],
          layout: {
            "text-field": "{point_count_abbreviated}",
            "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
            "text-size": 13,
          },
          paint: {
            "text-color": "#ffffff",
          },
        });

        // 4. Individual City Points (Unclustered)
        map.addLayer({
          id: "unclustered-point",
          type: "circle",
          source: "cities-source",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-color": [
              "case",
              ["get", "is_capital"],
              "#b3261e", // Red for Capitals
              ["==", ["get", "tier"], "Tier 1"],
              "#fa8128", // Orange for Tier 1 Metros
              "#1a6b32", // Green for Tier 2/3
            ],
            "circle-radius": [
              "case",
              ["get", "is_capital"],
              9,
              ["==", ["get", "tier"], "Tier 1"],
              8,
              6,
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff",
          },
        });

        // 5. City Name Labels on zoom >= 6
        map.addLayer({
          id: "city-labels",
          type: "symbol",
          source: "cities-source",
          filter: ["!", ["has", "point_count"]],
          minzoom: 5.5,
          layout: {
            "text-field": ["get", "name"],
            "text-font": ["Open Sans Regular", "Arial Unicode MS Regular"],
            "text-size": 11,
            "text-offset": [0, 1.2],
            "text-anchor": "top",
          },
          paint: {
            "text-color": "#2b2b2b",
            "text-halo-color": "#ffffff",
            "text-halo-width": 1.5,
          },
        });

        // Click on Cluster -> Zoom In
        map.on("click", "clusters", (e) => {
          const features = map?.queryRenderedFeatures(e.point, { layers: ["clusters"] });
          const firstFeature = features?.[0];
          const clusterId = firstFeature?.properties?.cluster_id;
          const source = map?.getSource("cities-source") as any;
          if (source && clusterId !== undefined && firstFeature) {
            source.getClusterExpansionZoom(clusterId, (err: any, zoom: number) => {
              if (err || !map) return;
              const coords = (firstFeature.geometry as any).coordinates;
              map.easeTo({ center: coords, zoom: Math.min(zoom, 14), duration: 500 });
            });
          }
        });

        // Click on City Marker -> Open Detail Drawer
        map.on("click", "unclustered-point", (e) => {
          const props = e.features?.[0]?.properties;
          if (props) {
            const city = allCities.find((c) => c.id === props.id) || (props as unknown as IndianCity);
            setSelectedCity(city);
            setCityWeather(null);
            if (city.lon && city.lat) {
              map?.easeTo({ center: [city.lon, city.lat], zoom: 9, duration: 600 });
            }
          }
        });

        // Cursor Pointer on Hover
        map.on("mouseenter", "clusters", () => {
          if (map) map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "clusters", () => {
          if (map) map.getCanvas().style.cursor = "";
        });
        map.on("mouseenter", "unclustered-point", () => {
          if (map) map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "unclustered-point", () => {
          if (map) map.getCanvas().style.cursor = "";
        });
      });
    }

    initMap();

    return () => {
      cancelled = true;
      map?.remove();
      mapRef.current = null;
    };
  }, [allCities]);

  // Update GeoJSON source data whenever filters change
  useEffect(() => {
    if (mapRef.current && mapRef.current.getSource("cities-source")) {
      const source = mapRef.current.getSource("cities-source") as any;
      source.setData(geojsonData);
    }
  }, [geojsonData]);

  // Query live weather for selected city
  const fetchCityWeather = async (c: IndianCity) => {
    setIsLoadingWeather(true);
    try {
      const res = await api.get<any>(`/v1/weather/current?lat=${c.lat}&lon=${c.lon}`);
      setCityWeather(res);
    } catch (err) {
      console.warn("Weather query failed:", err);
    } finally {
      setIsLoadingWeather(false);
    }
  };

  const handleCitySelect = (c: IndianCity) => {
    setSelectedCity(c);
    setCityWeather(null);
    if (mapRef.current) {
      mapRef.current.flyTo({ center: [c.lon, c.lat], zoom: 9.5, essential: true });
    }
  };

  return (
    <div className={s.citySensePage}>
      {/* Top Filter & Search Controls */}
      <div className={s.controlBar}>
        <div className={s.brandBadge}>
          <div className={s.brandIcon}>AP</div>
          <h1 className={s.brandTitle}>CitySense Andhra Pradesh</h1>
        </div>

        {/* Search Input */}
        <div className={s.searchWrapper}>
          <span className={s.searchIcon}>🔍</span>
          <input
            type="text"
            className={s.searchInput}
            placeholder="Search AP city, district, or municipal zone..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* AP Urban Zone Filter */}
        <select
          className={s.filterSelect}
          value={selectedZone}
          onChange={(e) => setSelectedZone(e.target.value)}
        >
          {ZONES.map((zn) => (
            <option key={zn} value={zn}>
              {zn === "All" ? "All AP Zones (26 Districts)" : `${zn} Zone`}
            </option>
          ))}
        </select>

        <div className={s.statsPill}>
          📍 {filteredCities.length} AP Urban Centers
        </div>
      </div>

      {/* Map View */}
      <div className={s.mapContainer}>
        <div ref={mapHolder} className={s.mapCanvas} />

        {/* Floating City Detail Drawer */}
        {selectedCity && (
          <div className={s.cityDrawer}>
            <div className={s.drawerHeader}>
              <div>
                <h2 className={s.drawerCityName}>{selectedCity.name}</h2>
                <div className={s.drawerState}>
                  {selectedCity.district} District, {selectedCity.state}
                </div>
              </div>
              <button
                type="button"
                className={s.closeDrawerBtn}
                onClick={() => setSelectedCity(null)}
                title="Close"
              >
                ×
              </button>
            </div>

            <div className={s.cityMetaGrid}>
              <div className={s.metaItem}>
                <span className={s.metaLabel}>Coordinates</span>
                <span className={s.metaVal}>
                  {selectedCity.lat.toFixed(4)}°N, {selectedCity.lon.toFixed(4)}°E
                </span>
              </div>
              <div className={s.metaItem}>
                <span className={s.metaLabel}>Population</span>
                <span className={s.metaVal}>
                  {selectedCity.population >= 1000000
                    ? `${(selectedCity.population / 1000000).toFixed(2)}M`
                    : `${(selectedCity.population / 1000).toFixed(0)}k`}
                </span>
              </div>
              <div className={s.metaItem}>
                <span className={s.metaLabel}>Tier / Type</span>
                <span className={s.metaVal}>
                  {selectedCity.is_capital ? "👑 Capital" : selectedCity.tier}
                </span>
              </div>
              <div className={s.metaItem}>
                <span className={s.metaLabel}>Elevation</span>
                <span className={s.metaVal}>{selectedCity.elevation_m}m MSL</span>
              </div>
            </div>

            {/* Live Weather Preview */}
            {cityWeather && (
              <div style={{ background: "var(--accent-wash)", padding: "10px", borderRadius: "8px", fontSize: "var(--fs-xs)", color: "var(--accent-ink)" }}>
                🌤️ <strong>Live Weather:</strong> {cityWeather.temperature}°C · Humidity {cityWeather.humidity}%
              </div>
            )}

            <div className={s.drawerActions}>
              <button
                type="button"
                className={s.primaryActionBtn}
                onClick={() => fetchCityWeather(selectedCity)}
                disabled={isLoadingWeather}
              >
                {isLoadingWeather ? "Querying Telemetry..." : "🌤️ Query Live Weather & Telemetry"}
              </button>
              <a
                href={`/routes?dest_lat=${selectedCity.lat}&dest_lon=${selectedCity.lon}`}
                className={s.secondaryActionBtn}
                style={{ textAlign: "center", textDecoration: "none" }}
              >
                🚗 Plan Safe Route To {selectedCity.name}
              </a>
            </div>
          </div>
        )}

        {/* Bottom Zone Bar */}
        <div className={s.zoneBar}>
          {ZONES.map((z) => (
            <button
              type="button"
              key={z}
              className={s.zoneBtn}
              data-active={selectedZone === z}
              onClick={() => setSelectedZone(z)}
            >
              {z}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
