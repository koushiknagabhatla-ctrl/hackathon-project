"use client";

/**
 * Incident Room — /incidents/[id]
 *
 * Progressive disclosure, in this order and no other:
 *   1. SUMMARY   what is established, what is forecast, what is proposed
 *   2. UNKNOWNS  stated before the trace, because a gap is a finding
 *   3. TRACE     specialist agents, conflicts, candidate next steps, policy
 *   4. RAW       the evidence records themselves, behind a disclosure
 *
 * Claim classes are never visually interchangeable: a fact, a forecast and a
 * recommendation carry different edges, different icons and different words,
 * and a forecast always draws its uncertainty as a range rather than stating a
 * single number. If the incident endpoint is unreachable the page renders the
 * UNAVAILABLE state; it never invents a shape to fill.
 */

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { Layer } from "@deck.gl/core";
import { useApi } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import {
  ClaimBlock,
  EmptyState,
  ErrorState,
  EvidenceChip,
  Icon,
  NoData,
  RiskBadge,
  Skeleton,
  StaleBadge,
} from "@/components/ui";
import { CityMap } from "@/components/map/CityMap";
import { stamp, duration, ageSeconds, num } from "@/lib/format";
import type {
  Claim,
  Evidence,
  Forecast,
  IncidentDetail,
  Plan,
  PolicyDecision,
} from "@/lib/types";
import s from "../../pages.module.css";
import r from "./room.module.css";

const CLASS_ORDER: Claim["claim_class"][] = ["fact", "forecast", "recommendation"];

const CLASS_COPY: Record<Claim["claim_class"], { title: string; blurb: string }> = {
  fact: {
    title: "Established",
    blurb: "Verified observation. Every statement below is bound to evidence records.",
  },
  forecast: {
    title: "Forecast",
    blurb:
      "Model output, not observation. Each carries the range it could take, and the range is the answer.",
  },
  recommendation: {
    title: "Proposed",
    blurb:
      "A suggested course of action. Nothing here has been authorised and nothing here has happened.",
  },
};

/** The uncertainty band for one forecast, drawn rather than described. */
function ForecastBand({ f }: { f: Forecast }) {
  const span = Math.max(f.p90 - f.p10, 1e-9);
  const lo = f.p10 - span * 0.35;
  const hi = f.p90 + span * 0.35;
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100;

  return (
    <article className={r.forecast}>
      <header className={r.forecastHead}>
        <span className={r.forecastKind}>
          <Icon name="forecast" size={14} />
          Forecast
        </span>
        <span className={r.forecastModel}>
          {f.model_version} · {f.horizon_min} min horizon
        </span>
      </header>

      <p className={r.forecastLede}>
        Between <strong className="num">{num(f.p10, 2)}</strong> and{" "}
        <strong className="num">{num(f.p90, 2)}</strong> {f.unit}, most likely{" "}
        <strong className="num">{num(f.median, 2)}</strong> {f.unit}.
      </p>

      <div
        className={r.band}
        role="img"
        aria-label={`Forecast range from ${f.p10} to ${f.p90} ${f.unit}, median ${f.median} ${f.unit}.`}
      >
        <div className={r.bandTrack}>
          <div
            className={r.bandFill}
            style={{ left: `${pct(f.p10)}%`, right: `${100 - pct(f.p90)}%` }}
          />
          <div className={r.bandMedian} style={{ left: `${pct(f.median)}%` }} />
        </div>
        <div className={r.bandScale}>
          <span className="num">{num(f.p10, 2)}</span>
          <span className={r.bandScaleMid}>
            p10 to p90 · {f.unit}
          </span>
          <span className="num">{num(f.p90, 2)}</span>
        </div>
      </div>

      {!f.in_envelope && (
        <p className={r.envelope}>
          <Icon name="critical" size={14} />
          Outside the model&apos;s validated envelope.
          {f.envelope_note ? ` ${f.envelope_note}` : " Treat the range as a floor, not a bound."}
        </p>
      )}

      <p className={r.forecastFoot}>
        Produced {stamp(f.produced_at)} · grounded in{" "}
        {f.evidence_ids.length > 0 ? (
          <span className="num">{f.evidence_ids.length}</span>
        ) : (
          "no"
        )}{" "}
        evidence record{f.evidence_ids.length === 1 ? "" : "s"}
      </p>
    </article>
  );
}

