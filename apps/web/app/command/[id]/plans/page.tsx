"use client";

/**
 * Plan Review — approval workflow for candidate plans.
 * Shows each plan's actions, risk tiers, policy decisions, and the approval control.
 */

import { useParams } from "next/navigation";
import Link from "next/link";
import { useApi, api, idempotencyKey } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { ApprovalControl } from "@/components/ui/ApprovalControl";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { EvidenceChip } from "@/components/ui/EvidenceChip";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import type { Plan, Action, Evidence } from "@/lib/types";
import s from "../../../pages.module.css";

function ActionStatusTag({ status }: { status: string }) {
  const cls: Record<string, string> = {
    verified: s.tagVerified,
    failed: s.tagFailed,
    blocked: s.tagBlocked,
    executing: s.tagExecuting,
    proposed: s.tagProposed,
    approved: s.tagAllow,
    unknown: s.tagUnknown,
  };
  return <span className={`${s.tag} ${cls[status] ?? s.tagUnknown}`}>{status.replace("_", " ")}</span>;
}

export default function PlanReview() {
  const params = useParams<{ id: string }>();
  const { data: plans, loading, error, reload } = useApi<Plan[]>(`/v1/incidents/${params.id}/plans`);
  const ref = useGsap<HTMLElement>((_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }), [!!plans]);

  if (loading) return <section className="container section"><Skeleton lines={10} /></section>;

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <Link href={`/command/${params.id}`} style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>← Incident Room</Link>
          <h1 style={{ marginTop: 6 }}>Plan Review</h1>
        </div>
      </div>

      {(!plans || plans.length === 0) && (
        <div className={`${s.card} js-reveal`}>
          <p className={s.empty}>No candidate plans available for this incident.</p>
        </div>
      )}

      {plans?.map((plan) => (
        <div key={plan.id} className={`${s.card} js-reveal`} style={{ marginBottom: 20 }}>
          <div className={s.cardHeader}>
            <div>
              <h2 style={{ fontSize: "1.125rem" }}>{plan.title}</h2>
              <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginTop: 4 }}>{plan.rationale}</p>
            </div>
            <span className={s.badge}>{plan.status}</span>
          </div>

          {/* Objective score */}
          {plan.objective_score && (
            <div className={s.kpiStrip} style={{ marginBottom: 20 }}>
              {Object.entries(plan.objective_score as Record<string, unknown>).map(([k, v]) => (
                <div key={k} className={s.stat}>
                  <span className={s.statValue}>{String(v)}</span>
                  <span className={s.statLabel}>{k.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>
          )}

          {/* Actions table */}
          <h3 className={s.sectionTitle}>Actions ({plan.actions.length})</h3>
          <table className={s.table}>
            <thead>
              <tr>
                <th>#</th>
                <th>Tool</th>
                <th>Target</th>
                <th>Risk</th>
                <th>Policy</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {plan.actions.map((act) => (
                <tr key={act.id}>
                  <td style={{ fontFamily: "var(--font-num)" }}>{act.sequence}</td>
                  <td><code style={{ fontSize: "0.8125rem" }}>{act.tool_id}</code></td>
                  <td>{act.target_asset_id || "—"}</td>
                  <td><RiskBadge tier={act.risk_tier} reason={`blast radius: ${act.blast_radius}`} /></td>
                  <td>
                    {act.policy_decision ? (
                      <span className={`${s.tag} ${act.policy_decision.effect === "allow" ? s.tagAllow : act.policy_decision.effect === "deny" ? s.tagDeny : s.tagApproval}`}>
                        {act.policy_decision.effect.replace("_", " ")}
                      </span>
                    ) : "—"}
                  </td>
                  <td><ActionStatusTag status={act.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Blocked actions needing approval */}
          {plan.actions.filter((a) => a.policy_decision?.effect === "require_approval" && a.status === "proposed").map((act) => (
            <div key={act.id} style={{ marginTop: 16, padding: 16, border: "1px solid var(--accent)", borderRadius: "var(--r-surface)" }}>
              <p style={{ fontWeight: 600, fontSize: "0.875rem", marginBottom: 8 }}>
                <Icon name="lock" size={14} /> Approval required for {act.tool_id}
              </p>
              <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginBottom: 12 }}>
                {act.policy_decision?.reason}
              </p>
              <ApprovalControl
                action={act}
                onDecision={async ({ decision, rationale }) => {
                  await api.post(`/v1/plans/${plan.id}/approve`, {
                    action_id: act.id,
                    decision,
                    rationale,
                  });
                  reload();
                }}
              />
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}
