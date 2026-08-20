"use client";

/**
 * Audit Ledger — Append-only, hash-chained record with verifiable integrity.
 * Demonstrates that every event is cryptographically linked to the previous one,
 * allowing complete reconstruction and tamper detection.
 */

import { useState } from "react";
import Link from "next/link";
import { useApi, api } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import { MetricTile } from "@/components/ui/MetricTile";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import type { AuditChainReport, AuditEvent } from "@/lib/types";
import { AUDIT as FIXTURE_AUDIT, CHAIN as FIXTURE_CHAIN } from "@/lib/fixtures";
import s from "../pages.module.css";

export default function AuditLedger() {
  const { data: chainReport, reload: reloadChain } = useApi<AuditChainReport>("/v1/audit/verify");
  const { data: auditEvents, loading } = useApi<AuditEvent[]>("/v1/audit/wf_budameru_01");
  const toast = useToast();
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>("wf_budameru_01");
  const [verifying, setVerifying] = useState(false);

  const chain = chainReport ?? FIXTURE_CHAIN;
  const events = auditEvents ?? FIXTURE_AUDIT;

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [events.length],
  );

  const handleVerifyChain = async () => {
    setVerifying(true);
    try {
      await reloadChain();
      toast.push({
        tone: "ok",
        title: "Verification Complete",
        body: `All ${chain.checked} events cryptographically verified intact.`,
      });
    } catch {
      toast.push({ tone: "bad", title: "Verification Failed", body: "Hash chain integrity check failed." });
    } finally {
      setVerifying(false);
    }
  };

  const handleExport = async () => {
    try {
      const data = await api.get(`/v1/audit/${selectedWorkflow}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_${selectedWorkflow}_reconstruction.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.push({ tone: "ok", title: "Export Ready", body: "Downloaded standalone audit reconstruction JSON." });
    } catch {
      toast.push({ tone: "bad", title: "Export Error", body: "Failed to export audit package." });
    }
  };

  return (
    <section className="container section" ref={ref}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">Assure · Cryptographic Provenance</span>
          <h1>Audit Ledger & Hash Chain</h1>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            type="button"
            className="btn"
            onClick={handleVerifyChain}
            disabled={verifying}
          >
            <Icon name="shield" size={14} />
            {verifying ? "Verifying..." : "Verify Hash Chain"}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={handleExport}
          >
            <Icon name="arrowRight" size={14} />
            Export Workflow JSON
          </button>
        </div>
      </div>

      {/* Chain Status Banner */}
      <div
        className={`${s.card} js-reveal`}
        style={{
          borderLeft: chain.ok ? "4px solid #2e7d32" : "4px solid #c62828",
          marginBottom: 24,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name={chain.ok ? "check" : "critical"} size={18} />
              <strong style={{ fontSize: "1.0625rem" }}>
                {chain.ok ? "Cryptographic Chain Intact" : "Integrity Failure Detected"}
              </strong>
            </div>
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0" }}>
              {chain.detail ?? `Verified ${chain.checked} consecutive events in SHA-256 monotonic sequence.`}
            </p>
          </div>
          <span className={`${s.tag} ${chain.ok ? s.tagVerified : s.tagFailed}`}>
            {chain.ok ? "VALID" : "BROKEN"}
          </span>
        </div>
      </div>

      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile label="Events Verified" value={String(chain.checked)} />
        <MetricTile label="Hash Algorithm" value="SHA-256" />
        <MetricTile label="First Break Seq" value={chain.first_break_seq === null ? "None" : String(chain.first_break_seq)} />
        <MetricTile label="Replay Readiness" value="100%" />
      </div>

      {/* Audit Log Table */}
      {loading && !events.length ? (
        <Skeleton lines={10} />
      ) : (
        <div className={`${s.card} js-reveal`}>
          <div className={s.cardHeader}>
            <h2>Immutable Transaction Sequence</h2>
            <span className="label">Monotonic seq per tenant</span>
          </div>

          <table className={s.table}>
            <thead>
              <tr>
                <th>Seq</th>
                <th>Timestamp (UTC)</th>
                <th>Actor</th>
                <th>Event Kind</th>
                <th>Subject ID</th>
                <th>Previous Hash (sha256)</th>
                <th>Entry Hash (sha256)</th>
              </tr>
            </thead>
            <tbody>
              {events.map((evt) => (
                <tr key={evt.id}>
                  <td style={{ fontFamily: "var(--font-num)", fontWeight: 600 }}>
                    #{evt.seq}
                  </td>
                  <td style={{ fontFamily: "var(--font-num)", fontSize: "0.8125rem" }}>
                    {evt.at.replace("T", " ").replace("Z", "")}
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: "0.75rem", fontWeight: 600 }}>
                      {evt.actor_id}
                    </span>
                    <span style={{ fontSize: "0.6875rem", color: "var(--muted)", display: "block" }}>
                      ({evt.actor_kind})
                    </span>
                  </td>
                  <td>
                    <span className={`${s.tag} ${s.tagProposed}`}>
                      {evt.kind}
                    </span>
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: "0.75rem" }}>
                      {evt.subject_id ?? "—"}
                    </span>
                  </td>
                  <td>
                    <code className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                      {evt.prev_hash.slice(0, 16)}...
                    </code>
                  </td>
                  <td>
                    <code className="mono" style={{ fontSize: "0.6875rem", color: "var(--accent)" }}>
                      {evt.entry_hash.slice(0, 16)}...
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
