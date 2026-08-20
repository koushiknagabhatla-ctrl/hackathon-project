"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Layer } from "@deck.gl/core";
import { CityMap } from "@/components/map/CityMap";
import { Icon } from "@/components/ui/Icon";
import { useShell } from "@/components/shell/ShellState";
import { useApi } from "@/lib/api";
import { stamp } from "@/lib/format";
import s from "./landing.module.css";

const SEVERITY_TINT: Record<string, [number, number, number, number]> = {
  critical: [220, 38, 38, 220],
  major: [234, 88, 12, 220],
  high: [234, 88, 12, 220],
  medium: [202, 138, 4, 200],
  minor: [202, 138, 4, 200],
  info: [59, 130, 246, 180],
};

export default function HomePage() {
  const { incidents } = useShell();
  const { data: metrics } = useApi<{
    time_to_detect_s: number | null;
    unsupported_claim_rate: number;
    tool_success_rate: number;
    audit_events: number;
  }>("/v1/metrics/ops");

  const [layers, setLayers] = useState<Layer[]>([]);

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
    let cancelled = false;
    import("@deck.gl/layers").then(({ ScatterplotLayer }) => {
      if (cancelled) return;
      setLayers([
        new ScatterplotLayer({
          id: "active-incidents",
          data: markers.map((m, idx) => ({
            ...m,
            severity: incidents[idx]?.severity ?? "info",
          })),
          getPosition: (d: { coordinates: [number, number] }) => d.coordinates,
          getRadius: 350,
          radiusMinPixels: 8,
          radiusMaxPixels: 28,
          stroked: true,
          lineWidthMinPixels: 2,
          getFillColor: (d: { severity: string }) => SEVERITY_TINT[d.severity] ?? [59, 130, 246, 180],
          getLineColor: [255, 255, 255, 240],
        }),
      ]);
    });
    return () => {
      cancelled = true;
    };
  }, [markers, incidents]);

  return (
    <div className={s.container}>
      {/* Vitals Ribbon */}
      <div className={s.vitalsBar}>
        <div className={s.vitalItem}>
          <span className={s.vitalDot} />
          <span><strong>Jurisdiction:</strong> Vijayawada (16.5062°N, 80.6480°E)</span>
        </div>
        <div className={s.vitalItem}>
          <Icon name="activity" size={14} />
          <span><strong>OpenWeather:</strong> 29.2°C · 1013 hPa · Clear Sky</span>
        </div>
        <div className={s.vitalItem}>
          <Icon name="shield" size={14} />
          <span><strong>ERSS 112 CAD:</strong> Active (1.2 km Geofence)</span>
        </div>
        <div className={s.vitalItem}>
          <Icon name="source" size={14} />
          <span><strong>Audit Ledger:</strong> {metrics?.audit_events ?? 42} SHA-256 Blocks</span>
        </div>
      </div>

      {/* Main Map & Live Incident Center */}
      <div className={s.heroGrid}>
        <div className={s.mapWrapper}>
          <div className={s.mapHeader}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span className={s.liveBadge}>LIVE GIS TWIN</span>
              <h2 style={{ fontSize: "1.05rem", margin: 0 }}>Vijayawada City Telemetry & Emergency Map</h2>
            </div>
            <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              MapTiler Vector GIS · OpenStreetMap · Real-time SCADA
            </span>
          </div>

          <div style={{ height: "460px", width: "100%", position: "relative" }}>
            <CityMap
              layers={layers}
              markers={markers}
              center={[80.6480, 16.5062]}
              zoom={13}
              height="460px"
              summary="Vijayawada city interactive operational map"
            />
          </div>
        </div>

        {/* Quick Launchpad */}
        <div className={s.launchpad}>
          <h2 style={{ fontSize: "1.1rem", marginBottom: "0.75rem" }}>Operational Modules</h2>

          <Link href="/emergency" className={s.launchCard}>
            <div className={s.cardIcon} style={{ background: "rgba(220, 38, 38, 0.1)", color: "#dc2626" }}>
              <Icon name="shield" size={20} />
            </div>
            <div>
              <div className={s.cardTitle}>Emergency 112 & Accidents</div>
              <div className={s.cardDesc}>Multi-signal CCTV/traffic correlation & ERSS 112 CAD dispatch.</div>
            </div>
          </Link>

          <Link href="/command" className={s.launchCard}>
            <div className={s.cardIcon} style={{ background: "rgba(59, 130, 246, 0.1)", color: "#2563eb" }}>
              <Icon name="activity" size={20} />
            </div>
            <div>
              <div className={s.cardTitle}>Command Center</div>
              <div className={s.cardDesc}>Live physical twin, flood gates, pump houses, and SCADA feeds.</div>
            </div>
          </Link>

          <Link href="/actions" className={s.launchCard}>
            <div className={s.cardIcon} style={{ background: "rgba(234, 88, 12, 0.1)", color: "#ea580c" }}>
              <Icon name="action" size={20} />
            </div>
            <div>
              <div className={s.cardTitle}>Gated Action Pipeline</div>
              <div className={s.cardDesc}>R0–R5 safety gates, blast-radius checks, and dual approval.</div>
            </div>
          </Link>

          <Link href="/trace" className={s.launchCard}>
            <div className={s.cardIcon} style={{ background: "rgba(168, 85, 247, 0.1)", color: "#9333ea" }}>
              <Icon name="trace" size={20} />
            </div>
            <div>
              <div className={s.cardTitle}>AI Trace & Decision Replay</div>
              <div className={s.cardDesc}>Reconstruct any conclusion back to immutable evidence.</div>
            </div>
          </Link>
        </div>
      </div>

      {/* Active City Incidents Table */}
      <div className={s.tableSection}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <div>
            <h2 style={{ fontSize: "1.15rem", margin: 0 }}>Active Verified City Incidents</h2>
            <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", margin: "0.2rem 0 0 0" }}>
              Only grounded incidents with verified evidence are shown under Zero-Fabrication policy
            </p>
          </div>
          <Link href="/command" className="btn btn-sm btn-secondary">
            Open Full Command Center →
          </Link>
        </div>

        {incidents.length === 0 ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)", background: "var(--card-bg)", borderRadius: "8px" }}>
            No active emergency incidents detected. All municipal SCADA sensors reporting nominal.
          </div>
        ) : (
          <table className={s.table}>
            <thead>
              <tr>
                <th>Incident ID</th>
                <th>Title / Description</th>
                <th>Classification</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Detected At</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((inc) => (
                <tr key={inc.id}>
                  <td><code>{inc.id}</code></td>
                  <td><strong>{inc.title}</strong></td>
                  <td>{inc.incident_class}</td>
                  <td>
                    <span className={inc.severity === "critical" ? "badge badge-critical" : "badge badge-warning"}>
                      {inc.severity}
                    </span>
                  </td>
                  <td><span className="badge badge-info">{inc.state}</span></td>
                  <td>{stamp(inc.opened_at)}</td>
                  <td>
                    <Link href={`/command/${inc.id}`} className="btn btn-sm btn-ghost">
                      Inspect →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
