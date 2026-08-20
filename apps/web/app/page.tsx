"use client";

/**
 * Landing. Scroll-led, restrained, operational. Not a dashboard, not a pitch
 * deck: three claims about how the system behaves, each one demonstrated with
 * the same components the operator sees.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Layer } from "@deck.gl/core";
import { CityMap } from "@/components/map/CityMap";
import { EvidenceChip } from "@/components/ui/EvidenceChip";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Icon } from "@/components/ui/Icon";
import { useShell } from "@/components/shell/ShellState";
import { useGsap, sectionReveal } from "@/lib/motion";
import { CITY, EVIDENCE } from "@/lib/fixtures";
import s from "./landing.module.css";

/** deck.gl fill per severity. RGBA — the map is never the only signal. */
const SEVERITY_TINT: Record<string, [number, number, number, number]> = {
  critical: [180, 35, 24, 190],
  major: [250, 129, 40, 190],
  minor: [138, 90, 0, 170],
  info: [91, 91, 91, 150],
};

const STEPS = [
  {
    title: "Observe",
    body: "Connectors stream the city in: hydrology SCADA, IMD nowcasts, pump telemetry, CCTV vision, citizen reports, satellite extent. Every event is validated, deduplicated and either promoted to evidence or quarantined.",
    note: "Freshness and trust tier travel with the datum, not with the dashboard.",
  },
  {
    title: "Ground",
    body: "Nothing the system says exists without evidence behind it. A fact or a forecast that arrives with an empty evidence list is rejected server-side, before it can reach a screen.",
    note: "Enforced in code, not in a prompt.",
  },
  {
    title: "Decide",
    body: "Risk is computed from the action, the asset, the blast radius and the age of the evidence. Policy is deterministic Python that no model output can influence. High-risk and public-facing actions stop and wait for a named human.",
    note: "The same tool can be routine on one asset and require an approver on another.",
  },
  {
    title: "Verify",
    body: "Every effect goes through one gateway, carries an idempotency key and is confirmed by reading the world back. A timeout is recorded as unknown — never as success.",
    note: "The ledger is append-only and hash-chained, so the record cannot be quietly edited.",
  },
];

