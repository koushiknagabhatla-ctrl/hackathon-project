"use client";

import { useEffect, useState } from "react";
import { useApi, api } from "@/lib/api";
import { stamp } from "@/lib/format";
import s from "../pages.module.css";

interface EmergencyDispatch {
  id: string;
  incident_id: string;
  service_type: string;
  severity: string;
  coordinates: [number, number];
  road_segment: string;
  status: string;
  external_ref: string | null;
  eta_minutes: number | null;
  requesting_authority: string;
  created_at: string;
  confirmed_at: string | null;
  hazards: string[];
}

export default function EmergencyPage() {
  const { data: dispatches, loading, reload } = useApi<EmergencyDispatch[]>("/v1/emergency/dispatches");
  const [selectedService, setSelectedService] = useState("ambulance");
  const [roadSegment, setRoadSegment] = useState("MG Road / Benz Circle Intersection");
  const [dispatchStatus, setDispatchStatus] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Simulating/Triggering real emergency signals for demonstration
  async function triggerSignal(kind: "cctv" | "traffic" | "citizen") {
    setIsSubmitting(true);
    setDispatchStatus("Transmitting signal to correlation engine...");
    try {
      let endpoint = "/v1/emergency/cctv/event";
      let payload: Record<string, unknown> = { vehicle_count: 2 };
      if (kind === "traffic") {
        endpoint = "/v1/emergency/traffic/event";
        payload = { speed_kph: 3.5 };
      } else if (kind === "citizen") {
        endpoint = "/v1/emergency/citizen/report";
        payload = { text: "Major collision reported at Benz Circle. Immediate medical support required." };
      }

      const res = await api.post<{ verification_status: string; confidence: number; decision: { policy_effect: string } }>(
        endpoint,
        {
          latitude: 16.5062,
          longitude: 80.6480,
          road_segment: roadSegment,
          payload,
        }
      );
      setDispatchStatus(
        `Signal Ingested -> Status: ${res.verification_status} (Confidence: ${(res.confidence * 100).toFixed(0)}%) | Policy: ${res.decision.policy_effect}`
      );
      reload();
    } catch (err: unknown) {
      setDispatchStatus(`Signal ingestion error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className={s.page}>
      <header className={s.header}>
        <div>
          <h1 className={s.title}>Emergency Response & ERSS 112 Dispatch</h1>
          <p className={s.subtitle}>
            Multi-signal accident corroboration, deterministic safety policy, and authorized ERSS 112 CAD integration
          </p>
        </div>
        <div className={s.actions}>
          <span className="badge badge-info">Zero-Fabrication Mode</span>
          <span className="badge badge-success">ERSS 112 Active</span>
        </div>
      </header>

      {dispatchStatus && (
        <div style={{ padding: "1rem", background: "var(--card-bg)", borderRadius: "8px", border: "1px solid var(--accent)", marginBottom: "1.5rem" }}>
          <strong>Correlation Engine Notice:</strong> {dispatchStatus}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem", marginBottom: "2rem" }}>
        {/* Multi-Signal Ingestion Console */}
        <div className={s.card}>
          <h2 style={{ fontSize: "1.2rem", marginBottom: "1rem", color: "var(--accent)" }}>
            1. Multi-Signal Corroboration Engine
          </h2>
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1.2rem" }}>
            The system requires independent corroboration before escalating to emergency dispatch:
            <br />
            • <strong>1 Signal</strong> = SUSPECTED (Operator monitoring only)
            <br />
            • <strong>2 Signals</strong> = CORROBORATED (Geofenced caution alert)
            <br />
            • <strong>3 Signals</strong> = VERIFIED (Auto ERSS 112 ambulance dispatch & officer SMS)
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <button
              className="btn btn-secondary"
              disabled={isSubmitting}
              onClick={() => triggerSignal("cctv")}
            >
              📹 Ingest Signal 1: CCTV Collision Vision (conn_traffic_cam_01)
            </button>
            <button
              className="btn btn-secondary"
              disabled={isSubmitting}
              onClick={() => triggerSignal("traffic")}
            >
              🚗 Ingest Signal 2: Traffic Speed Collapse &lt;5 km/h (conn_tomtom_traffic)
            </button>
            <button
              className="btn btn-secondary"
              disabled={isSubmitting}
              onClick={() => triggerSignal("citizen")}
            >
              📱 Ingest Signal 3: Citizen Open311 Verified Report (conn_citizen)
            </button>
          </div>
        </div>

        {/* ERSS 112 Integration Safeguards */}
        <div className={s.card}>
          <h2 style={{ fontSize: "1.2rem", marginBottom: "1rem", color: "var(--accent)" }}>
            2. ERSS 112 Dispatch Safeguards
          </h2>
          <div style={{ fontSize: "0.85rem", lineHeight: "1.6", color: "var(--text-muted)" }}>
            <div style={{ marginBottom: "0.6rem" }}>
              <span className="badge badge-warning" style={{ marginRight: "0.5rem" }}>INVARIANT</span>
              Never claims <em>&quot;Ambulance dispatched&quot;</em> until the external ERSS 112 CAD gateway explicitly confirms the unit dispatch.
            </div>
            <div style={{ marginBottom: "0.6rem" }}>
              <span className="badge badge-info" style={{ marginRight: "0.5rem" }}>GEOFENCE</span>
              FCM push alerts are broadcast <strong>strictly to consenting registered devices</strong> within the calculated spatial danger radius (1.2 km).
            </div>
            <div>
              <span className="badge badge-critical" style={{ marginRight: "0.5rem" }}>FALLBACK</span>
              If external ERSS CAD times out or fails, the workflow immediately escalates to the human operator console.
            </div>
          </div>
        </div>
      </div>

      {/* Live Dispatch Ledger */}
      <div className={s.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.2rem" }}>ERSS 112 Dispatch Ledger & Confirmation Status</h2>
          <button className="btn btn-sm btn-ghost" onClick={() => reload()}>
            Refresh Ledger
          </button>
        </div>

        {loading ? (
          <p>Loading dispatch ledger...</p>
        ) : !dispatches || dispatches.length === 0 ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)" }}>
            No active emergency dispatch requests. Multi-signal monitoring active on all monitored corridors.
          </div>
        ) : (
          <table className={s.table}>
            <thead>
              <tr>
                <th>Dispatch ID</th>
                <th>Service</th>
                <th>Location / Road</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Requesting Authority</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {dispatches.map((d) => (
                <tr key={d.id}>
                  <td><code>{d.id}</code></td>
                  <td><strong>{d.service_type.toUpperCase()}</strong></td>
                  <td>{d.road_segment}</td>
                  <td>
                    <span className={d.severity === "critical" ? "badge badge-critical" : "badge badge-warning"}>
                      {d.severity}
                    </span>
                  </td>
                  <td>
                    {d.status === "confirmed" ? (
                      <span className="badge badge-success">✓ DISPATCH CONFIRMED ({d.eta_minutes}m ETA)</span>
                    ) : d.status === "awaiting_confirmation" ? (
                      <span className="badge badge-warning">⏳ AWAITING CONFIRMATION</span>
                    ) : (
                      <span className="badge badge-info">ESCALATED TO OPERATOR</span>
                    )}
                  </td>
                  <td>{d.requesting_authority}</td>
                  <td>{stamp(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
