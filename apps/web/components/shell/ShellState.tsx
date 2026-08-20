"use client";

/**
 * ShellState — one place that knows whether the city is on fire, whether the
 * stream is live, and whether what you are looking at is real.
 *
 * It owns the single EventSource for the whole app (opening one per component
 * would hammer the API), and the single incident poll that feeds the critical
 * rail. Lane E can read it anywhere:
 *
 *   const { criticalIncidents, streamStatus, dataMode, refresh } = useShell();
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, useDataMode, useStream, type DataMode, type StreamStatus } from "@/lib/api";
import type { Incident, StreamEvent } from "@/lib/types";

interface ShellValue {
  incidents: Incident[];
  criticalIncidents: Incident[];
  streamStatus: StreamStatus;
  dataMode: DataMode;
  events: StreamEvent[];
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
  const [nonce, setNonce] = useState(0);
  const { events, status } = useStream();
  const dataMode = useDataMode();

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

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

  // Any incident frame on the stream invalidates the list. Cheap and correct.
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
      dataMode,
      events,
      refresh,
    }),
    [incidents, criticalIncidents, status, dataMode, events, refresh],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