export default function Landing() {
  const { incidents, dataMode } = useShell();
  const [layers, setLayers] = useState<Layer[]>([]);

  const heroRef = useGsap<HTMLDivElement>((_, el) => {
    sectionReveal(el, ".js-reveal", { stagger: 0.055, start: "top 95%" });
  }, []);
  const pillarsRef = useGsap<HTMLElement>((_, el) => sectionReveal(el), []);
  const howRef = useGsap<HTMLElement>((_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.06 }), []);
  const closeRef = useGsap<HTMLElement>((_, el) => sectionReveal(el), []);

  const markers = useMemo(
    () =>
      incidents
        .map((i) => {
          const c = (i.geometry as { coordinates?: [number, number] } | null)?.coordinates;
          return c
            ? {
                id: i.id,
                label: i.title,
                detail: `${i.severity} · ${i.state.replace("_", " ")}`,
                coordinates: c,
              }
            : null;
        })
        .filter((m): m is NonNullable<typeof m> => m !== null),
    [incidents],
  );

  // deck.gl loads on the client only, after the shell is interactive.
  useEffect(() => {
    if (!markers.length) return;
    let cancelled = false;
    import("@deck.gl/layers").then(({ ScatterplotLayer }) => {
      if (cancelled) return;
      setLayers([
        new ScatterplotLayer({
          id: "incidents",
          data: markers.map((m, i) => ({
            ...m,
            severity: incidents[i]?.severity ?? "info",
          })),
          getPosition: (d: { coordinates: [number, number] }) => d.coordinates,
          getRadius: 260,
          radiusMinPixels: 7,
          radiusMaxPixels: 26,
          stroked: true,
          lineWidthMinPixels: 2,
          getFillColor: (d: { severity: string }) => SEVERITY_TINT[d.severity] ?? [91, 91, 91, 140],
          getLineColor: [17, 17, 17, 200],
          pickable: false,
        }) as unknown as Layer,
      ]);
    });
    return () => {
      cancelled = true;
    };
  }, [markers, incidents]);

  return (
    <>
      {/* ---------------------------------------------------------- hero */}
      <section className={`container ${s.hero}`} ref={heroRef}>
        <div className={s.heroGrid}>
          <div>
            <span className={`${s.place} js-reveal`}>
              <span className={s.pulse} aria-hidden="true" />
              {CITY.name} · {CITY.region}
            </span>

            <h1 className={`${s.title} js-reveal`}>
              <span>See the city.</span>
              <span>Understand the evidence.</span>
              <span>Act with authority.</span>
            </h1>

            <p className={`${s.heroLede} js-reveal`}>
              Auralis is the operations layer between a city&apos;s sensors and the
              people accountable for what happens next. Every statement carries the
              evidence behind it. Every action carries the authority that permitted
              it. Every outcome can be reconstructed afterwards, in order.
            </p>

            <div className={`${s.ctas} js-reveal`}>
              <Link className="btn btn--primary" href="/command">
                Enter Command Center
                <Icon name="arrowRight" size={16} />
              </Link>
              <Link className="btn" href="#how">
                See how it works
              </Link>
            </div>

            <div className={`${s.heroFacts} js-reveal`}>
              <div className={s.fact}>
                <span className={s.factValue}>{incidents.length || "—"}</span>
                <span className={s.factLabel}>Open incidents</span>
              </div>
              <div className={s.fact}>
                <span className={s.factValue}>6</span>
                <span className={s.factLabel}>Connectors</span>
              </div>
              <div className={s.fact}>
                <span className={s.factValue}>R0–R5</span>
                <span className={s.factLabel}>Computed risk tiers</span>
              </div>
            </div>
          </div>

          <div className="js-reveal">
            <CityMap
              layers={layers}
              markers={markers}
              interactive={false}
              height="min(58vh, 520px)"
              summary={`${markers.length} open incidents plotted on the live city view${
                dataMode === "fixture" ? ", from bundled demo data" : ""
              }`}
            />
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- pillars */}
      <section className="container section" ref={pillarsRef} aria-labelledby="proof">
        <div className={s.sectionHead}>
          <span className="eyebrow js-reveal">What holds it up</span>
          <h2 id="proof" className={`${s.sectionTitle} js-reveal`}>
            Three properties, enforced in code rather than promised in copy.
          </h2>
        </div>

        <div className={s.pillars}>
          <article className={`${s.pillar} js-reveal`}>
            <span className={s.pillarIndex}>01</span>
            <h3 className={s.pillarTitle}>Verified evidence</h3>
            <p className={s.pillarBody}>
              Every claim on every screen is bound to the observations that
              support it, with the source, the trust tier and the age attached.
              Stale, conflicting and synthetic data are labelled in words, not by
              a colour you have to remember.
            </p>
            <div className={s.pillarDemo}>
              <span className="label">How it renders</span>
              <EvidenceChip evidence={EVIDENCE[0]} readOnly />
              <EvidenceChip evidence={EVIDENCE[2]} readOnly />
            </div>
          </article>

          <article className={`${s.pillar} js-reveal`}>
            <span className={s.pillarIndex}>02</span>
            <h3 className={s.pillarTitle}>Bounded autonomy</h3>
            <p className={s.pillarBody}>
              Risk is computed per action from the asset, the blast radius and
              the freshness of the evidence — the same tool is routine in one
              place and requires a named approver in another. Denials state the
              rule and the reason, and cannot be clicked away.
            </p>
            <div className={s.pillarDemo}>
              <RiskBadge tier="R4" reason="1,240 premises downstream, public facing" />
              <p className={s.pillarBody} style={{ fontSize: "var(--fs-xs)" }}>
                <Icon name="lock" size={13} /> RULE.PUBLIC.SIREN.EVIDENCE_AGE —
                mass alerting needs corroboration newer than 600 s.
              </p>
            </div>
          </article>

          <article className={`${s.pillar} js-reveal`}>
            <span className={s.pillarIndex}>03</span>
            <h3 className={s.pillarTitle}>Reconstructable actions</h3>
            <p className={s.pillarBody}>
              The ledger is append-only and hash-chained. Any decision can be
              replayed from the evidence that existed at the time, through the
              policy that applied, to the read-back that verified the effect.
            </p>
            <div className={s.pillarDemo}>
              {["incident.detected", "policy.evaluated", "action.verified"].map((k, i) => (
                <p
                  key={k}
                  className={s.pillarBody}
                  style={{ fontSize: "var(--fs-xs)", display: "flex", gap: 8 }}
                >
                  <span className="num">{String(i + 1).padStart(2, "0")}</span>
                  <Icon name="check" size={13} />
                  {k}
                </p>
              ))}
            </div>
          </article>
        </div>
      </section>

      {/* ------------------------------------------------------------ how */}
      <section className="container section" id="how" ref={howRef} aria-labelledby="how-title">
        <div className={s.sectionHead}>
          <span className="eyebrow js-reveal">How it works</span>
          <h2 id="how-title" className={`${s.sectionTitle} js-reveal`}>
            Observe, ground, decide, verify. In that order, every time.
          </h2>
        </div>

        <div className={s.steps}>
          {STEPS.map((step, i) => (
            <div className={`${s.step} js-reveal`} key={step.title}>
              <span className={s.stepNum}>{String(i + 1).padStart(2, "0")}</span>
              <div>
                <h3 className={s.stepTitle}>{step.title}</h3>
                <p className={s.stepBody}>{step.body}</p>
              </div>
              <p className={s.stepNote}>{step.note}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- close */}
      <section className="container section" ref={closeRef}>
        <div className={`${s.close} js-reveal`}>
          <span className="eyebrow">Ready when you are</span>
          <h2 className={s.closeTitle}>
            The evidence is already on the table. Go and look.
          </h2>
          <p className="lede">
            The command centre opens on live incidents for {CITY.name}, with the
            twin, the action queue and the audit ledger one click away.
          </p>
          <div className={s.ctas}>
            <Link className="btn btn--primary" href="/command">
              Enter Command Center
              <Icon name="arrowRight" size={16} />
            </Link>
            <Link className="btn" href="/public">
              View the public status page
            </Link>
          </div>
        </div>

        <footer className={s.foot}>
          <span>
            Auralis · {CITY.name}, {CITY.region}
          </span>
          <span>
            Evidence-grounded operations. Severity, verification and permission are
            never signalled by colour alone.
          </span>
        </footer>
      </section>
    </>
  );
}
