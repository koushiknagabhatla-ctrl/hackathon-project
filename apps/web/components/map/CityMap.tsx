"use client";

/**
 * CityMap — MapLibre basemap + deck.gl operational overlays, centred on
 * Vijayawada.
 *
 * RESILIENCE IS THE POINT: if the basemap tiles fail — offline laptop, blocked
 * network, dead CDN — the map does NOT become a grey box. It swaps to a local
 * style with no network dependency, keeps rendering every deck.gl data layer
 * and every marker, and shows a quiet "basemap unavailable" note. The rest of
 * the screen never depends on this component succeeding.
 *
 * Lane E usage:
 *   <CityMap
 *     layers={[new GeoJsonLayer({ id: "flood", data: extent, ... })]}
 *     markers={incidents.map(i => ({ id: i.id, label: i.title, coordinates: c(i) }))}
 *     summary="3 incidents, 1 flood extent polygon"
 *     height="min(64vh, 620px)"
 *   />
 *
 * maplibre-gl and deck.gl are imported dynamically so they never touch the
 * server bundle and never block first paint.
 */

import { useEffect, useRef, useState } from "react";
import type { Layer } from "@deck.gl/core";
import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Icon } from "@/components/ui/Icon";
import { revealMap } from "@/lib/motion";
import { CITY } from "@/lib/fixtures";
import s from "./map.module.css";

const MAPTILER_KEY = process.env.NEXT_PUBLIC_MAPTILER_KEY;

export const MAP_STYLE =
  process.env.NEXT_PUBLIC_MAP_STYLE ??
  (MAPTILER_KEY
    ? `https://api.maptiler.com/maps/dataviz-dark/style.json?key=${MAPTILER_KEY}`
    : "https://tiles.openfreemap.org/styles/liberty");

/** Zero-network style. Same projection, same deck.gl layers, no tiles. */
const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "ground",
      type: "background",
      paint: { "background-color": "#ECECEC" },
    },
  ],
};

export interface CityMapMarker {
  id: string;
  label: string;
  coordinates: [number, number];
  /** Rendered as the marker's accessible description. */
  detail?: string;
}

export interface CityMapProps {
  /** deck.gl layers, most important first — they fade in in that order. */
  layers?: Layer[];
  markers?: CityMapMarker[];
  center?: [number, number];
  zoom?: number;
  height?: string;
  /** One line describing what is currently drawn, for screen readers. */
  summary?: string;
  interactive?: boolean;
  onReady?: (map: MapLibreMap) => void;
  className?: string;
}

export function CityMap({
  layers = [],
  markers = [],
  center = CITY.centre,
  zoom = CITY.zoom,
  height = "min(60vh, 560px)",
  summary,
  interactive = true,
  onReady,
  className,
}: CityMapProps) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<{ setProps: (p: { layers: Layer[] }) => void } | null>(null);
  const [basemap, setBasemap] = useState<"loading" | "ok" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    let map: MapLibreMap | null = null;

    (async () => {
      const [maplibreglModule, { MapboxOverlay }] = await Promise.all([
        import("maplibre-gl"),
        import("@deck.gl/mapbox"),
      ]);
      const maplibregl = ((maplibreglModule as any).default || maplibreglModule) as typeof import("maplibre-gl");
      if (cancelled || !holder.current) return;

      map = new maplibregl.Map({
        container: holder.current,
        style: MAP_STYLE,
        center,
        zoom,
        attributionControl: false,
        interactive,
      });
      mapRef.current = map;

      if (interactive && map) {
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      }

      const overlay = new MapboxOverlay({ interleaved: false, layers });
      if (map) {
        map.addControl(overlay as any);
      }
      overlayRef.current = overlay as unknown as {
        setProps: (p: { layers: Layer[] }) => void;
      };

      let degraded = false;
      const degrade = () => {
        if (degraded || cancelled || !map) return;
        degraded = true;
        setBasemap("unavailable");
        try {
          map.setStyle(OFFLINE_STYLE);
        } catch {
          /* the overlay still renders even if the style swap is refused */
        }
      };

      // A style or tile failure must never take the screen down.
      if (map) {
        map.on("error", (e: any) => {
          const msg = String(e?.error?.message ?? e?.message ?? "");
          if (/style|tile|source|fetch|network|Failed/i.test(msg)) degrade();
        });

        map.on("load", () => {
          if (cancelled || !map) return;
          setBasemap((b) => (b === "unavailable" ? b : "ok"));
          revealMap(holder.current);
          onReady?.(map);
        });
      }

      // If nothing has loaded after 6s, assume the tiles are not coming.
      setTimeout(() => {
        if (!cancelled && map && !map.loaded()) degrade();
      }, 6000);
    })();

    return () => {
      cancelled = true;
      overlayRef.current = null;
      map?.remove();
      mapRef.current = null;
    };
    // Layers are pushed through the overlay below, not by rebuilding the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    overlayRef.current?.setProps({ layers });
  }, [layers]);

  useEffect(() => {
    mapRef.current?.easeTo({ center, zoom, duration: 700 });
  }, [center, zoom]);

  return (
    <div className={`${s.wrap} ${className ?? ""}`} style={{ height }}>
      {basemap === "unavailable" && <div className={s.fallbackGrid} aria-hidden="true" />}
      <div className={s.canvas} ref={holder} />

      {basemap === "unavailable" && (
        <p className={s.note} role="status">
          <Icon name="offline" size={13} />
          Basemap unavailable — data layers still live
        </p>
      )}
      {basemap === "ok" && (
        <p className={s.attrib} aria-hidden="true">
          <a href="https://openfreemap.org" target="_blank" rel="noreferrer">
            OpenFreeMap
          </a>{" "}
          ·{" "}
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
            OpenStreetMap
          </a>
        </p>
      )}

      {/* The map's content, in text. A canvas is invisible to a screen reader. */}
      <div className="sr-only">
        <p>
          Map of {CITY.name}, {CITY.region}.{summary ? ` ${summary}.` : ""}
          {basemap === "unavailable"
            ? " The basemap could not load; data layers are drawn on a plain background."
            : ""}
        </p>
        {markers.length > 0 && (
          <ul>
            {markers.map((m) => (
              <li key={m.id}>
                {m.label}
                {m.detail ? `. ${m.detail}` : ""}. Located at{" "}
                {m.coordinates[1].toFixed(4)} north, {m.coordinates[0].toFixed(4)} east.
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default CityMap;
