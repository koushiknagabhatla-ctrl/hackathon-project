"use client";

/**
 * Action Monitor — The authorization queue, executing tools, and verified outcomes.
 * Shows every tool call with its risk tier, idempotency key, policy decision,
 * intended vs actual state, and verification status.
 */

import { useState } from "react";
import Link from "next/link";
import { useApi, api, idempotencyKey } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { MetricTile } from "@/components/ui/MetricTile";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import type { Action, PolicyDecision } from "@/lib/types";
import { ACTIONS as FIXTURE_ACTIONS } from "@/lib/fixtures";
import s from "../pages.module.css";

function ActionStatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    verified: s.tagVerified,
    failed: s.tagFailed,
    blocked: s.tagBlocked,
    executing: s.tagExecuting,
    proposed: s.tagProposed,
    approved: s.tagAllow,
    unknown: s.tagUnknown,
    rolled_back: s.tagUnknown,
  };
  return <span className={`${s.tag} ${cls[status] ?? s.tagUnknown}`}>{status.replace("_", " ")}</span>;
}

export default function ActionMonitor() {
  const { data: actionsData, loading, reload } = useApi<Action[]>("/v1/actions");
  const toast = useToast();
  const [executingId, setExecutingId] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const actions = actionsData && actionsData.length > 0 ? actionsData : FIXTURE_ACTIONS;

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [actions.length],
  );

  const handleExecute = async (action: Action) => {
    try {
      setExecutingId(action.id);
      const key = idempotencyKey("act");
      await api.post(`/v1/actions/${action.id}/execute`, { idempotency_key: key });
      toast.push({ title: "Action Executed", body: `Action ${action.id} read-back verified.`, tone: "ok" });
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Execution failed";
      toast.push({ title: "Execution Halted", body: msg, tone: "bad" });
    } finally {
      setExecutingId(null);
    }
  };

  const handleRollback = async (action: Action) => {
    try {
      setExecutingId(action.id);
      await api.post(`/v1/actions/${action.id}/rollback`);
      toast.push({ title: "Rollback Complete", body: `Action ${action.id} rolled back successfully.`, tone: "ok" });
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Rollback failed";
      toast.push({ title: "Rollback Error", body: msg, tone: "bad" });
    } finally {
      setExecutingId(null);
    }
  };

  const filtered = actions.filter((a) => {
    if (filter === "all") return true;
    if (filter === "pending") return a.status === "proposed" || a.status === "approved";
    if (filter === "blocked") return a.status === "blocked";
    if (filter === "executed") return a.status === "verified" || a.status === "executed";
    return true;
  });

  const verifiedCount = actions.filter((a) => a.status === "verified").length;
  const blockedCount = actions.filter((a) => a.status === "blocked").length;
  const proposedCount = actions.filter((a) => a.status === "proposed" || a.status === "approved").length;

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Operational Execution</span>
          <h1>Action Monitor & Queue</h1>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className={`btn ${filter === "all" ? "btn--primary" : ""}`}
            onClick={() => setFilter("all")}
            type="button"
          >
            All ({actions.length})
          </button>
          <button
            className={`btn ${filter === "pending" ? "btn--primary" : ""}`}
            onClick={() => setFilter("pending")}
            type="button"
          >
            Pending ({proposedCount})
          </button>
          <button
            className={`btn ${filter === "blocked" ? "btn--primary" : ""}`}
            onClick={() => setFilter("blocked")}
            type="button"
          >
            Blocked ({blockedCount})
          </button>
          <button
            className={`btn ${filter === "executed" ? "btn--primary" : ""}`}
            onClick={() => setFilter("executed")}
            type="button"
          >
            Verified ({verifiedCount})
          </button>
        </div>
      </div>

      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile label="Total Actions" value={String(actions.length)} />
        <MetricTile label="Verified Outcomes" value={String(verifiedCount)} />
        <MetricTile label="Policy Blocked" value={String(blockedCount)} />
        <MetricTile label="Pending Auth" value={String(proposedCount)} />
      </div>

      {loading && !actions.length ? (
        <Skeleton lines={8} />
      ) : (
        <div className={`${s.card} js-reveal`}>
          <div className={s.cardHeader}>
            <h2>Tool Execution & Verification Ledger</h2>
            <span className="label">Deterministic Gateway Enforced</span>
          </div>

          <table className={s.table}>
            <thead>
              <tr>
                <th>Seq</th>
                <th>Tool Identifier</th>
                <th>Target Asset</th>
                <th>Risk Tier</th>
                <th>Policy Rule</th>
                <th>Idempotency Key</th>
                <th>Verification</th>
                <th>Status</th>
                <th>Controls</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((act) => (
                <tr key={act.id}>
                  <td style={{ fontFamily: "var(--font-num)", fontWeight: 600 }}>
                    #{act.sequence}
                  </td>
                  <td>
                    <code style={{ fontSize: "0.8125rem", color: "var(--text)" }}>{act.tool_id}</code>
                    {act.args && (
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: 2 }}>
                        {JSON.stringify(act.args)}
                      </div>
                    )}
                  </td>
                  <td>
                    {act.target_asset_id ? (
                      <span className="mono">{act.target_asset_id}</span>
                    ) : (
                      <span style={{ color: "var(--muted)" }}>Citywide / None</span>
                    )}
                  </td>
                  <td>
                    <RiskBadge tier={act.risk_tier} reason={`Radius: ${act.blast_radius}`} />
                  </td>
                  <td>
                    {act.policy_decision ? (
                      <div>
                        <span
                          className={`${s.tag} ${
                            act.policy_decision.effect === "allow"
                              ? s.tagAllow
                              : act.policy_decision.effect === "deny"
                              ? s.tagDeny
                              : s.tagApproval
                          }`}
                        >
                          {act.policy_decision.rule_id}
                        </span>
                        <p style={{ fontSize: "0.75rem", color: "var(--muted)", margin: "4px 0 0" }}>
                          {act.policy_decision.reason}
                        </p>
                      </div>
                    ) : (
                      <span style={{ color: "var(--muted)" }}>Pre-evaluated</span>
                    )}
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: "0.75rem" }}>
                      {act.idempotency_key ?? "—"}
                    </span>
                  </td>
                  <td>
                    {act.verification ? (
                      <div>
                        <span
                          className={`${s.tag} ${
                            act.verification === "SUCCESS"
                              ? s.tagVerified
                              : act.verification === "DIFFERENCE"
                              ? s.tagApproval
                              : s.tagFailed
                          }`}
                        >
                          {act.verification}
                        </span>
                        {act.verification_method && (
                          <div style={{ fontSize: "0.6875rem", color: "var(--muted)", marginTop: 2 }}>
                            {act.verification_method}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>Pending run</span>
                    )}
                  </td>
                  <td>
                    <ActionStatusBadge status={act.status} />
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {(act.status === "approved" || act.status === "proposed") && (
                        <button
                          type="button"
                          className="btn btn--primary"
                          style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                          onClick={() => handleExecute(act)}
                          disabled={executingId === act.id}
                        >
                          {executingId === act.id ? "Running..." : "Execute"}
                        </button>
                      )}
                      {act.status === "verified" && act.reversible && (
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                          onClick={() => handleRollback(act)}
                          disabled={executingId === act.id}
                        >
                          Rollback
                        </button>
                      )}
                      {act.status === "blocked" && (
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                          <Icon name="lock" size={12} /> Policy gated
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className={s.empty}>
                    No actions match the selected filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
