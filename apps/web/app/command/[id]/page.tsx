"use client";

/**
 * Incident Room — evidence, claims, forecasts, plans for a single incident.
 */

import { useParams } from "next/navigation";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { EvidenceChip } from "@/components/ui/EvidenceChip";
import { ClaimBlock } from "@/components/ui/ClaimBlock";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { StaleBadge } from "@/components/ui/StaleBadge";
import { formatAge } from "@/lib/format";
import type { IncidentDetail, Plan } from "@/lib/types";
import s from "../../pages.module.css";

export default function IncidentRoom() {
  const params = useParams<{ id: string }>();
  const { data: detail, loading, error } = useApi<IncidentDetail>(`/v1/incidents/${params.id}`);
  const { data: plans } = useApi<Plan[]>(`/v1/incidents/${params.id}/plans`);
  const ref = useGsap<HTMLElement>((_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }), [!!detail]);

  if (loading) return <section className="container section"><Skeleton lines={12} /></section>;
  if (error || !detail) {
    return (
      <section className="container section">
        <p className={s.empty}>Incident not found or API unreachable.</p>
        <Link className="btn" href="/command">← Back to Command</Link>
      </section>
    );
  }

  const { incident, evidence, claims, conflicts, forecasts, unknowns, assets, degraded } = detail;

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <Link href="/command" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>← Command Center</Link>
          <h1 style={{ marginTop: 6 }}>{incident.title}</h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span className={s.badge} data-severity={incident.severity}>{incident.severity}</span>
          <span className={s.badge}>{incident.state.replace("_", " ")}</span>
        </div>
      </div>

      {degraded && <p className={s.syntheticBanner}><Icon name="critical" size={16} /> Assessment ran in degraded mode — some claims may lack LLM analysis.</p>}

      <div className={`${s.splitView} js-reveal`}>
        <div>
          {/* Evidence */}
          <h2 className={s.sectionTitle}>Evidence ({evidence.length})</h2>
          <div className={s.chipRow} style={{ marginBottom: 24 }}>
            {evidence.map((ev) => (
              <EvidenceChip key={ev.id} evidence={ev} readOnly />
            ))}
          </div>

          {/* Claims */}
          <h2 className={s.sectionTitle}>Claims ({claims.length})</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 24 }}>
            {claims.map((cl) => (
              <ClaimBlock key={cl.id} claim={cl} />
            ))}
          </div>

          {/* Forecasts */}
          {forecasts.length > 0 && (
            <>
              <h2 className={s.sectionTitle}>Forecasts</h2>
              <div className={s.grid2} style={{ marginBottom: 24 }}>
                {forecasts.map((fc) => (
                  <div key={fc.id} className={s.card}>
                    <div className={s.cardHeader}>
                      <h3>Horizon: {fc.horizon_min} min</h3>
                      <span className="label">{fc.model_version}</span>
                    </div>
                    <div style={{ display: "flex", gap: 20 }}>
                      <div className={s.stat}><span className={s.statValue}>{fc.median}</span><span className={s.statLabel}>Median {fc.unit}</span></div>
                      <div className={s.stat}><span className={s.statValue}>{fc.p10}</span><span className={s.statLabel}>p10</span></div>
                      <div className={s.stat}><span className={s.statValue}>{fc.p90}</span><span className={s.statLabel}>p90</span></div>
                    </div>
                    {!fc.in_envelope && <p style={{ color: "var(--accent)", fontSize: "0.8125rem", marginTop: 8 }}><Icon name="critical" size={14} /> {fc.envelope_note || "Outside model envelope"}</p>}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Unknowns */}
          {unknowns.length > 0 && (
            <>
              <h2 className={s.sectionTitle}>What we don&apos;t know</h2>
              <ul style={{ margin: "0 0 24px", paddingLeft: 20, color: "var(--muted)", fontSize: "0.875rem" }}>
                {unknowns.map((u, i) => <li key={i} style={{ marginBottom: 6 }}>{u}</li>)}
              </ul>
            </>
          )}
        </div>

        <div className={s.rail}>
          {/* Affected assets */}
          <h3 className={s.sectionTitle}>Affected assets</h3>
          {assets.map((a: Record<string, unknown>) => (
            <div key={String(a.id)} className={s.card} style={{ padding: 14 }}>
              <strong>{String(a.name)}</strong>
              <p style={{ fontSize: "0.75rem", color: "var(--muted)", margin: 0 }}>{String(a.kind)}</p>
            </div>
          ))}

          {/* Conflicts */}
          {conflicts.length > 0 && (
            <>
              <h3 className={s.sectionTitle}>Conflicts ({conflicts.length})</h3>
              {conflicts.map((cf) => (
                <div key={cf.id} className={s.card} style={{ borderColor: "var(--accent)" }}>
                  <p style={{ fontWeight: 600, fontSize: "0.875rem" }}>{cf.subject}</p>
                  <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>{cf.impact}</p>
                  <span className={s.badge}>{cf.resolution}</span>
                </div>
              ))}
            </>
          )}

          {/* Plans */}
          <h3 className={s.sectionTitle}>Plans</h3>
          {plans && plans.length > 0 ? (
            plans.map((pl) => (
              <Link key={pl.id} href={`/command/${params.id}/plans`} style={{ textDecoration: "none", color: "inherit" }}>
                <div className={s.card}>
                  <strong>{pl.title}</strong>
                  <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginTop: 4 }}>{pl.status} · {pl.actions.length} actions</p>
                </div>
              </Link>
            ))
          ) : (
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>No plans generated yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}
