"use client";

/**
 * Public Status — Redacted, disclosure-delayed public situational advisory portal.
 * Designed for citizens and media: clear plain-language advisories with no raw SCADA telemetry
 * or internal sensitive asset states.
 */

import { useApi } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { useGsap, sectionReveal } from "@/lib/motion";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import s from "../pages.module.css";

interface Advisory {
  id: string;
  area: string;
  status: string;
  guidance: string;
  severity: "critical" | "major" | "minor" | "info";
}

interface PublicStatusData {
  city: string;
  updated_at: string;
  disclosure_delay_s: number;
  advisories: Advisory[];
  redactions: string[];
}

export default function PublicStatusPage() {
  const { location } = useShell();
  const { data: statusData, loading } = useApi<PublicStatusData>("/v1/public/status");
  // NO SILENT SUBSTITUTION. This is the citizen-facing surface. Publishing
  // fabricated incident status to the public — or worse, a fabricated "all
  // clear" — is the most damaging failure this system could have.
  const status = statusData;

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [],
  );

  if (!status) {
    return (
      <section className="container section" style={{ maxWidth: 880, marginInline: "auto" }}>
        <h1>City Status</h1>
        <div className={s.card} style={{ marginTop: 16 }}>
          <strong>Status information is currently unavailable.</strong>
          <p style={{ color: "var(--muted)", marginTop: 8, fontSize: "0.9375rem" }}>
            We cannot reach the verified incident feed, so no status is shown.
            This is <strong>not</strong> a statement that there are no active
            incidents. For emergencies call <strong>112</strong>. For local
            disaster information contact the district authority.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="container section" ref={ref} style={{ maxWidth: 880, marginInline: "auto" }}>
      <div className={`${s.pageHeader} js-reveal`}>
        <div>
          <span className="eyebrow">{location.name} · Public service</span>
          <h1 style={{ marginTop: 4 }}>Live City Safety & Flood Advisories</h1>
        </div>
        <span className={`${s.tag} ${s.tagProposed}`}>Public Access Mode</span>
      </div>

      {/* Delayed Disclosure Notice Banner */}
      <div className={`${s.card} js-reveal`} style={{ background: "rgba(0,0,0,0.02)", marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Icon name="shield" size={16} />
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: 0 }}>
            Official verified status. Real-time engineering telemetry undergoes a mandatory{" "}
            <strong>{status.disclosure_delay_s / 60}-minute verification & disclosure window</strong>{" "}
            before publication.
          </p>
        </div>
      </div>

      {/* Active Advisories List */}
      <div className="js-reveal">
        <h2 className={s.sectionTitle}>Active Civil Advisories ({status.advisories.length})</h2>

        {loading && !status.advisories.length ? (
          <Skeleton lines={6} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {status.advisories.map((adv) => (
              <article
                key={adv.id}
                className={s.publicCard}
                style={{
                  borderLeft:
                    adv.severity === "critical"
                      ? "4px solid #c62828"
                      : adv.severity === "major"
                      ? "4px solid var(--accent)"
                      : "4px solid var(--line-strong)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 8 }}>
                  <div>
                    <span className="label" style={{ color: "var(--muted)" }}>
                      Affected Area: {adv.area}
                    </span>
                    <h3 style={{ marginTop: 4 }}>{adv.status}</h3>
                  </div>
                  <span
                    className={s.badge}
                    data-severity={adv.severity}
                    style={{ textTransform: "uppercase", fontSize: "0.6875rem", fontWeight: 700 }}
                  >
                    {adv.severity}
                  </span>
                </div>

                <div style={{ padding: "12px 16px", background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "var(--r-control)", marginTop: 12 }}>
                  <strong style={{ fontSize: "0.875rem", display: "block", marginBottom: 4 }}>
                    Public Guidance & Action:
                  </strong>
                  <p style={{ fontSize: "0.875rem", color: "var(--text)", margin: 0, lineHeight: 1.5 }}>
                    {adv.guidance}
                  </p>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* Redactions Policy Disclosure */}
      <div className={`${s.card} js-reveal`} style={{ marginTop: 28 }}>
        <h3 className={s.sectionTitle}>Privacy & Operational Redactions</h3>
        <ul style={{ margin: 0, paddingLeft: 20, fontSize: "0.8125rem", color: "var(--muted)" }}>
          {status.redactions.map((redaction, idx) => (
            <li key={idx}>{redaction}</li>
          ))}
          <li>Citizen reporting identities and location coordinates are protected under municipal privacy protocols.</li>
        </ul>
      </div>
    </section>
  );
}
