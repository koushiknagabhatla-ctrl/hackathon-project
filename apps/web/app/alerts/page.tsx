"use client";

/**
 * Auralis Proactive Hazards & Early Warning Alerts — /alerts
 *
 * Multi-signal predictive risk engine cross-correlating weather telemetry,
 * flood hydrology, traffic gridlock, and citizen reports into real-time threat tiers.
 */

import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import s from "./alerts.module.css";

interface HazardSignal {
  source: string;
  category: string;
  severity: "info" | "minor" | "major" | "critical";
  value_summary: string;
  threshold_exceeded: boolean;
  confidence: number;
  detected_at: string;
}

interface HazardAssessment {
  overall_risk_tier: "R0" | "R1" | "R2" | "R3" | "R4" | "R5";
  risk_score: number;
  threat_level: string;
  signals_analyzed: number;
  active_threats: Array<{ hazard: string; severity: string; corridor?: string }>;
  signals: HazardSignal[];
  recommended_mitigations: string[];
  assessed_at: string;
}

export default function AlertsPage() {
  const { location, queryCoords } = useShell();
  const { lat, lon } = queryCoords;
  const { data: assessment, loading, error, correlationId, reload } = useApi<HazardAssessment>(
    `/v1/hazards/scan?lat=${lat}&lon=${lon}&city_name=${encodeURIComponent(location.name)}`
  );
  const [broadcastSent, setBroadcastSent] = useState(false);
  const [isBroadcasting, setIsBroadcasting] = useState(false);

  const handleBroadcast = async () => {
    setIsBroadcasting(true);
    try {
      await api.post("/v1/hazards/broadcast", {
        title: `${location.name} Municipal Emergency Advisory`,
        message: `Active meteorological and civic hazard advisory active across ${location.name} municipal zones.`,
        severity: "major",
        geofence_name: `${location.name} Urban Zone`,
      });
      setBroadcastSent(true);
      setTimeout(() => setBroadcastSent(false), 5000);
    } catch (err) {
      console.error("Broadcast failed:", err);
    } finally {
      setIsBroadcasting(false);
    }
  };

  if (loading && !assessment) {
    return (
      <div className={s.alertsPage}>
        <div className={s.pageHeader}>
          <div className={s.pageSub}>{location.name}</div>
          <h1>Hazard alerts</h1>
        </div>
        <Skeleton lines={10} />
      </div>
    );
  }

  if (error || !assessment) {
    return (
      <div className={s.alertsPage}>
        <div className={s.pageHeader}>
          <div className={s.pageSub}>{location.name}</div>
          <h1>Hazard alerts</h1>
        </div>
        <ErrorState
          error={error ?? new Error("The hazard scan returned no assessment.")}
          onRetry={reload}
          correlationId={correlationId}
          what={`the hazard scan for ${location.name}`}
        />
        <p style={{ marginTop: 16, color: "var(--muted)", fontSize: "0.875rem", maxWidth: "60ch" }}>
          No threat level is shown. An unread scan is not a quiet city, and
          rendering one as &quot;normal&quot; would read as an all-clear nobody issued.
        </p>
      </div>
    );
  }

  const a = assessment;

  return (
    <div className={s.alertsPage}>
      {/* Page Header */}
      <div className={s.pageHeader}>
        <div>
          <div className={s.pageSub}>{location.name}</div>
          <h1>Hazard alerts</h1>
        </div>
        <p>Weather, river levels, traffic and citizen reports, watched together.</p>
      </div>

      {/* Top Risk Tier Banner */}
      <div className={s.riskBanner}>
        <div className={s.riskBadge} data-tier={a.overall_risk_tier}>
          <span>{a.overall_risk_tier}</span>
        </div>

        <div className={s.riskInfo}>
          <h2>Threat level: {a.threat_level}</h2>
          <p>
            Across {a.signals_analyzed} data streams. Last checked {a.assessed_at?.slice(11, 19)} UTC.
          </p>
        </div>

        <div className={s.scoreMeter}>
          <span className={s.scoreNum}>{a.risk_score.toFixed(0)}/100</span>
          <span className={s.scoreLabel}>Composite Risk Score</span>
        </div>
      </div>

      {/* Main Two-Column Layout */}
      <div className={s.layoutGrid}>
        {/* Left: Active Threats & Preemptive Mitigations */}
        <div className={s.panel}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 className={s.panelTitle}>
              <Icon name="critical" size={16} /> Active advisories ({a.active_threats.length})
            </h2>
            <button
              type="button"
              onClick={() => reload()}
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
              Refresh
            </button>
          </div>

          {a.active_threats.length === 0 ? (
            <div style={{ padding: "24px", background: "var(--bg-sunken)", borderRadius: "12px", textAlign: "center", color: "var(--muted)", fontSize: "var(--fs-sm)" }}>
              No threshold breaches detected.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {a.active_threats.map((t, idx) => (
                <div key={idx} className={s.threatCard}>
                  <div className={s.threatHeader}>
                    <h3 className={s.threatTitle}>{t.hazard}</h3>
                    <span style={{ fontSize: "var(--fs-micro)", textTransform: "uppercase", fontWeight: 700, color: "var(--bad)" }}>
                      {t.severity}
                    </span>
                  </div>
                  <div className={s.threatBody}>
                    Affected Sector: <strong>{t.corridor ?? "not reported"}</strong>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Preemptive Mitigations */}
          <h2 className={s.panelTitle} style={{ marginTop: "12px" }}>
            <Icon name="action" size={16} /> Recommended mitigations
          </h2>
          <div className={s.mitigationList}>
            {a.recommended_mitigations.map((m, idx) => (
              <div key={idx} className={s.mitigationItem}>
                <span className={s.mitigationIcon}><Icon name="chevronRight" size={13} /></span>
                <span>{m}</span>
              </div>
            ))}
          </div>

          {/* Broadcast Action */}
          <div style={{ marginTop: "8px", borderTop: "1px solid var(--line)", paddingTop: "16px" }}>
            <button
              type="button"
              onClick={handleBroadcast}
              disabled={isBroadcasting}
              style={{
                width: "100%",
                padding: "12px",
                borderRadius: "12px",
                background: "var(--bad)",
                color: "#fff",
                border: "none",
                fontFamily: "var(--font-ui)",
                fontWeight: 600,
                cursor: "pointer",
                fontSize: "var(--fs-sm)",
              }}
            >
              {isBroadcasting ? "Transmitting CAP Broadcast..." : "Transmit public alert (CAP 1.2)"}
            </button>
            {broadcastSent && (
              <div style={{ color: "var(--ok)", fontSize: "var(--fs-xs)", textAlign: "center", marginTop: "6px" }}>
                Broadcast sent to geofenced devices and the public status page.
              </div>
            )}
          </div>
        </div>

        {/* Right: Multi-Signal Correlation Matrix */}
        <div className={s.panel}>
          <h2 className={s.panelTitle}>
            <Icon name="activity" size={16} /> Signal correlation
          </h2>
          <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)", lineHeight: 1.4 }}>
            Streams being watched:
          </div>

          <div className={s.signalList}>
            {a.signals.length === 0 ? (
              <p className={s.signalEmpty}>
                The scan returned no signals. Nothing is listed here rather than
                naming streams whose readings were never received.
              </p>
            ) : (
              a.signals.map((sig, idx) => (
                <div key={idx} className={s.signalItem} data-exceeded={sig.threshold_exceeded ? "true" : "false"}>
                  <div>
                    <span className={s.signalTitle}>{sig.category.replace("_", " ").toUpperCase()}</span>
                    <span className={s.signalSource}>{sig.source} · Conf: {(sig.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <span className={s.signalValue}>{sig.value_summary}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
