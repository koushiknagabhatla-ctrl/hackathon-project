"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, useStream, type StreamStatus } from "@/lib/api";
import type { Incident, StreamEvent } from "@/lib/types";
import { DEFAULT_LOCATION, type IndiaLocation } from "@/lib/locations";

interface ShellValue {
  incidents: Incident[];
  criticalIncidents: Incident[];
  streamStatus: StreamStatus;
  events: StreamEvent[];
  location: IndiaLocation;
  weather: Record<string, any> | null;
  setLocation: (loc: IndiaLocation) => void;
  refresh: () => void;
}

const Ctx = createContext<ShellValue | null>(null);

export function useShell(): ShellValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useShell must be used inside <ShellStateProvider>");
  return ctx;
}

const OPEN_STATES = new Set([
  "detected",
  "assessing",
  "planning",
  "awaiting_approval",
  "acting",
  "verifying",
]);

export function ShellStateProvider({ children }: { children: ReactNode }) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [location, setLocationState] = useState<IndiaLocation>(DEFAULT_LOCATION);
  const [weather, setWeather] = useState<Record<string, any> | null>(null);
  const [nonce, setNonce] = useState(0);
  const { events, status } = useStream();

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  const setLocation = useCallback((newLoc: IndiaLocation) => {
    setLocationState(newLoc);
    // Persist preferred location
    if (typeof window !== "undefined") {
      localStorage.setItem("auralis_location", JSON.stringify(newLoc));
    }
  }, []);

  // Hydrate stored location if present
  useEffect(() => {
    try {
      const stored = localStorage.getItem("auralis_location");
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed?.coordinates) setLocationState(parsed);
      }
    } catch {
      /* ignore */
    }
  }, []);

  // Fetch real-world live weather whenever location changes
  useEffect(() => {
    let alive = true;
    const [lon, lat] = location.coordinates;
    api
      .get<Record<string, any>>(`/v1/weather/live?lat=${lat}&lon=${lon}`)
      .then((res) => {
        if (alive && res) setWeather(res);
      })
      .catch(() => {
        /* fallback handled gracefully */
      });
    return () => {
      alive = false;
    };
  }, [location]);

  useEffect(() => {
    let alive = true;
    api
      .get<Incident[]>("/v1/incidents")
      .then((list) => alive && setIncidents(Array.isArray(list) ? list : []))
      .catch(() => {
        /* degraded: the shell still renders, the rail just stays quiet */
      });
    return () => {
      alive = false;
    };
  }, [nonce]);

  const incidentFrames = events.filter((e) => e.type === "incident").length;
  useEffect(() => {
    if (incidentFrames > 0) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidentFrames]);

  const criticalIncidents = useMemo(
    () =>
      incidents.filter(
        (i) => i.severity === "critical" && OPEN_STATES.has(i.state),
      ),
    [incidents],
  );

  const value = useMemo(
    () => ({
      incidents,
      criticalIncidents,
      streamStatus: status,
      events,
      location,
      weather,
      setLocation,
      refresh,
    }),
    [incidents, criticalIncidents, status, events, location, weather, setLocation, refresh],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
