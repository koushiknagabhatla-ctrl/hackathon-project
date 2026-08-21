"use client";

/**
 * Executive Dashboard — City Leadership & Strategic Assurance.
 * Surfaces high-level outcome metrics, cost of autonomy, adherence to invariant safety
 * thresholds (0% unsupported claims, 0% unauthorized actions), and operational velocity.
 */

import { useApi } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { useGsap, sectionReveal } from "@/lib/motion";
import { MetricTile } from "@/components/ui/MetricTile";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import type { OpsMetrics } from "@/lib/types";
import { ErrorState } from "@/components/ui/ErrorState";
import s from "../pages.module.css";

export default function ExecutiveDashboard() {
  const { location } = useShell();
  const { data: opsData, loading } = useApi<OpsMetrics>("/v1/metrics/ops");
  // NO SILENT SUBSTITUTION. Executive KPIs drive real decisions and get quoted
  // upward. Showing demo numbers when the API is down would put fabricated
  // figures in front of the person least able to spot them.
  const ops = opsData;

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [],
  );

  if (!ops) {
    return (
      <section className="container section">
        <div className={s.pageHeader}>
          <div>
            <span className="eyebrow">Executive · Outcome KPIs</span>
            <h1>Executive Overview</h1>
          </div>
        </div>
        <ErrorState
          error={new Error("Metrics source unavailable")}
          what="operational KPIs"
          onRetry={() => window.location.reload()}
        />
        <p style={{ marginTop: 16, color: "var(--muted)", fontSize: "0.875rem", maxWidth: "60ch" }}>
          No figures are shown because none could be read. These KPIs are
          reported upward and must never be estimated or substituted.
        </p>
      </section>
    );
  }

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Communicate · Leadership Overview</span>
          <h1>Executive summary</h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span className="label">{location.name}</span>
        </div>
      </div>

      {/* Primary Inviolable Invariants Strip */}
      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile
          label="Unsupported Claim Rate"
          value={`${(ops.unsupported_claim_rate * 100).toFixed(1)}%`}
        />
        <MetricTile
          label="Unauthorized Action Rate"
          value={`${(ops.unauthorized_action_rate * 100).toFixed(1)}%`}
        />
        {/* A null metric means not enough measured workflows yet. It renders as
            "not yet measured", never as an invented number. */}
        <MetricTile
          label="Avg Detection Velocity"
          value={ops.time_to_detect_s != null ? `${ops.time_to_detect_s}s` : "—"}
          foot={ops.time_to_detect_s != null ? undefined : "not yet measured"}
        />
        <MetricTile
          label="Avg Plan Compilation"
          value={ops.time_to_plan_s != null ? `${ops.time_to_plan_s}s` : "—"}
          foot={ops.time_to_plan_s != null ? undefined : "not yet measured"}
        />
        <MetricTile
          label="Tool Success Rate"
          value={`${(ops.tool_success_rate * 100).toFixed(1)}%`}
        />
      </div>

      {/* Cost & Efficiency Section */}
      <div className={`${s.grid2} js-reveal`} style={{ marginBottom: 24 }}>
        <div className={s.card}>
          <div className={s.cardHeader}>
            <h2>Model cost and token use</h2>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div className={s.stat}>
              <span className={s.statValue}>${ops.llm_cost_usd.toFixed(2)}</span>
              <span className={s.statLabel}>24h Model Compute Spend</span>
            </div>
            <div className={s.stat}>
              <span className={s.statValue}>${ops.cost_per_incident_usd.toFixed(2)}</span>
              <span className={s.statLabel}>Average Cost per Incident</span>
            </div>
          </div>

          <table className={s.table}>
            <tbody>
              <tr>
                <td>Total Specialized Invocations</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-num)", fontWeight: 600 }}>
                  {ops.llm_calls}
                </td>
              </tr>
              <tr>
                <td>Total Processed Tokens</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-num)", fontWeight: 600 }}>
                  {ops.llm_tokens.toLocaleString()}
                </td>
              </tr>
              <tr>
                <td>AI Path</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-num)" }}>
                  {ops.degraded ? "Deterministic fallback active" : "Model path online"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className={s.card}>
          <div className={s.cardHeader}>
            <h2>Safety and governance</h2>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div className={s.stat}>
              <span className={s.statValue} style={{ color: "var(--accent)" }}>
                {ops.policy_blocks_24h}
              </span>
              <span className={s.statLabel}>Autonomous Actions Prevented</span>
            </div>
            <div className={s.stat}>
              <span className={s.statValue}>{ops.audit_events.toLocaleString()}</span>
              <span className={s.statLabel}>Cryptographic Audit Records</span>
            </div>
          </div>

          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", lineHeight: 1.6 }}>
            R4 and R5 actions cannot reach a tool without a named human
            approval. The counts above are what the policy engine recorded.
          </p>
        </div>
      </div>

      {/* Strategic Value Narrative */}
      <div className={`${s.card} js-reveal`}>
        <div className={s.cardHeader}>
          <h2>Last 24 hours</h2>
        </div>
        {/* Only statements derived from the metrics actually returned. The
            previous version hardcoded specific figures — a 4.82m river stage,
            1,240 premises, "100% of claims" — as accomplishments that had
            supposedly happened. Narrative prose asserting measurements the
            system never took is fabrication with a confident voice, which is
            the most dangerous kind on an executive surface. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, fontSize: "0.875rem" }}>
          <div style={{ padding: 12, background: "rgba(0,0,0,0.015)", borderRadius: "var(--r-control)" }}>
            <strong>Grounding:</strong>{" "}
            {ops.unsupported_claim_rate === 0
              ? `No unsupported claims were recorded across ${ops.llm_calls} model invocations. Every claim rendered to an operator carried at least one verified evidence reference.`
              : `${(ops.unsupported_claim_rate * 100).toFixed(1)}% of claims lacked a valid evidence link and were withheld from operator surfaces.`}
          </div>
          <div style={{ padding: 12, background: "rgba(0,0,0,0.015)", borderRadius: "var(--r-control)" }}>
            <strong>Bounded autonomy:</strong>{" "}
            {ops.policy_blocks_24h > 0
              ? `${ops.policy_blocks_24h} proposed action${ops.policy_blocks_24h === 1 ? " was" : "s were"} refused by the deterministic policy engine before reaching a tool.`
              : "No proposed action required policy refusal in this period."}
            {" "}Unauthorized-action rate: {(ops.unauthorized_action_rate * 100).toFixed(1)}%.
          </div>
          <div style={{ padding: 12, background: "rgba(0,0,0,0.015)", borderRadius: "var(--r-control)" }}>
            <strong>Reconstructability:</strong>{" "}
            {ops.audit_events > 0
              ? `${ops.audit_events.toLocaleString()} hash-chained audit records were written, each linked to its predecessor.`
              : "No audit records have been written in this period."}
          </div>
        </div>
      </div>
    </section>
  );
}
