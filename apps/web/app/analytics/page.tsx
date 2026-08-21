"use client";

/**
 * Auralis Municipal Analytics & Executive KPIs — /analytics
 *
 * Real-time operational intelligence dashboard tracking incident lifecycles,
 * citizen grievance SLA compliance, department workload distribution, and AI efficiency.
 */

import { api, useApi } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import s from "./analytics.module.css";

interface AnalyticsOverview {
  generated_at: string;
  tenant_id: string;
  jurisdiction: string;
  incidents: {
    total: number;
    active: number;
    closed: number;
    mttd_minutes: number;
    mttr_minutes: number;
    resolution_rate_pct: number;
  };
  civic_reports: {
    total: number;
    pending: number;
    resolved: number;
    sla_compliance_pct: number;
    by_department: Record<string, number>;
    by_category: Record<string, number>;
  };
  emergency_dispatch: {
    total_dispatches: number;
    confirmed: number;
    average_eta_minutes: number;
    erss_integration_status: string;
  };
  system_and_ai: {
    evidence_items_minted: number;
    audit_events_chained: number;
    agent_runs_total: number;
    tokens_processed: number;
    total_llm_cost_usd: number;
    unsupported_claim_rate: number;
    policy_enforcement_rate_pct: number;
  };
}

export default function AnalyticsPage() {
  const { data: a, loading, error, correlationId, reload } =
    useApi<AnalyticsOverview>("/v1/analytics/overview");

  // These KPIs are read as operational fact and reported upward. When the
  // endpoint cannot be read the page says so; it never falls back to a
  // plausible-looking dashboard, which is indistinguishable from a real one.
  if (loading && !a) {
    return (
      <div className={s.analyticsPage}>
        <div className={s.pageHeader}>
          <h1>Analytics</h1>
        </div>
        <Skeleton lines={10} />
      </div>
    );
  }

  if (error || !a) {
    return (
      <div className={s.analyticsPage}>
        <div className={s.pageHeader}>
          <h1>Analytics</h1>
        </div>
        <ErrorState
          error={error ?? new Error("The analytics endpoint returned no data.")}
          onRetry={reload}
          correlationId={correlationId}
          what="operational analytics"
        />
      </div>
    );
  }

  const departments = Object.entries(a.civic_reports.by_department || {});
  const maxDept = Math.max(1, ...departments.map(([, v]) => v));

  return (
    <div className={s.analyticsPage}>
      {/* Page Header */}
      <div className={s.pageHeader}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h1>Analytics</h1>
            <p>SLAs, incident lifecycle, dispatch and token spend.</p>
          </div>
          <button
            type="button"
            onClick={() => reload()}
            style={{
              background: "transparent",
              border: "1px solid var(--line)",
              borderRadius: "8px",
              padding: "6px 12px",
              fontSize: "var(--fs-sm)",
              cursor: "pointer",
              color: "var(--muted)",
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Top 4 Primary KPI Cards */}
      <div className={s.kpiGrid}>
        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>SLA Compliance</span>
          <span className={s.kpiValue} style={{ color: "var(--ok)" }}>
            {a.civic_reports.sla_compliance_pct}%
          </span>
          <span className={s.kpiSubtext}>
            {a.civic_reports.resolved} of {a.civic_reports.total} reports within deadline
          </span>
        </div>

        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>Mean Time to Detect (MTTD)</span>
          <span className={s.kpiValue} style={{ color: "var(--accent)" }}>
            {a.incidents.mttd_minutes} min
          </span>
          <span className={s.kpiSubtext}>Autonomous multi-signal AI correlation</span>
        </div>

        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>112 Ambulance Dispatch ETA</span>
          <span className={s.kpiValue} style={{ color: "var(--sev-info)" }}>
            {a.emergency_dispatch.average_eta_minutes} min
          </span>
          <span className={s.kpiSubtext}>ERSS 112 urban response corridor</span>
        </div>

        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>Grounded claims</span>
          <span
            className={s.kpiValue}
            style={{ color: a.system_and_ai.unsupported_claim_rate === 0 ? "var(--ok)" : "var(--warn)" }}
          >
            {((1 - a.system_and_ai.unsupported_claim_rate) * 100).toFixed(1)}%
          </span>
          <span className={s.kpiSubtext}>
            across {a.system_and_ai.agent_runs_total} agent runs
          </span>
        </div>
      </div>

      {/* Two-Column Analytics Breakdown */}
      <div className={s.layoutGrid}>
        {/* Left Column: Department Workload & Incident Resolution */}
        <div className={s.panel}>
          <h2 className={s.panelTitle}>
            <Icon name="layers" size={16} /> Department workload
          </h2>
          <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>
            Live civic ticket distribution and work order routing:
          </div>

          <div className={s.deptList}>
            {departments.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: "var(--fs-sm)" }}>No departmental work orders logged.</div>
            ) : (
              departments.map(([name, count]) => {
                const fillPct = Math.round((count / maxDept) * 100);
                return (
                  <div key={name} className={s.deptItem}>
                    <div className={s.deptHeader}>
                      <span>{name}</span>
                      <span><strong>{count}</strong> active/logged</span>
                    </div>
                    <div className={s.progressBarTrack}>
                      <div className={s.progressBarFill} style={{ width: `${fillPct}%` }} />
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <h2 className={s.panelTitle} style={{ marginTop: "16px" }}>
            <Icon name="clock" size={16} /> Incident resolution
          </h2>
          <table className={s.statsTable}>
            <tbody>
              <tr>
                <td>Total Incidents Logged</td>
                <td>{a.incidents.total}</td>
              </tr>
              <tr>
                <td>Currently Active</td>
                <td>{a.incidents.active}</td>
              </tr>
              <tr>
                <td>Resolved / Closed</td>
                <td>{a.incidents.closed}</td>
              </tr>
              <tr>
                <td>Mean Time to Resolve (MTTR)</td>
                <td>{a.incidents.mttr_minutes} minutes</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Right Column: AI Gateway, Evidence Ledger & Governance */}
        <div className={s.panel}>
          <h2 className={s.panelTitle}>
            <Icon name="trace" size={16} /> Model and ledger usage
          </h2>
          <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>
            LLM Gateway telemetry, token budget, and cryptographic assurance:
          </div>

          <table className={s.statsTable}>
            <tbody>
              <tr>
                <td>Cryptographic Evidence Items Minted</td>
                <td>{a.system_and_ai.evidence_items_minted} verified records</td>
              </tr>
              <tr>
                <td>Hash-Chained Audit Events</td>
                <td>{a.system_and_ai.audit_events_chained} entries</td>
              </tr>
              <tr>
                <td>AI Agent Workflow Invocations</td>
                <td>{a.system_and_ai.agent_runs_total} runs</td>
              </tr>
              <tr>
                <td>Total LLM Tokens Consumed</td>
                <td>{a.system_and_ai.tokens_processed.toLocaleString()}</td>
              </tr>
              <tr>
                <td>Total Operational AI Spend</td>
                <td>${a.system_and_ai.total_llm_cost_usd.toFixed(4)} USD</td>
              </tr>
              <tr>
                <td>Deterministic Policy Enforcement Rate</td>
                <td>{a.system_and_ai.policy_enforcement_rate_pct}%</td>
              </tr>
              <tr>
                <td>ERSS 112 Dispatch Protocol</td>
                <td>{a.emergency_dispatch.erss_integration_status}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
