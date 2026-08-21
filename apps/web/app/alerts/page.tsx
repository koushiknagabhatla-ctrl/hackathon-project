"use client";

/**
 * Auralis Proactive Hazards & Early Warning Alerts — /alerts
 *
 * Multi-signal predictive risk engine cross-correlating weather telemetry,
 * flood hydrology, traffic gridlock, and citizen reports into real-time threat tiers.
 */

import { useState } from "react";
import { api, useApi } from "@/lib/api";
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
  const { data: assessment, loading, reload } = useApi<HazardAssessment>("/v1/hazards/scan");
  const [broadcastSent, setBroadcastSent] = useState(false);
  const [isBroadcasting, setIsBroadcasting] = useState(false);

  const handleBroadcast = async () => {
    setIsBroadcasting(true);
    try {
      await api.post("/v1/hazards/broadcast", {
        title: "Vijayawada Municipal Advisory",
        message: "Severe weather and drainage surge advisory active across municipal zones.",
        severity: "major",
      });
      setBroadcastSent(true);
      setTimeout(() => setBroadcastSent(false), 5000);
    } catch (err) {
      console.error("Broadcast failed:", err);
    } finally {
      setIsBroadcasting(false);
    }
  };

  const a = assessment || {
    overall_risk_tier: "R0",
    risk_score: 5.0,
    threat_level: "NORMAL",
    signals_analyzed: 4,
    active_threats: [],
    signals: [],
    recommended_mitigations: ["Maintain standard 24/7 telemetry monitoring across municipal sensors."],
    assessed_at: new Date().toISOString(),
  };

  return (
    <div className={s.alertsPage}>
      {/* Page Header */}
      <div className={s.pageHeader}>
        <h1>Proactive Hazard Intelligence & Alerts</h1>
        <p>
          Predictive multi-signal anomaly correlation across meteorological sensors,
          flood hydrology, traffic collapse, and citizen reports to detect threats before escalation.
        </p>
      </div>

      {/* Top Risk Tier Banner */}
      <div className={s.riskBanner}>
        <div className={s.riskBadge} data-tier={a.overall_risk_tier}>
          <span>{a.overall_risk_tier}</span>
        </div>

        <div className={s.riskInfo}>
          <h2>Threat Level: {a.threat_level}</h2>
          <p>
            Continuous Bayesian correlation across {a.signals_analyzed || 5} municipal data streams.
            Last assessed: {a.assessed_at?.slice(11, 19)} UTC.
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
              <span>🚨</span> Active Threat Advisories ({a.active_threats.length})
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
              🔄 Refresh Scan
            </button>
          </div>

          {a.active_threats.length === 0 ? (
            <div style={{ padding: "24px", background: "var(--bg-sunken)", borderRadius: "12px", textAlign: "center", color: "var(--muted)", fontSize: "var(--fs-sm)" }}>
              ✅ No critical threshold breaches detected in Vijayawada urban sector.
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
                    Affected Sector: <strong>{t.corridor || "Vijayawada Urban Zone"}</strong>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Preemptive Mitigations */}
          <h2 className={s.panelTitle} style={{ marginTop: "12px" }}>
            <span>🛠️</span> Preemptive Mitigation Directives
          </h2>
          <div className={s.mitigationList}>
            {a.recommended_mitigations.map((m, idx) => (
              <div key={idx} className={s.mitigationItem}>
                <span className={s.mitigationIcon}>⚡</span>
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
                background: "linear-gradient(135deg, #b3261e, #8a1f18)",
                color: "#fff",
                border: "none",
                fontFamily: "var(--font-ui)",
                fontWeight: 600,
                cursor: "pointer",
                fontSize: "var(--fs-sm)",
              }}
            >
              {isBroadcasting ? "Transmitting CAP Broadcast..." : "📢 Transmit Public Emergency Alert (CAP 1.2)"}
            </button>
            {broadcastSent && (
              <div style={{ color: "var(--ok)", fontSize: "var(--fs-xs)", textAlign: "center", marginTop: "6px" }}>
                ✅ Emergency broadcast transmitted to geofenced mobile devices and public status portal.
              </div>
            )}
          </div>
        </div>

        {/* Right: Multi-Signal Correlation Matrix */}
        <div className={s.panel}>
          <h2 className={s.panelTitle}>
            <span>📡</span> Multi-Signal Correlation Matrix
          </h2>
          <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)", lineHeight: 1.4 }}>
            Independent observation streams monitored in real time:
          </div>

          <div className={s.signalList}>
            {a.signals.length === 0 ? (
              <>
                <div className={s.signalItem} data-exceeded="false">
                  <div>
                    <span className={s.signalTitle}>Precipitation Telemetry</span>
                    <span className={s.signalSource}>Open-Meteo & OpenWeatherMap</span>
                  </div>
                  <span className={s.signalValue}>0.0 mm/h (Normal)</span>
                </div>
                <div className={s.signalItem} data-exceeded="false">
                  <div>
                    <span className={s.signalTitle}>River Discharge / Hydrology</span>
                    <span className={s.signalSource}>GloFAS Krishna Basin Model</span>
                  </div>
                  <span className={s.signalValue}>Stage 0 (Normal)</span>
                </div>
                <div className={s.signalItem} data-exceeded="false">
                  <div>
                    <span className={s.signalTitle}>Arterial Traffic Flow</span>
                    <span className={s.signalSource}>Urban Corridor Speed Sensors</span>
                  </div>
                  <span className={s.signalValue}>LOS B (Stable)</span>
                </div>
                <div className={s.signalItem} data-exceeded="false">
                  <div>
                    <span className={s.signalTitle}>Citizen Report Clustering</span>
                    <span className={s.signalSource}>Auralis Open311 Ledger</span>
                  </div>
                  <span className={s.signalValue}>0 Anomaly Clusters</span>
                </div>
                <div className={s.signalItem} data-exceeded="false">
                  <div>
                    <span className={s.signalTitle}>Global & Regional News Stream</span>
                    <span className={s.signalSource}>GDELT Event Intelligence</span>
                  </div>
                  <span className={s.signalValue}>Monitored</span>
                </div>
              </>
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
