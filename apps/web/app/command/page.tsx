"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Layer } from "@deck.gl/core";
import { CityMap } from "@/components/map/CityMap";
import { IncidentCard } from "@/components/ui/IncidentCard";
import { MetricTile } from "@/components/ui/MetricTile";
import { Icon } from "@/components/ui/Icon";
import { useShell } from "@/components/shell/ShellState";
import { useApi } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { CITY } from "@/lib/fixtures";
import type { OpsMetrics } from "@/lib/types";
import s from "../pages.module.css";

const SEVERITY_TINT: Record<string, [number, number, number, number]> = {
  critical: [220, 38, 38, 220],
  major: [234, 88, 12, 220],
  minor: [202, 138, 4, 200],
  info: [59, 130, 246, 180],
};

export default function CommandCenter() {
  const { incidents, location } = useShell();
  const { data: ops } = useApi<OpsMetrics>("/v1/metrics/ops");
  const [layers, setLayers] = useState<Layer[]>([]);
  const ref = useGsap<HTMLElement>((_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }), []);

  const markers = useMemo(
    () =>
      incidents
        .map((i) => {
          const c = (i.geometry as { coordinates?: [number, number] } | null)?.coordinates;
          return c
            ? {
                id: i.id,
                label: i.title,
                detail: `${i.severity?.toUpperCase()} · ${i.state?.replace("_", " ")}`,
                coordinates: c,
              }
            : null;
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
          getRadius: 300,
          radiusMinPixels: 8,
          radiusMaxPixels: 28,
          stroked: true,
          lineWidthMinPixels: 2,
          getFillColor: (d: { severity: string }) => SEVERITY_TINT[d.severity] ?? [59, 130, 246, 180],
          getLineColor: [255, 255, 255, 240],
          pickable: true,
        }) as unknown as Layer,
      ]);
    });
    return () => {
      cancelled = true;
    };
  }, [markers, incidents]);

  const criticals = incidents.filter((i) => i.severity === "critical");
  const open = incidents.filter((i) => i.state !== "closed");

  return (
    <section className="container section" ref={ref} style={{ paddingBottom: "2rem" }}>
      <div className={`${s.pageHeader} js-reveal`} style={{ marginBottom: "0.85rem" }}>
        <div>
          <h1 style={{ fontSize: "1.45rem", margin: 0 }}>Command Center</h1>
          <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: "0.15rem 0 0 0" }}>
            Unified Municipal State · Live SCADA & GIS Telemetry · {location.name}, {location.state}
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Link href="/emergency" className="btn btn-sm btn-critical" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <Icon name="shield" size={15} />
            <span>Emergency 112 CAD</span>
          </Link>
          <Link href="/actions" className="btn btn-sm btn-secondary" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <Icon name="action" size={15} />
            <span>Action Queue</span>
          </Link>
        </div>
      </div>

      <div className={`${s.kpiStrip} js-reveal`} style={{ marginBottom: "1rem" }}>
        <MetricTile label="Active Incidents" value={String(open.length)} />
        <MetricTile label="Critical" value={String(criticals.length)} />
        <MetricTile label="Time to Detect" value={ops?.time_to_detect_s ? `${ops.time_to_detect_s}s` : "14s"} />
        <MetricTile label="Policy Blocks (24h)" value={String(ops?.policy_blocks_24h ?? 0)} />
        <MetricTile label="CAD Zone" value={location.cad_zone} />
        <MetricTile label="LLM Cost (24h)" value={ops?.llm_cost_usd !== undefined ? `$${ops.llm_cost_usd.toFixed(2)}` : "$0.12"} />
      </div>

      <div className={`${s.splitView} js-reveal`} style={{ gridTemplateColumns: "1.7fr 1fr", gap: "1rem" }}>
        <div style={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "8px", overflow: "hidden" }}>
          <div style={{ padding: "0.6rem 0.9rem", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {location.name} Vector Map & Telemetry
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
              {location.region}
            </span>
          </div>
          <CityMap
            layers={layers}
            markers={markers}
            interactive
            height="520px"
            summary={`${location.name} operational map`}
          />
        </div>

        <div className={s.rail} style={{ gap: "0.75rem" }}>
          <div className={s.card} style={{ padding: "0.9rem" }}>
            <h2 className={s.sectionTitle} style={{ margin: "0 0 0.65rem 0", fontSize: "0.8rem" }}>
              Priority Incidents ({open.length})
            </h2>
            {open.length === 0 && <p className={s.empty} style={{ padding: "1rem" }}>No open incidents.</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
              {open.map((inc) => (
                <IncidentCard key={inc.id} incident={inc} href={`/command/${inc.id}`} />
              ))}
            </div>
          </div>

          <div className={s.card} style={{ padding: "0.9rem" }}>
            <h2 className={s.sectionTitle} style={{ margin: "0 0 0.65rem 0", fontSize: "0.8rem" }}>
              Critical Infrastructure Status
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", fontSize: "0.78rem" }}>
              <div style={{ padding: "6px 8px", background: "rgba(0,0,0,0.02)", borderRadius: "6px", border: "1px solid var(--line)" }}>
                <div style={{ fontWeight: 600 }}>Gate BD-04</div>
                <div style={{ color: "#16a34a" }}>● Nominal (2.8m flow)</div>
              </div>
              <div style={{ padding: "6px 8px", background: "rgba(0,0,0,0.02)", borderRadius: "6px", border: "1px solid var(--line)" }}>
                <div style={{ fontWeight: 600 }}>Pump House P-12</div>
                <div style={{ color: "#16a34a" }}>● 4/4 Units Online</div>
              </div>
              <div style={{ padding: "6px 8px", background: "rgba(0,0,0,0.02)", borderRadius: "6px", border: "1px solid var(--line)" }}>
                <div style={{ fontWeight: 600 }}>Substation PK-3</div>
                <div style={{ color: "#16a34a" }}>● 33kV Operational</div>
              </div>
              <div style={{ padding: "6px 8px", background: "rgba(0,0,0,0.02)", borderRadius: "6px", border: "1px solid var(--line)" }}>
                <div style={{ fontWeight: 600 }}>ERSS 112 CAD</div>
                <div style={{ color: "#16a34a" }}>● Standby / Active</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
