"use client";

/**
 * Trace — AI Trace & Decision Replay.
 * Reconstruct any operational decision from raw observation, through agent synthesis,
 * policy evaluation, tool invocation, and physical read-back verification.
 */

import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { EvidenceChip } from "@/components/ui/EvidenceChip";
import { ClaimBlock } from "@/components/ui/ClaimBlock";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import type { TwinQueryResult, IncidentDetail, AuditEvent } from "@/lib/types";
import { TWIN as FIXTURE_TWIN, INCIDENT_DETAIL as FIXTURE_INCIDENT, AUDIT as FIXTURE_AUDIT } from "@/lib/fixtures";
import s from "../pages.module.css";

export default function TracePage() {
  const { data: twinData } = useApi<TwinQueryResult>("/v1/twin/query?asset_id=ast_gate_bd04&depth=2");
  const { data: incidentDetail } = useApi<IncidentDetail>("/v1/incidents/inc_budameru_01");
  const { data: auditEvents } = useApi<AuditEvent[]>("/v1/audit/wf_budameru_01");

  const [activeStep, setActiveStep] = useState<number>(0);

  const twin = twinData ?? FIXTURE_TWIN;
  const detail = incidentDetail ?? FIXTURE_INCIDENT;
  const audit = auditEvents ?? FIXTURE_AUDIT;

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.05 }),
    [],
  );

  const STEPS = [
    {
      num: "01",
      title: "Observe: Raw Telemetry & Ingestion",
      desc: "Hydrology SCADA, citizen reports, and IMD nowcasts arrived with statutory/certified trust tiers.",
      data: detail.evidence,
    },
    {
      num: "02",
      title: "Ground: Agent Claims Synthesis",
      desc: "Specialist agents extracted structured assertions, linking every claim directly to evidence IDs.",
      data: detail.claims,
    },
    {
      num: "03",
      title: "Twin: Dependency & Blast Radius Analysis",
      desc: "Queried topological graph to calculate 1,240 downstream premises exposed to flood risks.",
      data: twin,
    },
    {
      num: "04",
      title: "Decide: Deterministic Policy Evaluation",
      desc: "Evaluated RULE.PUMP.CAPACITY.R2 (Allow) and RULE.GATE.CLOSE.R4 (Requires Approval).",
      data: detail.incident,
    },
    {
      num: "05",
      title: "Verify: Tool Gateway & Sensor Read-back",
      desc: "Idempotency key checked, units set to 4, verified via SCADA telemetry after 60s.",
      data: audit,
    },
  ];

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Assure · Decision Provenance</span>
          <h1>AI Trace & Decision Replay</h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span className="mono" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Workflow: wf_budameru_01
          </span>
          <span className={s.badge} data-severity="critical">
            Closed Loop Verified
          </span>
        </div>
      </div>

      {/* Decision Pipeline Stepper */}
      <div className={`${s.card} js-reveal`} style={{ marginBottom: 24 }}>
        <div className={s.cardHeader}>
          <h2>Causal Decision Pipeline</h2>
          <span className="label">Step-by-Step Replay</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
          {STEPS.map((st, i) => (
            <button
              key={st.num}
              type="button"
              onClick={() => setActiveStep(i)}
              style={{
                textAlign: "left",
                padding: 14,
                borderRadius: "var(--r-control)",
                border: activeStep === i ? "2px solid var(--accent)" : "1px solid var(--line)",
                background: activeStep === i ? "var(--surface)" : "transparent",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <span className="mono" style={{ fontWeight: 700, color: activeStep === i ? "var(--accent)" : "var(--muted)" }}>
                  {st.num}
                </span>
                {i < 4 && <Icon name="arrowRight" size={14} />}
              </div>
              <strong style={{ fontSize: "0.875rem", display: "block", color: "var(--text)" }}>
                {st.title.split(":")[0]}
              </strong>
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                {st.title.split(":")[1]}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Main Trace Content Split */}
      <div className={`${s.splitView} js-reveal`}>
        {/* Active Stage Details */}
        <div>
          <div className={s.card} style={{ marginBottom: 20 }}>
            <div className={s.cardHeader}>
              <div>
                <span className="mono" style={{ fontSize: "0.75rem", color: "var(--accent)", fontWeight: 700 }}>
                  STAGE {STEPS[activeStep].num}
                </span>
                <h3 style={{ fontSize: "1.125rem", marginTop: 4 }}>{STEPS[activeStep].title}</h3>
              </div>
            </div>
            <p style={{ color: "var(--muted)", fontSize: "0.875rem", marginBottom: 20 }}>
              {STEPS[activeStep].desc}
            </p>

            {/* Stage-specific components */}
            {activeStep === 0 && (
              <div>
                <h4 className={s.sectionTitle}>Supporting Evidence</h4>
                <div className={s.chipRow}>
                  {detail.evidence.map((ev) => (
                    <EvidenceChip key={ev.id} evidence={ev} readOnly />
                  ))}
                </div>
              </div>
            )}

            {activeStep === 1 && (
              <div>
                <h4 className={s.sectionTitle}>Grounded Assertions</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {detail.claims.map((cl) => (
                    <ClaimBlock key={cl.id} claim={cl} />
                  ))}
                </div>
              </div>
            )}

            {activeStep === 2 && (
              <div>
                <h4 className={s.sectionTitle}>Digital Twin Topology & Blast Radius</h4>
                <div className={s.kpiStrip} style={{ marginBottom: 16 }}>
                  <div className={s.stat}>
                    <span className={s.statValue}>{twin.blast_radius}</span>
                    <span className={s.statLabel}>Downstream premises</span>
                  </div>
                  <div className={s.stat}>
                    <span className={s.statValue}>{twin.nodes.length}</span>
                    <span className={s.statLabel}>Connected Assets</span>
                  </div>
                  <div className={s.stat}>
                    <span className={s.statValue}>{twin.traversal_ms}ms</span>
                    <span className={s.statLabel}>Graph Traversal</span>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {twin.nodes.map((node) => (
                    <div key={node.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", border: "1px solid var(--line)", borderRadius: "var(--r-control)" }}>
                      <div>
                        <strong>{node.name}</strong>
                        <span className="mono" style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: 8 }}>({node.kind})</span>
                      </div>
                      <span className={s.badge}>Depth {node.depth}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activeStep === 3 && (
              <div>
                <h4 className={s.sectionTitle}>Deterministic Policy Evaluation</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ padding: 14, border: "1px solid var(--line)", borderRadius: "var(--r-control)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <code className="mono">RULE.PUMP.CAPACITY.R2</code>
                      <span className={`${s.tag} ${s.tagAllow}`}>ALLOW</span>
                    </div>
                    <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: 0 }}>
                      Reversible pump capacity change within operator standing authority.
                    </p>
                  </div>
                  <div style={{ padding: 14, border: "1px solid var(--accent)", borderRadius: "var(--r-control)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <code className="mono">RULE.GATE.CLOSE.R4</code>
                      <span className={`${s.tag} ${s.tagApproval}`}>REQUIRE_APPROVAL</span>
                    </div>
                    <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: 0 }}>
                      Affects 1,240 premises downstream and is public-facing. Dual named approver required.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {activeStep === 4 && (
              <div>
                <h4 className={s.sectionTitle}>Physical Outcome Verification</h4>
                <div style={{ padding: 16, background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "var(--r-control)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <Icon name="check" size={18} />
                    <strong>Outcome Verified: SUCCESS</strong>
                  </div>
                  <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: 0 }}>
                    SCADA telemetry confirmed Ajit Singh Nagar Pump Station increased to 4 running units. Rate of rise reduced by 0.28 m/h within 120 seconds.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Audit Log Timeline Rail */}
        <div className={s.rail}>
          <div className={s.card}>
            <div className={s.cardHeader}>
              <h3 className={s.sectionTitle}>Immutable Audit Chain</h3>
              <span className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>sha256 verified</span>
            </div>

            <div className={s.timeline}>
              {audit.map((evt, idx) => (
                <div key={evt.id} className={s.timelineItem}>
                  <span className={s.timelineTime}>{evt.at.split("T")[1]?.slice(0, 8) ?? "—"}</span>
                  <div className={s.timelineDot} data-active={idx <= activeStep + 2} />
                  <div>
                    <strong style={{ fontSize: "0.8125rem", display: "block" }}>{evt.kind}</strong>
                    <span className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                      by {evt.actor_id} ({evt.actor_kind})
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
