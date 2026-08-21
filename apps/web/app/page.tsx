"use client";

/**
 * Landing — /
 *
 * Scroll-led and restrained. Four sections, four different layout families,
 * one dominant visual each. The hero states the promise; the pillars state
 * what backs it; the vocabulary section shows the actual trust states this
 * interface renders, because that vocabulary IS the product.
 *
 * Every number on this page is read from the API. Nothing falls back to a
 * plausible figure: when a value cannot be verified the page says so, in the
 * same place the number would have been.
 */

import Link from "next/link";
import { useApi } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { useGsap, sectionReveal } from "@/lib/motion";
import { Icon, NoData, type IconName } from "@/components/ui";
import { num } from "@/lib/format";
import type { AuditChainReport, OpsMetrics } from "@/lib/types";
import s from "./landing.module.css";

interface Pillar {
  n: string;
  title: string;
  body: string;
  proof: string;
  icon: IconName;
  href: string;
  cta: string;
}

const PILLARS: Pillar[] = [
  {
    n: "01",
    title: "Verified evidence",
    body: "A fact on this platform carries the records it came from, the source that reported them and the moment they were observed. A statement with no evidence behind it cannot be stored, so it can never reach a screen.",
    proof: "Grounding is enforced in the data layer, not in a prompt.",
    icon: "fact",
    href: "/data-health",
    cta: "Inspect every source",
  },
  {
    n: "02",
    title: "Bounded autonomy",
    body: "Risk tier is computed from the target, the blast radius and the age of the evidence, then checked against a policy bundle that lives outside the model. No output from any agent can change that outcome.",
    proof: "The same tool is R2 on one asset and R4 on another.",
    icon: "lock",
    href: "/governance",
    cta: "Read the policy bundle",
  },
  {
    n: "03",
    title: "Reconstructable actions",
    body: "Every decision leaves a hash-chained trail from claim to evidence to model version to tool manifest to policy decision to verified outcome. You can replay it, export it, and check the chain yourself.",
    proof: "Chain verification is an endpoint, not a promise.",
    icon: "trace",
    href: "/audit",
    cta: "Verify the ledger",
  },
];

interface StateSpec {
  label: string;
  kind: string;
  meaning: string;
  icon: IconName;
}

/** The full vocabulary. If a surface cannot say which of these it is, it does not render. */
const VOCABULARY: StateSpec[] = [
  {
    label: "Fact",
    kind: "fact",
    meaning: "Verified observation, with its source, its timestamp and its freshness.",
    icon: "fact",
  },
  {
    label: "Forecast",
    kind: "forecast",
    meaning: "Model output. Always drawn as a range, never reported as one number.",
    icon: "forecast",
  },
  {
    label: "Recommendation",
    kind: "recommendation",
    meaning: "A proposed action. Never styled to look like something already true.",
    icon: "recommendation",
  },
  {
    label: "Unverified",
    kind: "unverified",
    meaning: "Present on the record, but not corroborated by a second source.",
    icon: "unknown",
  },
  {
    label: "Stale",
    kind: "stale",
    meaning: "Past its freshness window. Shown degraded, with the last verified time.",
    icon: "clock",
  },
  {
    label: "Conflict",
    kind: "conflict",
    meaning: "Two sources disagree. Both are shown, both are named, neither is hidden.",
    icon: "critical",
  },
  {
    label: "Unavailable",
    kind: "unavailable",
    meaning: "The source is down or unconfigured. The gap is reported, never filled.",
    icon: "offline",
  },
  {
    label: "Simulation",
    kind: "simulation",
    meaning: "Fabricated for a sandbox run. Hatched, labelled, barred from production tools.",
    icon: "synthetic",
  },
];