export default function IncidentRoom() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";

  const {
    data: detail,
    loading,
    error,
    correlationId,
    reload,
  } = useApi<IncidentDetail>(id ? `/v1/incidents/${id}` : null);
  const { data: plans } = useApi<Plan[]>(id ? `/v1/incidents/${id}/plans` : null);
  const { data: decisions } = useApi<PolicyDecision[]>("/v1/policies/decisions?limit=100");

  const [rawOpen, setRawOpen] = useState(false);

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.04 }),
    [!!detail],
  );

  const evidenceById = useMemo(() => {
    const m = new Map<string, Evidence>();
    (detail?.evidence ?? []).forEach((e) => m.set(e.id, e));
    return m;
  }, [detail]);

  /** Specialist agents are not a fixed list: they are whoever authored a claim. */
  const agents = useMemo(() => {
    const by = new Map<string, Claim[]>();
    (detail?.claims ?? [])
      .filter((c) => c.author_kind !== "human")
      .forEach((c) => by.set(c.author, [...(by.get(c.author) ?? []), c]));
    return [...by.entries()];
  }, [detail]);

  const markers = useMemo(() => {
    const c = (detail?.incident.geometry as { coordinates?: [number, number] } | null)
      ?.coordinates;
    if (!c || !detail) return [];
    return [
      {
        id: detail.incident.id,
        label: detail.incident.title,
        coordinates: c,
        detail: `${detail.incident.severity} · ${detail.incident.state.replace(/_/g, " ")}`,
      },
    ];
  }, [detail]);

  const relatedDecisions = useMemo(() => {
    if (!decisions || !plans) return [];
    const actionIds = new Set(plans.flatMap((p) => p.actions.map((a) => a.id)));
    return decisions.filter(
      (d) => d.subject_action_id && actionIds.has(d.subject_action_id),
    );
  }, [decisions, plans]);

  if (loading) {
    return (
      <section className="container section">
        <Skeleton lines={14} />
      </section>
    );
  }

  if (error || !detail) {
    return (
      <section className="container section" style={{ display: "grid", gap: 20 }}>
        <Link className={r.back} href="/command">
          <Icon name="arrowLeft" size={14} />
          Command Center
        </Link>
        <ErrorState
          error={error ?? new Error("The incident record could not be read.")}
          onRetry={reload}
          correlationId={correlationId}
          what={`incident ${id}`}
        />
        <p className={r.honesty}>
          Nothing is shown in place of this record. An incident room with invented
          evidence would be worse than no incident room.
        </p>
      </section>
    );
  }

  const { incident, evidence, claims, conflicts, forecasts, unknowns, assets, degraded } =
    detail;

  const layers: Layer[] = [];
  const openedAge = ageSeconds(incident.opened_at);

  return (
    <section className="container section" ref={ref}>
      {/* ------------------------------------------------------------ head */}
      <div className={`${r.head} js-reveal`}>
        <Link className={r.back} href="/command">
          <Icon name="arrowLeft" size={14} />
          Command Center
        </Link>
        <h1 className={r.title}>{incident.title}</h1>
        <div className={r.headMeta}>
          <span className={s.badge} data-severity={incident.severity}>
            <Icon
              name={incident.severity === "critical" ? "critical" : "major"}
              size={13}
            />
            {incident.severity}
          </span>
          <span className={s.badge}>{incident.state.replace(/_/g, " ")}</span>
          <span className={r.metaItem}>
            Opened {stamp(incident.opened_at)}
            {openedAge !== null && <> · running {duration(openedAge)}</>}
          </span>
          <span className={r.metaItem}>Detector {incident.detector}</span>
          <span className={r.metaItem}>
            <code>{incident.id}</code>
          </span>
        </div>
      </div>

      {degraded && (
        <p className={`${r.degraded} js-reveal`} role="status">
          <Icon name="offline" size={16} />
          <span>
            <strong>Degraded assessment.</strong> The language model path was
            unavailable for this incident, so the analysis below is the deterministic
            synthesis only. Evidence, policy and audit are unaffected.
          </span>
        </p>
      )}

      {/* --------------------------------------------------- 1. the summary */}
      <div className={`${r.split} js-reveal`}>
        <div className={r.main}>
          {CLASS_ORDER.map((klass) => {
            const group = claims.filter((c) => c.claim_class === klass);
            if (klass === "forecast" && group.length === 0 && forecasts.length === 0)
              return null;
            if (klass !== "forecast" && group.length === 0) return null;
            return (
              <section key={klass} className={r.block}>
                <header className={r.blockHead}>
                  <h2 className={r.blockTitle}>{CLASS_COPY[klass].title}</h2>
                  <p className={r.blockBlurb}>{CLASS_COPY[klass].blurb}</p>
                </header>

                {klass === "forecast" && forecasts.length > 0 && (
                  <div className={r.forecastGrid}>
                    {forecasts.map((f) => (
                      <ForecastBand key={f.id} f={f} />
                    ))}
                  </div>
                )}

                <div className={r.claimList}>
                  {group.map((c) => (
                    <ClaimBlock
                      key={c.id}
                      claim={c}
                      evidence={c.evidence_ids
                        .map((eid) => evidenceById.get(eid))
                        .filter((e): e is Evidence => !!e)}
                    />
                  ))}
                </div>
              </section>
            );
          })}

          {claims.length === 0 && forecasts.length === 0 && (
            <EmptyState
              icon="fact"
              title="No assessment on the record yet"
              body="No agent has produced a grounded claim for this incident. Rather than summarise the evidence for you, this space stays empty until one does. The evidence itself is below."
            />
          )}

          {/* ------------------------------------------- 2. explicit unknowns */}
          <section className={r.block}>
            <header className={r.blockHead}>
              <h2 className={r.blockTitle}>What is not known</h2>
              <p className={r.blockBlurb}>
                Stated before the trace, because a gap in the record is a finding and
                not an omission.
              </p>
            </header>
            {unknowns.length > 0 ? (
              <ul className={r.unknowns}>
                {unknowns.map((u, i) => (
                  <li key={i} className={r.unknown}>
                    <Icon name="info" size={15} />
                    <span>{u}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={r.blockBlurb}>
                No open unknowns were recorded against this incident. That is a
                statement about the record, not a guarantee about the city.
              </p>
            )}
          </section>

          {/* ------------------------------------------------ 3a. conflicts */}
          {conflicts.length > 0 && (
            <section className={r.block}>
              <header className={r.blockHead}>
                <h2 className={r.blockTitle}>
                  Sources disagree <span className="num">({conflicts.length})</span>
                </h2>
                <p className={r.blockBlurb}>
                  Both readings are shown and both are named. Auralis does not silently
                  pick a winner.
                </p>
              </header>
              <div className={r.conflictList}>
                {conflicts.map((cf) => (
                  <article key={cf.id} className={r.conflict}>
                    <header className={r.conflictHead}>
                      <span className={r.conflictMark}>
                        <Icon name="critical" size={13} />
                        Conflict
                      </span>
                      <strong>{cf.subject}</strong>
                      <span className={s.tag}>{cf.resolution}</span>
                    </header>
                    <div className={r.conflictSides}>
                      {[cf.evidence_a, cf.evidence_b].map((side, i) => (
                        <div key={side.id} className={r.conflictSide}>
                          <span className="label">Source {i === 0 ? "A" : "B"}</span>
                          <strong>{side.source}</strong>
                          <div className={r.conflictSideMeta}>
                            <span className={s.tag}>{side.trust_tier}</span>
                            <StaleBadge ageS={side.age_s} fresh={side.fresh} compact />
                          </div>
                          <EvidenceChip evidence={side} compact />
                          {cf.winner_evidence_id === side.id && (
                            <span className={r.conflictWinner}>
                              Precedence applied by {cf.resolved_by_rule ?? "rule"}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                    {cf.impact && (
                      <p className={r.conflictImpact}>
                        <strong>Effect on dependent plans.</strong> {cf.impact}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            </section>
          )}

          {/* ------------------------------------------- 3b. specialist agents */}
          {agents.length > 0 && (
            <section className={r.block}>
              <header className={r.blockHead}>
                <h2 className={r.blockTitle}>Specialist agents</h2>
                <p className={r.blockBlurb}>
                  Who authored what. An agent&apos;s output is a claim on the record, not
                  a conclusion of the system.
                </p>
              </header>
              <div className={r.agentGrid}>
                {agents.map(([author, list]) => {
                  const grounded = list.filter((c) => c.evidence_ids.length > 0).length;
                  return (
                    <article key={author} className={r.agent}>
                      <header className={r.agentHead}>
                        <span className={r.agentAvatar} aria-hidden="true">
                          <Icon name="trace" size={16} />
                        </span>
                        <div>
                          <strong className={r.agentName}>{author}</strong>
                          <span className={r.agentKind}>{list[0].author_kind}</span>
                        </div>
                      </header>
                      <dl className={r.agentStats}>
                        <div>
                          <dt>Claims</dt>
                          <dd className="num">{list.length}</dd>
                        </div>
                        <div>
                          <dt>Grounded</dt>
                          <dd className="num">
                            {grounded}/{list.length}
                          </dd>
                        </div>
                      </dl>
                      {list[0].confidence_basis ? (
                        <p className={r.agentBasis}>{list[0].confidence_basis}</p>
                      ) : (
                        <p className={r.agentBasis}>
                          <NoData reason="unverified" />
                        </p>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          )}

          {/* ------------------------------------------------- 4. raw evidence */}
          <section className={r.block}>
            <header className={r.blockHead}>
              <h2 className={r.blockTitle}>
                Evidence on the record <span className="num">({evidence.length})</span>
              </h2>
              <p className={r.blockBlurb}>
                Ordered by observation time, newest first. Every claim above resolves
                into these rows and nothing else.
              </p>
            </header>

            {evidence.length === 0 ? (
              <EmptyState
                inline
                icon="offline"
                title="No evidence records"
                body="This incident carries no evidence. No fact or forecast can be made from it, and none is shown."
              />
            ) : (
              <>
                <ol className={r.timeline}>
                  {[...evidence]
                    .sort((a, b) => b.observed_at.localeCompare(a.observed_at))
                    .map((e) => (
                      <li key={e.id} className={r.tlItem}>
                        <span className={r.tlTime}>
                          <span className="num">{stamp(e.observed_at)}</span>
                        </span>
                        <span
                          className={r.tlDot}
                          data-fresh={e.fresh}
                          data-synthetic={e.evidence_class.startsWith("synthetic")}
                          aria-hidden="true"
                        />
                        <div className={r.tlBody}>
                          <p className={r.tlStatement}>{e.statement}</p>
                          <div className={r.tlMeta}>
                            <EvidenceChip evidence={e} />
                            <StaleBadge ageS={e.age_s} fresh={e.fresh} compact />
                            <span className={s.tag}>{e.evidence_class}</span>
                          </div>
                        </div>
                      </li>
                    ))}
                </ol>

                <button
                  type="button"
                  className={r.disclosure}
                  aria-expanded={rawOpen}
                  onClick={() => setRawOpen((v) => !v)}
                >
                  <Icon name={rawOpen ? "chevronDown" : "chevronRight"} size={15} />
                  {rawOpen ? "Hide" : "Show"} raw evidence values and integrity hashes
                </button>

                {rawOpen && (
                  <div className={`scrollX ${r.rawWrap}`}>
                    <table className={s.table}>
                      <thead>
                        <tr>
                          <th scope="col">Evidence</th>
                          <th scope="col">Connector</th>
                          <th scope="col">Value</th>
                          <th scope="col">Expires</th>
                          <th scope="col">Integrity hash</th>
                          <th scope="col">Derived from</th>
                        </tr>
                      </thead>
                      <tbody>
                        {evidence.map((e) => (
                          <tr key={e.id}>
                            <th scope="row">
                              <code>{e.id}</code>
                            </th>
                            <td>{e.connector_id}</td>
                            <td>
                              <code className={r.rawValue}>
                                {JSON.stringify(e.value)}
                              </code>
                            </td>
                            <td>{stamp(e.expires_at)}</td>
                            <td>
                              <code className={r.rawHash}>{e.integrity_hash}</code>
                            </td>
                            <td>
                              {e.prov_derived_from.length > 0 ? (
                                e.prov_derived_from.join(", ")
                              ) : (
                                <span className={r.rawDirect}>Direct observation</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </section>
        </div>

        {/* ------------------------------------------------------------ rail */}
        <aside className={r.rail} aria-label="Incident context">
          <div className={r.railCard}>
            <h3 className={r.railTitle}>Where</h3>
            {markers.length > 0 ? (
              <CityMap
                layers={layers}
                markers={markers}
                center={markers[0].coordinates}
                zoom={13.5}
                height="240px"
                interactive={false}
                summary={`Single incident marker for ${incident.title}`}
              />
            ) : (
              <NoData reason="unverified" />
            )}
          </div>

          <div className={r.railCard}>
            <h3 className={r.railTitle}>Affected assets</h3>
            {assets.length > 0 ? (
              <ul className={r.assetList}>
                {assets.map((a: Record<string, unknown>) => (
                  <li key={String(a.id)} className={r.asset}>
                    <strong>{String(a.name ?? a.id)}</strong>
                    <span className={r.assetKind}>{String(a.kind ?? "asset")}</span>
                    {a.criticality !== undefined && (
                      <span className={r.assetCrit}>
                        criticality <span className="num">{String(a.criticality)}</span>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <NoData reason="unverified" />
            )}
          </div>

          <div className={r.railCard}>
            <h3 className={r.railTitle}>Candidate next steps</h3>
            {plans && plans.length > 0 ? (
              <ul className={r.planList}>
                {plans.map((p) => {
                  const topTier = p.actions.reduce(
                    (acc, a) => (a.risk_tier > acc ? a.risk_tier : acc),
                    "R0" as Plan["actions"][number]["risk_tier"],
                  );
                  return (
                    <li key={p.id}>
                      <Link href={`/plans/${p.id}`} className={r.planLink}>
                        <span className={r.planTitle}>{p.title}</span>
                        <span className={r.planMeta}>
                          <span className={s.tag}>{p.status}</span>
                          <RiskBadge tier={topTier} compact />
                          <span className="num">{p.actions.length}</span> action
                          {p.actions.length === 1 ? "" : "s"}
                        </span>
                        <span className={r.planNote}>
                          Proposed, not authorised. Nothing here has been executed.
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <EmptyState
                inline
                icon="action"
                title="No candidate plans"
                body="No plan has been generated for this incident yet. Nothing is proposed and nothing is queued."
              />
            )}
          </div>

          <div className={r.railCard}>
            <h3 className={r.railTitle}>Policy state</h3>
            {relatedDecisions.length > 0 ? (
              <ul className={r.policyList}>
                {relatedDecisions.map((d) => (
                  <li key={d.id} className={r.policy} data-effect={d.effect}>
                    <span className={r.policyEffect}>
                      <Icon
                        name={
                          d.effect === "allow"
                            ? "check"
                            : d.effect === "deny"
                              ? "critical"
                              : "lock"
                        }
                        size={13}
                      />
                      {d.effect.replace(/_/g, " ")}
                    </span>
                    <code className={r.policyRule}>{d.rule_id}</code>
                    <p className={r.policyReason}>{d.reason}</p>
                    <span className={r.policyFoot}>
                      bundle {d.bundle_version} · inputs {d.inputs_hash}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={r.blockBlurb}>
                No policy decision has been recorded against an action in this incident.
              </p>
            )}
            <Link className={r.railLink} href="/trace">
              Open the full trace
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
        </aside>
      </div>
    </section>
  );
}
