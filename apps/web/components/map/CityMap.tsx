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
import type {
  Map as MapLibreMap,
  StyleSpecification,
  IControl as MapLibreIControl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Icon } from "@/components/ui/Icon";
import { revealMap } from "@/lib/motion";
import { useShell } from "@/components/shell/ShellState";
import s from "./map.module.css";

/**
 * Primary basemap: OpenFreeMap "liberty". Keyless, free, no account, nothing
 * to configure and nothing that can rate-limit us mid-demonstration.
 */
const OPENFREEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

/** First fallback: raw OSM raster tiles. Different host, different failure mode. */
const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    "osm-tiles": {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap Contributors",
    },
  },
  layers: [
    {
      id: "osm-tiles-layer",
      type: "raster",
      source: "osm-tiles",
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

/**
 * Last resort: an empty style with no network dependency at all. The map is
 * never a single point of failure, so when both tile hosts are unreachable the
 * canvas still exists, every deck.gl data layer still draws on it, and the
 * component says the basemap is unavailable rather than pretending otherwise.
 */
const BLANK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "blank",
      type: "background",
      paint: { "background-color": "#ececec" },
    },
  ],
};

const MAP_STYLE: string | StyleSpecification =
  process.env.NEXT_PUBLIC_MAP_STYLE ?? OPENFREEMAP_STYLE;

/**
 * MapLibre and deck.gl both require WebGL2. Old hardware, a driver on Chrome's
 * blocklist, a VM or a hardened browser will not have it.
 *
 * This is checked BEFORE constructing the map because the constructor throws
 * part-way through setup: the object exists but its painter does not, so the
 * failure arrives as an unhandled rejection and the half-built map throws again
 * from its own `remove()` during cleanup.
 */
function hasWebGL2(): boolean {
  try {
    return !!document.createElement("canvas").getContext("webgl2");
  } catch {
    return false;
  }
}

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
  center,
  zoom,
  height = "min(60vh, 560px)",
  summary,
  interactive = true,
  onReady,
  className,
}: CityMapProps) {
  const { location } = useShell();
  const activeCenter = center ?? location.coordinates;
  const activeZoom = zoom ?? location.zoom;

  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<{ setProps: (p: { layers: Layer[] }) => void } | null>(null);
  // "unsupported" is distinct from "unavailable": no WebGL2 means the deck.gl
  // data layers cannot draw either, so the reassuring "data layers are still
  // live" note would be untrue.
  const [basemap, setBasemap] =
    useState<"loading" | "ok" | "unavailable" | "unsupported">("loading");

  useEffect(() => {
    let cancelled = false;
    let map: MapLibreMap | null = null;
    let tileTimer: ReturnType<typeof setTimeout> | null = null;

    if (!hasWebGL2()) {
      setBasemap("unsupported");
      return;
    }

    (async () => {
      const [maplibreglModule, { MapboxOverlay }] = await Promise.all([
        import("maplibre-gl"),
        import("@deck.gl/mapbox"),
      ]);
      // maplibre-gl v5 ships named exports and no default, so reaching for
      // `.default` yields undefined and the Map constructor blows up at runtime.
      const maplibregl = maplibreglModule;
      if (cancelled || !holder.current) return;

      try {
        map = new maplibregl.Map({
          container: holder.current,
          style: MAP_STYLE,
          center: activeCenter,
          zoom: activeZoom,
          attributionControl: false,
          interactive,
        });
      } catch {
        // WebGL2 present but unusable (blocklisted driver, lost context).
        map = null;
        setBasemap("unsupported");
        return;
      }
      mapRef.current = map;

      if (interactive && map) {
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      }

      const overlay = new MapboxOverlay({ interleaved: false, layers });
      if (map) {
        map.addControl(overlay as unknown as MapLibreIControl);
      }
      overlayRef.current = overlay as unknown as {
        setProps: (p: { layers: Layer[] }) => void;
      };

      // Degrade ladder, one rung per failure. The data layers survive all of it.
      let rung = 0;
      const degrade = () => {
        if (cancelled || !map || rung >= 2) return;
        rung += 1;
        try {
          map.setStyle(rung === 1 ? OSM_STYLE : BLANK_STYLE);
          setBasemap(rung === 1 ? "loading" : "unavailable");
        } catch {
          setBasemap("unavailable");
        }
      };

      if (map) {
        // If the style has not painted within 6s, treat it as failed rather
        // than leaving an operator staring at an empty rectangle.
        tileTimer = setTimeout(() => {
          if (!cancelled) degrade();
        }, 6000);

        map.on("error", (e: unknown) => {
          const err = e as { error?: { message?: string }; message?: string };
          const msg = String(err?.error?.message ?? err?.message ?? "");
          // Only the root style failing is fatal. A single missing tile is not.
          if (
            msg.includes("Failed to fetch") ||
            msg.includes("style") ||
            msg.includes("401") ||
            msg.includes("403")
          ) {
            degrade();
          }
        });

        map.on("load", () => {
          if (cancelled || !map) return;
          if (tileTimer) clearTimeout(tileTimer);
          setBasemap(rung >= 2 ? "unavailable" : "ok");
          revealMap(holder.current);
          onReady?.(map);
        });
      }
    })().catch(() => {
      if (!cancelled) setBasemap("unsupported");
    });

    return () => {
      cancelled = true;
      if (tileTimer) clearTimeout(tileTimer);
      overlayRef.current = null;
      // A map that failed mid-construction throws from its own remove().
      try {
        map?.remove();
      } catch {
        /* nothing left to tear down */
      }
      mapRef.current = null;
    };
    // Layers are pushed through the overlay below, not by rebuilding the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    overlayRef.current?.setProps({ layers });
  }, [layers]);

  useEffect(() => {
    if (!mapRef.current) return;
    try {
      mapRef.current.flyTo({
        center: activeCenter,
        zoom: activeZoom,
        duration: 1200,
        essential: true,
      });
    } catch {
      /* map torn down between render and effect */
    }
  }, [activeCenter, activeZoom]);

  return (
    <div className={`${s.wrap} ${className ?? ""}`} style={{ height }}>
      {basemap === "unavailable" && <div className={s.fallbackGrid} aria-hidden="true" />}
      <div className={s.canvas} ref={holder} />

      {basemap === "unavailable" && (
        <p className={s.note} role="status">
          <Icon name="offline" size={13} />
          Basemap unavailable. Data layers are still live and correct.
        </p>
      )}
      {basemap === "unsupported" && (
        <p className={s.unsupportedNote} role="status">
          <Icon name="offline" size={13} />
          <span>
            This map needs WebGL2, which this browser or device does not
            provide. The same data is listed below.
          </span>
        </p>
      )}
      {basemap === "ok" && (
        <p className={s.attrib}>
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
      <div className={basemap === "unsupported" ? s.textFallback : "sr-only"}>
        <p>
          Map of {location.name}, {location.state}.{summary ? ` ${summary}.` : ""}
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
