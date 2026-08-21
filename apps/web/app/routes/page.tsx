"use client";

/**
 * Auralis Safe Routing & Traffic Intelligence — /routes
 *
 * Provides dynamic hazard-avoidance routing (avoiding floods, accidents,
 * and road blockages) along with real-time municipal traffic corridor monitoring.
 */

import { useCallback, useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import s from "./routes.module.css";

interface RouteStep {
  instruction: string;
  distance_m: number;
  duration_s: number;
  name: string;
}

interface RouteResult {
  distance_km: number;
  duration_min: number;
  geometry: { type: string; coordinates: number[][] };
  steps: RouteStep[];
  hazard_avoidance: boolean;
  hazards_avoided: Array<{ id: string; title: string; severity: string; type: string }>;
  risk_level: "low" | "medium" | "high" | "critical";
  provider: string;
}

interface TrafficCorridor {
  id: string;
  name: string;
  from: string;
  to: string;
  length_km: number;
  current_speed_kph: number;
  free_flow_speed_kph: number;
  speed_ratio: number;
  level_of_service: "A" | "B" | "C" | "D" | "E" | "F";
  congestion_index: number;
  travel_time_min: number;
  delay_min: number;
  status: "clear" | "moderate" | "congested";
  updated_at: string;
}

const PRESETS = [
  { name: "Benz Circle", lat: 16.5062, lon: 80.6480 },
  { name: "Railway Station", lat: 16.5180, lon: 80.6200 },
  { name: "PNBS Bus Station", lat: 16.5120, lon: 80.6180 },
  { name: "GGH Hospital", lat: 16.5190, lon: 80.6350 },
  { name: "AIIMS Mangalagiri", lat: 16.4420, lon: 80.5650 },
  { name: "Airport (Gannavaram)", lat: 16.5300, lon: 80.7960 },
  { name: "Kanaka Durga Temple", lat: 16.5150, lon: 80.6050 },
  { name: "Auto Nagar", lat: 16.4950, lon: 80.6720 },
];

export default function RoutesPage() {
  const [originIndex, setOriginIndex] = useState(0);
  const [destIndex, setDestIndex] = useState(1);
  const [originLat, setOriginLat] = useState(PRESETS[0].lat);
  const [originLon, setOriginLon] = useState(PRESETS[0].lon);
  const [destLat, setDestLat] = useState(PRESETS[1].lat);
  const [destLon, setDestLon] = useState(PRESETS[1].lon);
  const [avoidHazards, setAvoidHazards] = useState(true);

  const [routeResult, setRouteResult] = useState<RouteResult | null>(null);
  const [isCalculating, setIsCalculating] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);

  // Live Traffic Corridors
  const { data: trafficData, loading: trafficLoading, reload: reloadTraffic } = useApi<{ corridors: TrafficCorridor[]; count: number }>("/v1/traffic/corridors");

  const calculateRoute = useCallback(async () => {
    setIsCalculating(true);
    setRouteError(null);

    try {
      const res = await api.post<RouteResult>("/v1/routes/safe", {
        origin_lat: originLat,
        origin_lon: originLon,
        dest_lat: destLat,
        dest_lon: destLon,
        avoid_hazards: avoidHazards,
      });
      setRouteResult(res);
    } catch (err: any) {
      setRouteError(err?.message || "Failed to calculate route");
    } finally {
      setIsCalculating(false);
    }
  }, [originLat, originLon, destLat, destLon, avoidHazards]);

  // Initial calculation
  useEffect(() => {
    calculateRoute();
  }, []);

  const handleOriginPreset = (p: typeof PRESETS[0]) => {
    setOriginLat(p.lat);
    setOriginLon(p.lon);
  };

  const handleDestPreset = (p: typeof PRESETS[0]) => {
    setDestLat(p.lat);
    setDestLon(p.lon);
  };

  const corridors = trafficData?.corridors || [];

  return (
    <div className={s.routesPage}>
      {/* Header */}
      <div className={s.pageHeader}>
        <h1>Safe Routing & Traffic Intelligence</h1>
        <p>
          Dynamic turn-by-turn navigation with real-time flood & incident avoidance,
          coupled with Level of Service (LOS) congestion tracking across primary arterial corridors.
        </p>
      </div>

      <div className={s.layoutGrid}>
        {/* Left Column: Route Planner & Navigation */}
        <div className={s.panel}>
          <h2 className={s.panelTitle}>
            <span>🧭</span> Safe Navigation Planner
          </h2>

          {/* Origin Selection */}
          <div className={s.formGroup}>
            <label className={s.label}>Origin Location</label>
            <div className={s.presetGrid}>
              {PRESETS.slice(0, 4).map((p) => (
                <button
                  type="button"
                  key={`orig-${p.name}`}
                  className={s.presetBtn}
                  style={originLat === p.lat ? { borderColor: "var(--accent)", color: "var(--accent-ink)", fontWeight: 600 } : {}}
                  onClick={() => handleOriginPreset(p)}
                >
                  {p.name}
                </button>
              ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
              <input
                type="number"
                step="0.0001"
                className={s.input}
                value={originLat}
                onChange={(e) => setOriginLat(parseFloat(e.target.value))}
                placeholder="Origin Lat"
              />
              <input
                type="number"
                step="0.0001"
                className={s.input}
                value={originLon}
                onChange={(e) => setOriginLon(parseFloat(e.target.value))}
                placeholder="Origin Lon"
              />
            </div>
          </div>

          {/* Destination Selection */}
          <div className={s.formGroup}>
            <label className={s.label}>Destination Location</label>
            <div className={s.presetGrid}>
              {PRESETS.slice(4).map((p) => (
                <button
                  type="button"
                  key={`dest-${p.name}`}
                  className={s.presetBtn}
                  style={destLat === p.lat ? { borderColor: "var(--accent)", color: "var(--accent-ink)", fontWeight: 600 } : {}}
                  onClick={() => handleDestPreset(p)}
                >
                  {p.name}
                </button>
              ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
              <input
                type="number"
                step="0.0001"
                className={s.input}
                value={destLat}
                onChange={(e) => setDestLat(parseFloat(e.target.value))}
                placeholder="Dest Lat"
              />
              <input
                type="number"
                step="0.0001"
                className={s.input}
                value={destLon}
                onChange={(e) => setDestLon(parseFloat(e.target.value))}
                placeholder="Dest Lon"
              />
            </div>
          </div>

          {/* Hazard Avoidance Toggle */}
          <div className={s.switchRow}>
            <div className={s.switchLabel}>
              <strong>🛡️ Active Hazard Avoidance</strong>
              <span>Automatically divert around floods, accidents, and road blocks</span>
            </div>
            <input
              type="checkbox"
              className={s.switchInput}
              checked={avoidHazards}
              onChange={(e) => setAvoidHazards(e.target.checked)}
            />
          </div>

          {/* Action Button */}
          <button
            type="button"
            className={s.calculateBtn}
            onClick={calculateRoute}
            disabled={isCalculating}
          >
            {isCalculating ? "Calculating Safe Path..." : "Calculate Optimal Safe Route"}
          </button>

          {routeError && (
            <div style={{ color: "var(--bad)", fontSize: "var(--fs-sm)", background: "#ffebee", padding: "10px", borderRadius: "8px" }}>
              ⚠️ {routeError}
            </div>
          )}

          {/* Results Summary */}
          {routeResult && (
            <>
              <div className={s.routeSummary}>
                <div className={s.routeStat}>
                  <span className={s.routeStatNum}>{routeResult.distance_km} km</span>
                  <span className={s.routeStatLabel}>Distance</span>
                </div>
                <div className={s.routeStat}>
                  <span className={s.routeStatNum}>{routeResult.duration_min} min</span>
                  <span className={s.routeStatLabel}>Travel Time</span>
                </div>
                <div className={s.routeStat}>
                  <span className={s.routeStatNum} style={{ color: routeResult.hazard_avoidance ? "var(--ok)" : "var(--text)" }}>
                    {routeResult.hazard_avoidance ? "DETOUR" : "DIRECT"}
                  </span>
                  <span className={s.routeStatLabel}>Route Type</span>
                </div>
              </div>

              {/* Avoided Hazards Alert */}
              {routeResult.hazards_avoided && routeResult.hazards_avoided.length > 0 && (
                <div className={s.hazardAlert}>
                  <div className={s.hazardAlertTitle}>
                    <span>⚠️</span>
                    <span>{routeResult.hazards_avoided.length} Active Hazard(s) Avoided</span>
                  </div>
                  {routeResult.hazards_avoided.map((h, i) => (
                    <div key={h.id || i} className={s.hazardItem}>
                      • <strong>{h.title || h.type}</strong> ({h.severity?.toUpperCase()}) — Detour active
                    </div>
                  ))}
                </div>
              )}

              {/* Step-by-Step Navigation List */}
              <div className={s.formGroup}>
                <label className={s.label}>Turn-by-Turn Navigation ({routeResult.steps.length} steps)</label>
                <div className={s.stepList}>
                  {routeResult.steps.map((step, idx) => (
                    <div key={idx} className={s.stepItem}>
                      <span className={s.stepNum}>{idx + 1}</span>
                      <span>{step.instruction}</span>
                      {step.distance_m > 0 && (
                        <span className={s.stepDist}>
                          {step.distance_m > 1000 ? `${(step.distance_m / 1000).toFixed(1)} km` : `${Math.round(step.distance_m)} m`}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Right Column: Traffic Corridor Congestion Monitor */}
        <div className={s.panel}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 className={s.panelTitle}>
              <span>🚦</span> Arterial Corridor Congestion
            </h2>
            <button
              type="button"
              onClick={() => reloadTraffic()}
              style={{
                background: "transparent",
                border: "1px solid var(--line)",
                borderRadius: "6px",
                padding: "4px 8px",
                fontSize: "var(--fs-micro)",
                cursor: "pointer",
                color: "var(--muted)",
              }}
            >
              🔄 Refresh
            </button>
          </div>

          <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)", lineHeight: 1.4 }}>
            Level of Service (LOS) calculated using real-time speed ratios against design free-flow capacity.
          </div>

          {trafficLoading ? (
            <div style={{ padding: "32px", textAlign: "center", color: "var(--muted)" }}>
              Analyzing corridor telemetry...
            </div>
          ) : (
            <div className={s.corridorGrid}>
              {corridors.map((c) => {
                const fillPct = Math.round(c.speed_ratio * 100);
                const color = c.level_of_service in { A: 1, B: 1 } ? "var(--ok)" : c.level_of_service in { C: 1, D: 1 } ? "var(--accent)" : "var(--bad)";

                return (
                  <div key={c.id} className={s.corridorCard}>
                    <div className={s.corridorHeader}>
                      <h3 className={s.corridorName}>{c.name}</h3>
                      <span className={s.losBadge} data-los={c.level_of_service}>
                        LOS {c.level_of_service}
                      </span>
                    </div>

                    <div style={{ fontSize: "var(--fs-xs)", color: "var(--text-soft)" }}>
                      {c.from} ➔ {c.to} ({c.length_km} km)
                    </div>

                    {/* Speed indicator bar */}
                    <div className={s.speedBarTrack}>
                      <div
                        className={s.speedBarFill}
                        style={{ width: `${fillPct}%`, background: color }}
                      />
                    </div>

                    <div className={s.corridorFooter}>
                      <span>
                        Speed: <strong>{c.current_speed_kph} km/h</strong> (Free: {c.free_flow_speed_kph} km/h)
                      </span>
                      <span>
                        {c.delay_min > 0 ? `+${c.delay_min}m delay` : "No delay"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
