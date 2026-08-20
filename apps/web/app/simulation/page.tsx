"use client";

/**
 * Simulation & Counterfactual — Sandbox Digital Twin.
 * Explore "what-if" scenarios, rainfall variations, and infrastructure failures
 * completely isolated in the 'sim' trust domain.
 */

import { useState } from "react";
import { useApi, api } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { SyntheticBanner } from "@/components/ui/SyntheticBanner";
import { MetricTile } from "@/components/ui/MetricTile";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import type { SimulationRequest, SimulationResult } from "@/lib/types";
import s from "../pages.module.css";

export default function SimulationPage() {
  const toast = useToast();
  const [scenario, setScenario] = useState<string>("flood");
  const [seed, setSeed] = useState<number>(42);
  const [rainOverride, setRainOverride] = useState<number>(110);
  const [running, setRunning] = useState<boolean>(false);
  const [simResult, setSimResult] = useState<SimulationResult | null>(null);

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [],
  );

  const handleRunSimulation = async () => {
    setRunning(true);
    try {
      const payload: SimulationRequest = {
        scenario,
        seed,
        overrides: {
          rain_mm_hr: rainOverride,
          water_level_m: 4.82,
        },
      };
      const res = await api.post<SimulationResult>("/v1/simulations", payload);
      setSimResult(res);
      toast.push({ tone: "ok", title: "Simulation Complete", body: "Counterfactual scenario generated in sim trust domain." });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Simulation failed";
      toast.push({ tone: "bad", title: "Simulation Error", body: msg });
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Assure · Sandbox Digital Twin</span>
          <h1>Counterfactual Simulation Engine</h1>
        </div>
      </div>

      <div className="js-reveal">
        <SyntheticBanner
          scope="Sandbox Digital Twin"
          detail="Isolated from physical actuations. All predictions and claims are labeled synthetic."
        />
      </div>

      {/* Scenario Controls */}
      <div className={`${s.card} js-reveal`} style={{ marginBottom: 24 }}>
        <div className={s.cardHeader}>
          <h2>Simulation Parameters</h2>
          <span className="label">Deterministic Replay with Fixed Seed</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16 }}>
          <div>
            <label className="label" htmlFor="scenario-select">Scenario Preset</label>
            <select
              id="scenario-select"
              className="select"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              style={{ width: "100%", padding: 10, borderRadius: "var(--r-control)", border: "1px solid var(--line)", background: "var(--surface)", marginTop: 6 }}
            >
              <option value="flood">Budameru Rivulet Extreme Inflow (Flood)</option>
              <option value="traffic">Ring Road Impassable (Traffic Bottleneck)</option>
              <option value="power">Substation Cutoff Cascade (Grid)</option>
            </select>
          </div>

          <div>
            <label className="label" htmlFor="rain-input">Rainfall Override (mm / 3h)</label>
            <input
              id="rain-input"
              type="number"
              value={rainOverride}
              onChange={(e) => setRainOverride(Number(e.target.value))}
              style={{ width: "100%", padding: 10, borderRadius: "var(--r-control)", border: "1px solid var(--line)", background: "var(--surface)", marginTop: 6 }}
            />
          </div>

          <div>
            <label className="label" htmlFor="seed-input">Random Seed (Reproducibility)</label>
            <input
              id="seed-input"
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
              style={{ width: "100%", padding: 10, borderRadius: "var(--r-control)", border: "1px solid var(--line)", background: "var(--surface)", marginTop: 6 }}
            />
          </div>

          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button
              type="button"
              className="btn btn--primary"
              style={{ width: "100%", height: 42 }}
              onClick={handleRunSimulation}
              disabled={running}
            >
              <Icon name="synthetic" size={16} />
              {running ? "Simulating..." : "Run Sandbox Twin"}
            </button>
          </div>
        </div>
      </div>

      {/* Simulation Results Comparison */}
      {simResult && (
        <div className={`${s.card} js-reveal`}>
          <div className={s.cardHeader}>
            <h2>Baseline vs Counterfactual Comparison</h2>
            <span className="mono" style={{ fontSize: "0.75rem" }}>
              Hash: {simResult.results_hash}
            </span>
          </div>

          <div className={s.grid2} style={{ marginBottom: 24 }}>
            {/* Baseline Column */}
            <div style={{ padding: 18, border: "1px solid var(--line)", borderRadius: "var(--r-control)" }}>
              <span className="label">Observed Baseline</span>
              <h3 style={{ fontSize: "1.25rem", margin: "8px 0 16px" }}>Standard Forecast (68mm rain)</h3>
              <div className={s.kpiStrip}>
                <div className={s.stat}>
                  <span className={s.statValue}>{String((simResult.baseline as Record<string, unknown>).peak_forecast_m ?? "5.7")}m</span>
                  <span className={s.statLabel}>Peak Stage</span>
                </div>
                <div className={s.stat}>
                  <span className={s.statValue}>{String((simResult.baseline as Record<string, unknown>).premises_at_risk ?? "1,240")}</span>
                  <span className={s.statLabel}>Premises at Risk</span>
                </div>
              </div>
              <div style={{ marginTop: 12 }}>
                <span className="label">Computed Policy Tier</span>
                <div style={{ marginTop: 6 }}>
                  <RiskBadge tier={((simResult.baseline as Record<string, unknown>).risk_tier as any) ?? "R3"} />
                </div>
              </div>
            </div>

            {/* Counterfactual Column */}
            <div style={{ padding: 18, border: "2px solid var(--accent)", borderRadius: "var(--r-control)", background: "rgba(250, 129, 40, 0.02)" }}>
              <span className="label" style={{ color: "var(--accent)" }}>Synthetic Counterfactual</span>
              <h3 style={{ fontSize: "1.25rem", margin: "8px 0 16px" }}>Overridden Scenario ({rainOverride}mm rain)</h3>
              <div className={s.kpiStrip}>
                <div className={s.stat}>
                  <span className={s.statValue} style={{ color: "var(--accent)" }}>
                    {String((simResult.counterfactual as Record<string, unknown>).peak_forecast_m ?? "6.85")}m
                  </span>
                  <span className={s.statLabel}>Peak Stage</span>
                </div>
                <div className={s.stat}>
                  <span className={s.statValue} style={{ color: "var(--accent)" }}>
                    {String((simResult.counterfactual as Record<string, unknown>).premises_at_risk ?? "2,850")}
                  </span>
                  <span className={s.statLabel}>Premises at Risk</span>
                </div>
              </div>
              <div style={{ marginTop: 12 }}>
                <span className="label">Elevated Policy Tier</span>
                <div style={{ marginTop: 6 }}>
                  <RiskBadge tier={((simResult.counterfactual as Record<string, unknown>).risk_tier as any) ?? "R4"} reason="Elevated downstream blast radius" />
                </div>
              </div>
            </div>
          </div>

          {/* Policy Shift Report */}
          {simResult.policy_changes && simResult.policy_changes.length > 0 && (
            <div>
              <h3 className={s.sectionTitle}>Policy Impact Shift</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {simResult.policy_changes.map((pc: Record<string, unknown>, idx: number) => (
                  <div key={idx} style={{ padding: 12, border: "1px solid var(--line)", borderRadius: "var(--r-control)" }}>
                    <strong>{String(pc.impact)}</strong>
                    <div style={{ display: "flex", gap: 16, marginTop: 4, fontSize: "0.8125rem", color: "var(--muted)" }}>
                      <span>Baseline: {String(pc.baseline)}</span>
                      <span>→</span>
                      <span style={{ color: "var(--accent)", fontWeight: 600 }}>Counterfactual: {String(pc.counterfactual)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
