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
import s from "../pages.module.css";

export default function AuditLedger() {
  const { data: chainReport, reload: reloadChain } = useApi<AuditChainReport>("/v1/audit/verify");
  // The ledger for the tenant, not a hardcoded demo workflow that 404s.
  const { data: auditEvents, loading } = useApi<AuditEvent[]>("/v1/audit/events?limit=200");
  const toast = useToast();
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>("");
  const [verifying, setVerifying] = useState(false);

  // NO FALLBACK. `chain` is a tamper-evidence result: rendering a substituted
  // "chain intact" while the API is unreachable would assert an integrity
  // verification that never ran. That is the single most dishonest thing this
  // screen could do, so an unreachable verifier renders as UNVERIFIED instead.
  const chain = chainReport;
  const events = auditEvents ?? [];

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [events.length],
  );

  const handleVerifyChain = async () => {
    setVerifying(true);
    try {
      // Report what the verifier ACTUALLY returned. Announcing success on a
      // run that came back ok:false would hide a detected tamper, so read the
      // response directly rather than trusting cached state.
      const result = (await api.get("/v1/audit/verify")) as AuditChainReport | null;
      reloadChain();
      if (!result) {
        toast.push({
          tone: "bad",
          title: "Verifier Unreachable",
          body: "No integrity check ran. Ledger state is unknown, not intact.",
        });
      } else if (result.ok) {
        toast.push({
          tone: "ok",
          title: "Verification Complete",
          body: `${result.checked} events cryptographically verified intact.`,
        });
      } else {
        toast.push({
          tone: "bad",
          critical: true,
          title: "TAMPER DETECTED",
          body: `Hash chain broken at seq ${result.first_break_seq ?? "unknown"}. ${result.detail ?? ""}`,
        });
      }
    } catch {
      toast.push({ tone: "bad", title: "Verification Failed", body: "Hash chain integrity check could not complete." });
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

      {/* Chain Status Banner.
          Three distinct states, never two. "Not verified" is its own outcome
          and must never be rendered as "intact". */}
      <div
        className={`${s.card} js-reveal`}
        style={{
          borderLeft: !chain
            ? "4px solid var(--muted)"
            : chain.ok
              ? "4px solid #2e7d32"
              : "4px solid #c62828",
          marginBottom: 24,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name={!chain ? "critical" : chain.ok ? "check" : "critical"} size={18} />
              <strong style={{ fontSize: "1.0625rem" }}>
                {!chain
                  ? "Chain Integrity NOT Verified"
                  : chain.ok
                    ? "Cryptographic Chain Intact"
                    : "Integrity Failure Detected"}
              </strong>
            </div>
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0" }}>
              {!chain
                ? "The verifier could not be reached, so no integrity check has run. This is NOT a statement that the ledger is intact — it is unknown."
                : (chain.detail ?? `Verified ${chain.checked} consecutive events in SHA-256 monotonic sequence.`)}
            </p>
          </div>
          <span
            className={`${s.tag} ${!chain ? "" : chain.ok ? s.tagVerified : s.tagFailed}`}
          >
            {!chain ? "UNVERIFIED" : chain.ok ? "VALID" : "BROKEN"}
          </span>
        </div>
      </div>

      <div className={`${s.kpiStrip} js-reveal`}>
        <MetricTile
          label="Events Verified"
          value={chain ? String(chain.checked) : "—"}
          foot={chain ? undefined : "verifier unreachable"}
        />
        <MetricTile label="Hash Algorithm" value="SHA-256" />
        <MetricTile
          label="First Break Seq"
          value={!chain ? "—" : chain.first_break_seq === null ? "None" : String(chain.first_break_seq)}
          foot={chain ? undefined : "verifier unreachable"}
        />
        <MetricTile
          label="Ledger Events Loaded"
          value={String(events.length)}
        />
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