export default function LandingPage() {
  const { incidents, streamStatus } = useShell();
  const { data: ops, error: opsError } = useApi<OpsMetrics>("/v1/metrics/ops");
  const { data: chain, error: chainError } = useApi<AuditChainReport>("/v1/audit/verify");

  const ref = useGsap<HTMLDivElement>((_, el) => {
    el.querySelectorAll<HTMLElement>("[data-reveal]").forEach((section) =>
      sectionReveal(section, ".js-reveal", { stagger: 0.055, start: "top 84%" }),
    );
  }, []);

  const openIncidents = incidents.filter((i) => i.state !== "closed").length;
  const sources = ops?.source_health ?? [];
  const freshSources = sources.filter((c) => c.fresh).length;

  return (
    <div className={s.page} ref={ref}>
      {/* ============================================================ hero */}
      <section className={s.hero} data-reveal>
        <div className={`container ${s.heroInner}`}>
          <div className={s.heroCopy}>
            <h1 className={`${s.heroTitle} js-reveal`}>
              See the city.
              <br />
              Understand the evidence.
              <br />
              <span className={s.heroAccent}>Act with authority.</span>
            </h1>
            <p className={`${s.heroLede} js-reveal`}>
              An operations layer for city infrastructure where every claim carries its
              evidence and every action carries its authorisation.
            </p>
            <div className={`${s.heroCta} js-reveal`}>
              <Link className="btn btn--primary" href="/command">
                Open Command Center
                <Icon name="arrowRight" size={16} />
              </Link>
              <Link className="btn" href="/trace">
                Follow a decision
              </Link>
            </div>
          </div>

          {/* The one dominant visual: the live state of the platform, honestly. */}
          <aside className={`${s.vitals} js-reveal`} aria-label="Platform state">
            <div className={s.vitalsHead}>
              <span className="label">Right now</span>
              <span className={s.vitalsStream} data-state={streamStatus}>
                <Icon
                  name={streamStatus === "live" ? "activity" : "offline"}
                  size={13}
                />
                {streamStatus === "live"
                  ? "Stream live"
                  : streamStatus === "connecting"
                    ? "Connecting"
                    : "Stream degraded"}
              </span>
            </div>

            <dl className={s.vitalsGrid}>
              <div className={s.vital}>
                <dt>Open incidents</dt>
                <dd>
                  <span className={s.vitalNum}>{num(openIncidents)}</span>
                </dd>
              </div>

              <div className={s.vital}>
                <dt>Sources within their freshness window</dt>
                <dd>
                  {sources.length > 0 ? (
                    <span className={s.vitalNum}>
                      {num(freshSources)}
                      <span className={s.vitalOf}>of {num(sources.length)}</span>
                    </span>
                  ) : (
                    <NoData reason={opsError ? "unavailable" : "unverified"} />
                  )}
                </dd>
              </div>

              <div className={s.vital}>
                <dt>Audit entries, hash chain</dt>
                <dd>
                  {chain ? (
                    <span className={s.vitalNum}>
                      {num(chain.checked)}
                      <span
                        className={s.vitalVerdict}
                        data-ok={chain.ok}
                      >
                        <Icon name={chain.ok ? "check" : "critical"} size={13} />
                        {chain.ok
                          ? "chain intact"
                          : `break at ${chain.first_break_seq ?? "unknown"}`}
                      </span>
                    </span>
                  ) : (
                    <NoData reason={chainError ? "unavailable" : "unverified"} />
                  )}
                </dd>
              </div>
            </dl>

            <p className={s.vitalsFoot}>
              Read from the running API. Where a value could not be verified this panel
              says so instead of showing a number.
            </p>
          </aside>
        </div>
      </section>

      {/* ========================================================= pillars */}
      <section className={s.pillars} data-reveal aria-labelledby="pillars-title">
        <div className="container">
          <h2 id="pillars-title" className={`${s.sectionTitle} js-reveal`}>
            Three things hold this up.
          </h2>

          <div className={s.pillarList}>
            {PILLARS.map((pl) => (
              <article key={pl.n} className={`${s.pillar} js-reveal`}>
                <span className={s.pillarN} aria-hidden="true">
                  {pl.n}
                </span>
                <div className={s.pillarBody}>
                  <h3 className={s.pillarTitle}>
                    <Icon name={pl.icon} size={18} />
                    {pl.title}
                  </h3>
                  <p className={s.pillarText}>{pl.body}</p>
                  <p className={s.pillarProof}>{pl.proof}</p>
                  <Link className={s.pillarLink} href={pl.href}>
                    {pl.cta}
                    <Icon name="arrowRight" size={14} />
                  </Link>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ====================================================== vocabulary */}
      <section className={s.vocab} data-reveal aria-labelledby="vocab-title">
        <div className="container">
          <div className={`${s.vocabHead} js-reveal`}>
            <h2 id="vocab-title" className={s.sectionTitle}>
              Nothing renders without saying what it is.
            </h2>
            <p className={s.vocabLede}>
              These eight states are the whole vocabulary. A data surface that cannot
              place itself in one of them does not get drawn, because a blank that looks
              like a reading is the failure this platform exists to prevent.
            </p>
          </div>

          <ul className={s.vocabList}>
            {VOCABULARY.map((v) => (
              <li key={v.kind} className={`${s.vocabItem} js-reveal`} data-kind={v.kind}>
                <span className={s.vocabMark} aria-hidden="true">
                  <Icon name={v.icon} size={16} />
                </span>
                <span className={s.vocabLabel}>{v.label}</span>
                <span className={s.vocabMeaning}>{v.meaning}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ============================================================= close */}
      <section className={s.close} data-reveal>
        <div className={`container ${s.closeInner}`}>
          <p className={`${s.closeText} js-reveal`}>
            Every screen in Auralis can be asked the same question: on what evidence,
            under whose authority, and can you prove it.
          </p>
          <div className={`${s.closeCta} js-reveal`}>
            <Link className="btn btn--accent" href="/command">
              Open Command Center
              <Icon name="arrowRight" size={16} />
            </Link>
            <Link className="btn btn--ghost" href="/public">
              See the public view
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
