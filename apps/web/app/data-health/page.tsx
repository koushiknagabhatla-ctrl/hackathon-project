"use client";

/**
 * Data Health — Source freshness, quality scores, quarantine logs, and active conflicts.
 * Ensures the city's operational model only reflects validated, timely evidence.
 */

import { useState } from "react";
import { useApi } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { MetricTile } from "@/components/ui/MetricTile";
import { Icon } from "@/components/ui/Icon";
import { StaleBadge } from "@/components/ui/StaleBadge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, NoData } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatAge } from "@/lib/format";
import type { ConnectorHealth, EvidenceConflict } from "@/lib/types";
import s from "../pages.module.css";

export default function DataHealth() {
  const {
    data: connectorsData,
    loading,
    error,
    correlationId,
    reload,
  } = useApi<ConnectorHealth[]>("/v1/data-health");
  const { data: conflictsData } = useApi<EvidenceConflict[]>("/v1/conflicts");

  // No fallback list. A source register that quietly shows bundled data would
  // be lying about the exact thing this page exists to report on.
  const connectors = connectorsData ?? [];
  const conflicts = conflictsData ?? [];

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [connectors.length],
  );

  const freshCount = connectors.filter((c) => c.fresh).length;
  const staleCount = connectors.length - freshCount;
  const total24hEvents = connectors.reduce((acc, c) => acc + c.events_24h, 0);
  const totalQuarantined = connectors.reduce((acc, c) => acc + c.quarantined_24h, 0);

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Assure · Sensor Ingestion & Integrity</span>
          <h1>Data Health & Connector Posture</h1>
        </div>
      </div>

      {error && (
        <div className="js-reveal" style={{ marginBottom: 24 }}>
          <ErrorState
            error={error}
            onRetry={reload}
            correlationId={correlationId}
            what="the source register"
          />
        </div>
      )}

      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile label="Active connectors" value={connectorsData ? connectors.length : null} />
        <MetricTile
          label="Within freshness SLA"
          value={connectorsData ? `${freshCount} of ${connectors.length}` : null}
        />
        <MetricTile label="Events ingested, 24h" value={connectorsData ? total24hEvents : null} />
        <MetricTile label="Quarantined, 24h" value={connectorsData ? totalQuarantined : null} />
        <MetricTile label="Open conflicts" value={conflictsData ? conflicts.length : null} />
      </div>

      {staleCount > 0 && (
        <p className={`${s.syntheticBanner} js-reveal`} role="status" style={{ marginBottom: 20 }}>
          <Icon name="clock" size={16} />
          <span>
            <strong>
              {staleCount} of {connectors.length} sources are outside their freshness
              window.
            </strong>{" "}
            Anything derived from them is shown as stale wherever it appears, with the
            last verified time attached. It is not shown as current.
          </span>
        </p>
      )}

      {/* Connectors Table */}
      {loading && !connectors.length ? (
        <Skeleton lines={8} />
      ) : connectors.length === 0 ? (
        <div className="js-reveal" style={{ marginBottom: 24 }}>
          <EmptyState
            icon="offline"
            title="No source register available"
            body="The data-health endpoint returned no connectors. Rather than list sources from a bundled snapshot, this page reports the gap. Every downstream surface treats the same absence as unavailable."
          />
        </div>
      ) : (
        <div className={`${s.card} js-reveal`} style={{ marginBottom: 24 }}>
          <div className={s.cardHeader}>
            <h2>Ingestion Connectors ({connectors.length})</h2>
            <span className="label">Continuous SLA Monitoring</span>
          </div>

          <table className={s.table}>
            <thead>
              <tr>
                <th>Connector Name</th>
                <th>Trust Tier</th>
                <th>Contract</th>
                <th>Freshness SLA</th>
                <th>Last Seen / Age</th>
                <th>Quality Score</th>
                <th>DPIA Status</th>
                <th>24h Volume</th>
                <th>Quarantined</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {connectors.map((conn) => (
                <tr key={conn.id}>
                  <td>
                    <strong>{conn.name}</strong>
                    <span className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)", display: "block" }}>
                      {conn.id}
                    </span>
                  </td>
                  <td>
                    <span className={s.badge}>{conn.trust_tier}</span>
                  </td>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>
                    v{conn.contract_version}
                  </td>
                  <td style={{ fontFamily: "var(--font-num)" }}>
                    {conn.freshness_sla_s}s
                  </td>
                  <td>
                    {conn.age_s !== null ? (
                      <StaleBadge
                        ageS={conn.age_s}
                        fresh={conn.fresh}
                        slaS={conn.freshness_sla_s}
                      />
                    ) : (
                      <NoData reason="never" lastVerifiedAt={conn.last_seen_at} />
                    )}
                  </td>
                  <td style={{ fontFamily: "var(--font-num)" }}>
                    {(conn.quality_score * 100).toFixed(0)}%
                  </td>
                  <td>
                    <span className={`${s.tag} ${conn.dpia_status === "approved" ? s.tagAllow : s.tagApproval}`}>
                      {conn.dpia_status}
                    </span>
                  </td>
                  <td style={{ fontFamily: "var(--font-num)" }}>
                    {conn.events_24h.toLocaleString()}
                  </td>
                  <td style={{ fontFamily: "var(--font-num)", color: conn.quarantined_24h > 0 ? "var(--accent)" : "inherit" }}>
                    {conn.quarantined_24h > 0 ? (
                      <span style={{ fontWeight: 700 }}>{conn.quarantined_24h} held</span>
                    ) : (
                      "0 held"
                    )}
                  </td>
                  <td>
                    <span className={`${s.tag} ${conn.fresh ? s.tagVerified : s.tagFailed}`}>
                      {conn.fresh ? "FRESH" : "STALE"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Active Conflicts List */}
      <div className={`${s.card} js-reveal`}>
        <div className={s.cardHeader}>
          <h2>Open Evidentiary Conflicts ({conflicts.length})</h2>
          <span className="label">Explicit Contradiction Handling</span>
        </div>

        {conflicts.length === 0 ? (
          <p className={s.empty}>No unresolved contradictions detected across active evidence.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {conflicts.map((cf) => (
              <div
                key={cf.id}
                style={{
                  padding: 16,
                  border: "1px solid var(--accent)",
                  borderRadius: "var(--r-control)",
                  background: "var(--surface)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <strong style={{ fontSize: "0.9375rem" }}>{cf.subject}</strong>
                  <span className={`${s.tag} ${s.tagApproval}`}>{cf.resolution}</span>
                </div>
                <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "0 0 12px" }}>
                  <strong>Operational Impact:</strong> {cf.impact}
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div style={{ padding: 10, background: "rgba(0,0,0,0.02)", borderRadius: "var(--r-control)" }}>
                    <span className="label">Source A: {cf.evidence_a.source}</span>
                    <p style={{ fontSize: "0.75rem", margin: "4px 0 0" }}>
                      Trust: {cf.evidence_a.trust_tier} · Age: {formatAge(cf.evidence_a.age_s)}
                    </p>
                  </div>
                  <div style={{ padding: 10, background: "rgba(0,0,0,0.02)", borderRadius: "var(--r-control)" }}>
                    <span className="label">Source B: {cf.evidence_b.source}</span>
                    <p style={{ fontSize: "0.75rem", margin: "4px 0 0" }}>
                      Trust: {cf.evidence_b.trust_tier} · Age: {formatAge(cf.evidence_b.age_s)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
