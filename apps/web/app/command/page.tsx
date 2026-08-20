"use client";

/**
 * Command Center — unified city state, map/twin, incidents, trust posture.
 * Primary operational home. Optimise for scan speed over decoration.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Layer } from "@deck.gl/core";
import { CityMap } from "@/components/map/CityMap";
import { IncidentCard } from "@/components/ui/IncidentCard";
import { MetricTile } from "@/components/ui/MetricTile";
import { useShell } from "@/components/shell/ShellState";
import { useApi } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { CITY } from "@/lib/fixtures";
import { formatAge } from "@/lib/format";
import type { OpsMetrics } from "@/lib/types";
import s from "../pages.module.css";

const SEVERITY_TINT: Record<string, [number, number, number, number]> = {
  critical: [180, 35, 24, 190],
  major: [250, 129, 40, 190],
  minor: [138, 90, 0, 170],
  info: [91, 91, 91, 150],
};

export default function CommandCenter() {
  const { incidents } = useShell();
  const { data: ops } = useApi<OpsMetrics>("/v1/metrics/ops");
  const [layers, setLayers] = useState<Layer[]>([]);
  const ref = useGsap<HTMLElement>((_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }), []);

  const markers = useMemo(
    () =>
      incidents
        .map((i) => {
          const c = (i.geometry as { coordinates?: [number, number] } | null)?.coordinates;
          return c ? { id: i.id, label: i.title, detail: `${i.severity} · ${i.state.replace("_", " ")}`, coordinates: c } : null;
        })
        .filter((m): m is NonNullable<typeof m> => m !== null),
    [incidents],
  );

  useEffect(() => {
    if (!markers.length) return;
    let cancelled = false;
    import("@deck.gl/layers").then(({ ScatterplotLayer }) => {
      if (cancelled) return;
      setLayers([
        new ScatterplotLayer({
          id: "incidents",
          data: markers.map((m, i) => ({ ...m, severity: incidents[i]?.severity ?? "info" })),
          getPosition: (d: { coordinates: [number, number] }) => d.coordinates,
          getRadius: 260,
          radiusMinPixels: 7,
          radiusMaxPixels: 26,
          stroked: true,
          lineWidthMinPixels: 2,
          getFillColor: (d: { severity: string }) => SEVERITY_TINT[d.severity] ?? [91, 91, 91, 140],
          getLineColor: [17, 17, 17, 200],
          pickable: false,
        }) as unknown as Layer,
      ]);
    });
    return () => { cancelled = true; };
  }, [markers, incidents]);

  const criticals = incidents.filter((i) => i.severity === "critical");
  const open = incidents.filter((i) => i.state !== "closed");

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <h1>Command Center</h1>
        <span className="label">{CITY.name} · {CITY.region}</span>
      </div>

      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile label="Open incidents" value={String(open.length)} />
        <MetricTile label="Critical" value={String(criticals.length)} />
        <MetricTile label="Time to detect" value={ops?.time_to_detect_s ? `${ops.time_to_detect_s}s` : "—"} />
        <MetricTile label="Policy blocks (24h)" value={String(ops?.policy_blocks_24h ?? "—")} />
        <MetricTile label="LLM cost" value={ops?.llm_cost_usd !== undefined ? `$${ops.llm_cost_usd.toFixed(2)}` : "—"} />
      </div>

      <div className={`${s.splitView} js-reveal`}>
        <CityMap layers={layers} markers={markers} interactive height="min(56vh, 500px)" summary={`${markers.length} incidents on the city map`} />
        <div className={s.rail}>
          <h2 className={s.sectionTitle}>Priority incidents</h2>
          {open.length === 0 && <p className={s.empty}>No open incidents.</p>}
          {open.map((inc) => (
            <Link key={inc.id} href={`/command/${inc.id}`} style={{ textDecoration: "none", color: "inherit" }}>
              <IncidentCard incident={inc} />
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
