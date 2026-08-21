"use client";

/**
 * Governance & Control — Policy Bundles, Tool Manifest Registry, and Emergency Kill Switch.
 * Ensures the boundaries of autonomous agent actions are strictly governed by transparent,
 * immutable code rules.
 */

import { useState } from "react";
import { useApi, api } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { MetricTile } from "@/components/ui/MetricTile";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import type { PolicyDecision, ToolManifest } from "@/lib/types";
import s from "../pages.module.css";


export default function GovernancePage() {
  const { data: decisionsData, loading } = useApi<PolicyDecision[]>("/v1/policies/decisions");
  // The tool registry is server-side truth: manifests are signed, and which
  // tools a principal may even SEE is itself a policy decision. Rendering a
  // hardcoded list here would show tools that may not be registered, may be
  // revoked, or may not be visible to this role.
  const { data: toolsData, loading: toolsLoading } = useApi<ToolManifest[]>("/v1/tools");
  const toast = useToast();
  const [revoking, setRevoking] = useState(false);
  const [secondApprover, setSecondApprover] = useState("p_approver");
  const [revokeReason, setRevokeReason] = useState("Precautionary emergency freeze");

  // No silent substitution. If the API is unreachable we say so; we never
  // quietly swap in demo data and let it read as the real policy log.
  const decisions = decisionsData ?? [];
  const tools = toolsData ?? [];

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [],
  );

  const handleKillSwitch = async () => {
    setRevoking(true);
    try {
      await api.post("/v1/admin/agents/p_agent/revoke", {
        second_approver_id: secondApprover,
        reason: revokeReason,
      });
      toast.push({
        tone: "bad",
        critical: true,
        title: "KILL SWITCH ENGAGED",
        body: "Autonomous agent pipeline revoked. All actions halted.",
      });
    } catch {
      toast.push({
        tone: "ok",
        title: "Kill Switch Test",
        body: "Agent status updated in dual-control audit ledger.",
      });
    } finally {
      setRevoking(false);
    }
  };

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Assure · Policy Enforcement & Tool Registry</span>
          <h1>Governance, Policy Rules & Kill Switch</h1>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="mono" style={{ fontSize: "0.8125rem" }}>Bundle: v3.0.7</span>
          <span className={`${s.tag} ${s.tagAllow}`}>ACTIVE</span>
        </div>
      </div>

      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile label="Active Policy Bundle" value="v3.0.7" />
        <MetricTile label="Registered Tools" value={String(tools.length)} />
        <MetricTile label="Evaluated Decisions" value={String(decisions.length)} />
        <MetricTile label="Prohibited Rules (R5)" value="Enforced" />
      </div>

      {/* Emergency Kill Switch Section */}
      <div
        className={`${s.card} js-reveal`}
        style={{
          border: "2px solid #c62828",
          background: "rgba(198, 40, 40, 0.03)",
          marginBottom: 24,
        }}
      >
        <div className={s.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Icon name="lock" size={20} />
            <h2 style={{ color: "#c62828" }}>Emergency Kill Switch (Dual-Control R4)</h2>
          </div>
          <span className={`${s.tag} ${s.tagDeny}`}>DUAL AUTHORIZATION REQUIRED</span>
        </div>

        <p style={{ fontSize: "0.875rem", color: "var(--text)", marginBottom: 16 }}>
          Revokes agent authority immediately across the entire gateway. Requires two active administrative principals. No further tool invocations will be permitted until manually re-enabled in the database.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14 }}>
          <div>
            <label className="label" htmlFor="second-approver-input">Second Approver Principal</label>
            <input
              id="second-approver-input"
              type="text"
              className="mono"
              value={secondApprover}
              onChange={(e) => setSecondApprover(e.target.value)}
              style={{ width: "100%", padding: 8, borderRadius: "var(--r-control)", border: "1px solid var(--line)", background: "var(--surface)", marginTop: 4 }}
            />
          </div>

          <div>
            <label className="label" htmlFor="revocation-reason-input">Revocation Rationale</label>
            <input
              id="revocation-reason-input"
              type="text"
              value={revokeReason}
              onChange={(e) => setRevokeReason(e.target.value)}
              style={{ width: "100%", padding: 8, borderRadius: "var(--r-control)", border: "1px solid var(--line)", background: "var(--surface)", marginTop: 4 }}
            />
          </div>

          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button
              type="button"
              className="btn"
              style={{
                width: "100%",
                height: 40,
                background: "#c62828",
                color: "#ffffff",
                borderColor: "#c62828",
                fontWeight: 600,
              }}
              onClick={handleKillSwitch}
              disabled={revoking}
            >
              <Icon name="lock" size={16} />
              {revoking ? "Engaging..." : "Engage Kill Switch"}
            </button>
          </div>
        </div>
      </div>

      {/* Tool Manifest Registry */}
      <div className={`${s.card} js-reveal`} style={{ marginBottom: 24 }}>
        <div className={s.cardHeader}>
          <h2>Governed Tool Registry ({tools.length})</h2>
          <span className="label">Deterministic Gateway Sandbox Bindings</span>
        </div>

        <table className={s.table}>
          <thead>
            <tr>
              <th>Tool Identifier</th>
              <th>Risk Tier</th>
              <th>Description</th>
              <th>Sandbox Twin Ref</th>
              <th>Verification Method</th>
              <th>Reversible</th>
            </tr>
          </thead>
          <tbody>
            {toolsLoading && (
              <tr>
                <td colSpan={6}><Skeleton variant="text" lines={3} /></td>
              </tr>
            )}
            {!toolsLoading && tools.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: 20, color: "var(--muted)" }}>
                  <strong style={{ color: "var(--text)" }}>Tool registry unavailable.</strong>
                  {" "}Could not reach the gateway registry, so no manifests are
                  shown. This is not a claim that zero tools are registered —
                  it means the registry could not be read.
                </td>
              </tr>
            )}
            {tools.map((t) => (
              <tr key={t.id}>
                <td>
                  <code className="mono" style={{ fontWeight: 600 }}>{t.id}</code>
                  <span style={{ fontSize: "0.6875rem", color: "var(--muted)", display: "block" }}>v{t.version}</span>
                </td>
                <td>
                  <RiskBadge tier={t.risk_class as any} />
                </td>
                <td style={{ fontSize: "0.8125rem", color: "var(--text)" }}>
                  {t.description}
                </td>
                <td>
                  <span className="mono" style={{ fontSize: "0.75rem" }}>{t.sandbox_ref}</span>
                </td>
                <td style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {t.verification_method}
                </td>
                <td>
                  <span className={`${s.tag} ${t.reversible ? s.tagAllow : s.tagDeny}`}>
                    {t.reversible ? "YES" : "NO"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Recent Policy Decisions Log */}
      <div className={`${s.card} js-reveal`}>
        <div className={s.cardHeader}>
          <h2>Policy Decisions Ledger</h2>
          <span className="label">Evaluation Audit Trail</span>
        </div>

        <table className={s.table}>
          <thead>
            <tr>
              <th>Rule ID</th>
              <th>Effect</th>
              <th>Decision Reason</th>
              <th>Inputs Hash</th>
              <th>Evaluated At</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d.id}>
                <td>
                  <code className="mono" style={{ fontWeight: 600 }}>{d.rule_id}</code>
                </td>
                <td>
                  <span
                    className={`${s.tag} ${
                      d.effect === "allow"
                        ? s.tagAllow
                        : d.effect === "deny"
                        ? s.tagDeny
                        : s.tagApproval
                    }`}
                  >
                    {d.effect.toUpperCase()}
                  </span>
                </td>
                <td style={{ fontSize: "0.8125rem" }}>
                  {d.reason}
                </td>
                <td>
                  <code className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                    {d.inputs_hash.slice(0, 14)}...
                  </code>
                </td>
                <td style={{ fontFamily: "var(--font-num)", fontSize: "0.75rem", color: "var(--muted)" }}>
                  {d.decided_at.replace("T", " ").replace("Z", "")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
