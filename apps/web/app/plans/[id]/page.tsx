"use client";

/**
 * Plan Review — /plans/[id]
 *
 * The authority moment. Approving here is the only way a model-authored
 * proposal becomes a real effect on a real city, so the screen is built to
 * slow a person down rather than speed them up. Before any control is
 * reachable it states, for the specific action being authorised:
 *
 *   what happens         the tool, the target, the arguments, verbatim
 *   blast radius         how many premises sit downstream of it
 *   rollback             the compensating tool, or the fact there isn't one
 *   verification         how the system will prove the effect happened
 *   approver identity    who is signing, by principal id
 *   expiry               when the evidence under it stops being current
 *
 * Nothing on this page is styled to look settled. A plan is a proposal until
 * a named human says otherwise, and a policy denial is data shown in place,
 * never an error swallowed by a toast.
 */

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, getPrincipal, useApi, ApiError } from "@/lib/api";
import { useGsap, sectionReveal } from "@/lib/motion";
import {
  ApprovalControl,
  ErrorState,
  EmptyState,
  EvidenceChip,
  Icon,
  NoData,
  RiskBadge,
  Skeleton,
  useToast,
} from "@/components/ui";
import { stamp, duration, ageSeconds, num } from "@/lib/format";
import type { Action, Evidence, IncidentDetail, Plan, Incident } from "@/lib/types";
import s from "../../pages.module.css";
import p from "./plan.module.css";

type Provenance = "direct" | "reconstructed";

interface PlanState {
  plan: Plan | null;
  provenance: Provenance | null;
  error: ApiError | Error | null;
  loading: boolean;
  nonce: number;
}

/**
 * Read one plan.
 *
 * `/v1/plans/{id}` is the contract path. When that path is unavailable the
 * plan is re-read from the incident plan lists instead, and the page SAYS SO
 * rather than presenting a second-hand record as the authoritative one.
 */
function usePlan(id: string) {
  const [st, setSt] = useState<PlanState>({
    plan: null,
    provenance: null,
    error: null,
    loading: true,
    nonce: 0,
  });

  const reload = () => setSt((v) => ({ ...v, nonce: v.nonce + 1 }));

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setSt((v) => ({ ...v, loading: true }));

    (async () => {
      try {
        const direct = await api.get<Plan>(`/v1/plans/${id}`);
        if (!alive) return;
        setSt((v) => ({
          ...v,
          plan: direct,
          provenance: "direct",
          error: null,
          loading: false,
        }));
        return;
      } catch (primary) {
        try {
          const incidents = await api.get<Incident[]>("/v1/incidents");
          const lists = await Promise.all(
            incidents.map((i) =>
              api
                .get<Plan[]>(`/v1/incidents/${i.id}/plans`)
                .catch(() => [] as Plan[]),
            ),
          );
          const found = lists.flat().find((pl) => pl.id === id) ?? null;
          if (!alive) return;
          setSt((v) => ({
            ...v,
            plan: found,
            provenance: found ? "reconstructed" : null,
            error: found
              ? null
              : primary instanceof Error
                ? primary
                : new Error(String(primary)),
            loading: false,
          }));
        } catch (secondary) {
          if (!alive) return;
          setSt((v) => ({
            ...v,
            plan: null,
            provenance: null,
            error:
              secondary instanceof Error ? secondary : new Error(String(secondary)),
            loading: false,
          }));
        }
      }
    })();

    return () => {
      alive = false;
    };
  }, [id, st.nonce]);

  return { ...st, reload };
}

function ArgsTable({ args }: { args: Record<string, unknown> }) {
  const rows = Object.entries(args);
  if (rows.length === 0) {
    return (
      <p className={p.argsEmpty}>
        This tool is invoked with no arguments. The target alone determines the
        effect.
      </p>
    );
  }
  return (
    <dl className={p.args}>
      {rows.map(([k, v]) => (
        <div key={k} className={p.argRow}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd>
            <code>{typeof v === "string" ? v : JSON.stringify(v)}</code>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** One action, expanded into everything a person needs before signing. */
function ActionDossier({
  action,
  planId,
  evidence,
  expiresAt,
  approver,
  onDecided,
}: {
  action: Action;
  planId: string;
  evidence: Evidence[];
  expiresAt: string | null;
  approver: string;
  onDecided: () => void;
}) {
  const toast = useToast();
  const [denial, setDenial] = useState<ApiError | null>(null);
  const decision = action.policy_decision;
  const expiryAge = expiresAt ? ageSeconds(expiresAt) : null;
  const expired = expiryAge !== null && expiryAge > 0;

  return (
    <article className={p.dossier} data-risk={action.risk_tier}>
      <header className={p.dossierHead}>
        <span className={p.seq}>
          <span className="num">{action.sequence}</span>
        </span>
        <div className={p.dossierTitle}>
          <h3 className={p.toolId}>{action.tool_id}</h3>
          <span className={p.toolTarget}>
            {action.target_asset_id ? (
              <>
                targets <code>{action.target_asset_id}</code>
              </>
            ) : (
              "no asset target on the record"
            )}
          </span>
        </div>
        <RiskBadge
          tier={action.risk_tier}
          reason={`blast radius ${action.blast_radius}`}
        />
      </header>

      {/* ---------------------------------------------- what actually happens */}
      <section className={p.fact}>
        <h4 className={p.factTitle}>What happens if you approve</h4>
        <ArgsTable args={action.args as Record<string, unknown>} />
      </section>

      <div className={p.consequence}>
        <div className={p.consequenceCell}>
          <span className="label">Blast radius</span>
          {action.blast_radius > 0 ? (
            <>
              <strong className={p.big}>{num(action.blast_radius)}</strong>
              <span className={p.consequenceFoot}>
                dependent premises or assets downstream
              </span>
            </>
          ) : (
            <NoData reason="unverified" />
          )}
        </div>

        <div className={p.consequenceCell}>
          <span className="label">Reversible</span>
          <strong className={p.word}>
            <Icon name={action.reversible ? "check" : "critical"} size={15} />
            {action.reversible ? "Yes" : "No"}
          </strong>
          <span className={p.consequenceFoot}>
            {action.rollback_tool_id ? (
              <>
                rollback via <code>{action.rollback_tool_id}</code>
              </>
            ) : action.reversible ? (
              "no compensating tool is registered for this action"
            ) : (
              "this effect cannot be undone by the system"
            )}
          </span>
        </div>

        <div className={p.consequenceCell}>
          <span className="label">Verification</span>
          {action.verification_method ? (
            <>
              <strong className={p.word}>
                <Icon name="shield" size={15} />
                {action.verification_method}
              </strong>
              <span className={p.consequenceFoot}>
                the action reaches verified only after this read-back matches
              </span>
            </>
          ) : (
            <>
              <NoData reason="unverified" />
              <span className={p.consequenceFoot}>
                no verification method is declared. The outcome will close as
                unknown, never as success.
              </span>
            </>
          )}
        </div>

        <div className={p.consequenceCell}>
          <span className="label">Authority expires</span>
          {expiresAt ? (
            <>
              <strong className={p.word} data-expired={expired}>
                <Icon name="clock" size={15} />
                {stamp(expiresAt)}
              </strong>
              <span className={p.consequenceFoot}>
                {expired
                  ? `The evidence under this plan lapsed ${duration(expiryAge)} ago. Re-assess before approving.`
                  : "when the evidence under this plan stops being current"}
              </span>
            </>
          ) : (
            <>
              <NoData reason="unverified" />
              <span className={p.consequenceFoot}>
                no expiry could be computed from the evidence on this plan
              </span>
            </>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------ the evidence */}
      <section className={p.fact}>
        <h4 className={p.factTitle}>Evidence this rests on</h4>
        {evidence.length > 0 ? (
          <div className={s.chipRow}>
            {evidence.map((e) => (
              <EvidenceChip key={e.id} evidence={e} />
            ))}
          </div>
        ) : (
          <p className={p.argsEmpty}>
            No evidence record reached this screen for this plan. Do not approve on
            the strength of the summary alone.
          </p>
        )}
      </section>

      {/* --------------------------------------------------------- the policy */}
      {decision && (
        <section className={p.policy} data-effect={decision.effect}>
          <span className={p.policyEffect}>
            <Icon
              name={
                decision.effect === "allow"
                  ? "check"
                  : decision.effect === "deny"
                    ? "lock"
                    : "shield"
              }
              size={14}
            />
            Policy {decision.effect.replace(/_/g, " ")}
          </span>
          <code className={p.policyRule}>{decision.rule_id}</code>
          <p className={p.policyReason}>{decision.reason}</p>
          <span className={p.policyFoot}>
            bundle {decision.bundle_version} · inputs {decision.inputs_hash} · decided{" "}
            {stamp(decision.decided_at)}
          </span>
        </section>
      )}

      {!decision && (
        <p className={p.noPolicy}>
          <Icon name="info" size={14} />
          No policy decision has been recorded against this action yet. The gate
          runs at execution regardless of what is shown here.
        </p>
      )}

      {/* --------------------------------------------------- the signing act */}
      <div className={p.signing}>
        <p className={p.approver}>
          <Icon name="user" size={14} />
          Signing as <strong>{approver}</strong>. Your principal id, the rationale
          and the exact inputs hash are written to the append-only ledger.
        </p>

        <ApprovalControl
          action={action}
          note={
            action.risk_tier === "R4" || action.risk_tier === "R5"
              ? "This tier requires a named approver. A confirmation is not an authorisation and will not satisfy this gate."
              : undefined
          }
          onDecision={async ({ decision: d, rationale }) => {
            setDenial(null);
            try {
              await api.post(`/v1/plans/${planId}/approve`, {
                action_id: action.id,
                decision: d,
                rationale,
              });
              toast.push({
                tone: d === "approved" ? "ok" : "info",
                title: d === "approved" ? "Approval recorded" : "Denial recorded",
                body: `${action.tool_id} · ${action.id}. The decision is in the audit ledger.`,
              });
              onDecided();
            } catch (e) {
              if (e instanceof ApiError && e.code === "policy_denied") {
                setDenial(e);
                return;
              }
              throw e;
            }
          }}
        />

        {denial && (
          <div className={p.denied} role="alert">
            <span className={p.deniedMark}>
              <Icon name="lock" size={14} />
              Refused by policy
            </span>
            <code className={p.policyRule}>{denial.ruleId ?? denial.code}</code>
            <p className={p.policyReason}>{denial.reason ?? denial.message}</p>
            <span className={p.policyFoot}>
              correlation {denial.correlationId ?? "not returned"}
            </span>
          </div>
        )}
      </div>
    </article>
  );
}

export default function PlanReview() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const { plan, provenance, error, loading, reload } = usePlan(id);
  const approver = typeof window === "undefined" ? "" : getPrincipal();

  const { data: incidentDetail } = useApi<IncidentDetail>(
    plan ? `/v1/incidents/${plan.incident_id}` : null,
  );

  const ref = useGsap<HTMLElement>(
    (_, el) => sectionReveal(el, ".js-reveal", { stagger: 0.05 }),
    [!!plan],
  );

  const evidenceById = useMemo(() => {
    const m = new Map<string, Evidence>();
    (incidentDetail?.evidence ?? []).forEach((e) => m.set(e.id, e));
    return m;
  }, [incidentDetail]);

  const planEvidence = useMemo(
    () =>
      (plan?.evidence_ids ?? [])
        .map((eid) => evidenceById.get(eid))
        .filter((e): e is Evidence => !!e),
    [plan, evidenceById],
  );

  /** Authority expiry is the earliest expiry among the evidence under the plan. */
  const expiresAt = useMemo(() => {
    const stamps = planEvidence.map((e) => e.expires_at).filter(Boolean);
    return stamps.length ? stamps.sort()[0] : null;
  }, [planEvidence]);

  if (loading) {
    return (
      <section className="container section">
        <Skeleton lines={12} />
      </section>
    );
  }

  if (!plan) {
    return (
      <section className="container section" style={{ display: "grid", gap: 20 }}>
        <Link className={p.back} href="/command">
          <Icon name="arrowLeft" size={14} />
          Command Center
        </Link>
        <ErrorState
          error={error ?? new Error("The plan record could not be read.")}
          onRetry={reload}
          what={`plan ${id}`}
        />
      </section>
    );
  }

  const blocked = plan.actions.filter(
    (a) => a.policy_decision?.effect === "deny" || a.status === "blocked",
  );
  const awaiting = plan.actions.filter(
    (a) => a.status === "proposed" || a.status === "blocked",
  );
  const topTier = plan.actions.reduce(
    (acc, a) => (a.risk_tier > acc ? a.risk_tier : acc),
    "R0" as Action["risk_tier"],
  );
  const totalBlast = plan.actions.reduce((n, a) => n + a.blast_radius, 0);

  return (
    <section className="container section" ref={ref}>
      <div className={`${p.head} js-reveal`}>
        <Link className={p.back} href={`/incidents/${plan.incident_id}`}>
          <Icon name="arrowLeft" size={14} />
          Incident room
        </Link>
        <span className="eyebrow">Proposed course of action</span>
        <h1 className={p.title}>{plan.title}</h1>
        <p className={p.rationale}>{plan.rationale}</p>
        <div className={p.headMeta}>
          <span className={s.badge}>{plan.status}</span>
          <RiskBadge tier={topTier} reason={`highest tier across ${plan.actions.length} actions`} />
          <span className={p.metaItem}>
            Authored by {plan.created_by} · {stamp(plan.created_at)}
          </span>
          <span className={p.metaItem}>
            <code>{plan.id}</code>
          </span>
        </div>
      </div>

      {provenance === "reconstructed" && (
        <p className={`${p.provenance} js-reveal`} role="status">
          <Icon name="offline" size={16} />
          <span>
            <strong>Read from the incident plan list.</strong> The plan endpoint did
            not answer, so this record was re-read from the incident it belongs to.
            It is the same stored plan, read by a second route. Confirm against the
            audit ledger before authorising anything at R3 or above.
          </span>
        </p>
      )}

      {/* ------------------------------------------------------- the summary */}
      <div className={`${p.summary} js-reveal`}>
        <div className={p.summaryCell}>
          <span className="label">Actions</span>
          <strong className={p.big}>{num(plan.actions.length)}</strong>
        </div>
        <div className={p.summaryCell}>
          <span className="label">Awaiting a decision</span>
          <strong className={p.big}>{num(awaiting.length)}</strong>
        </div>
        <div className={p.summaryCell}>
          <span className="label">Blocked by policy</span>
          <strong className={p.big} data-alarm={blocked.length > 0}>
            {num(blocked.length)}
          </strong>
        </div>
        <div className={p.summaryCell}>
          <span className="label">Combined blast radius</span>
          {totalBlast > 0 ? (
            <strong className={p.big}>{num(totalBlast)}</strong>
          ) : (
            <NoData reason="unverified" />
          )}
        </div>
      </div>

      {/* ------------------------------------------ validation and objectives */}
      <div className={`${p.checks} js-reveal`}>
        <section className={p.check}>
          <h2 className={p.checkTitle}>Validation</h2>
          {Object.keys(plan.validation).length > 0 ? (
            <ul className={p.checkList}>
              {Object.entries(plan.validation).map(([k, v]) => {
                const pass = v === true || v === 0;
                const isBool = typeof v === "boolean";
                return (
                  <li key={k} className={p.checkRow} data-pass={pass}>
                    <Icon name={pass ? "check" : "critical"} size={14} />
                    <span>{k.replace(/_/g, " ")}</span>
                    <span className={p.checkValue}>
                      {isBool ? (v ? "pass" : "fail") : String(v)}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <NoData reason="unverified" />
          )}
        </section>

        <section className={p.check}>
          <h2 className={p.checkTitle}>Objective score</h2>
          <p className={p.checkNote}>
            The planner&apos;s own scoring. It is an argument for this plan, not
            evidence about the city.
          </p>
          {Object.keys(plan.objective_score).length > 0 ? (
            <dl className={p.scores}>
              {Object.entries(plan.objective_score).map(([k, v]) => (
                <div key={k}>
                  <dt>{k.replace(/_/g, " ")}</dt>
                  <dd className="num">{String(v)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <NoData reason="unverified" />
          )}
        </section>
      </div>

      {/* -------------------------------------------------------- the actions */}
      <h2 className={`${p.sectionHead} js-reveal`}>
        Each action, in full
        <span className={p.sectionHeadNote}>
          Executed in sequence. Every one is authorised on its own terms.
        </span>
      </h2>

      {plan.actions.length === 0 ? (
        <EmptyState
          icon="action"
          title="This plan proposes no actions"
          body="A plan with no actions cannot be approved and cannot have an effect. Nothing is queued."
        />
      ) : (
        <div className={p.dossiers}>
          {[...plan.actions]
            .sort((a, b) => a.sequence - b.sequence)
            .map((a) => (
              <div key={a.id} className="js-reveal">
                <ActionDossier
                  action={a}
                  planId={plan.id}
                  evidence={planEvidence}
                  expiresAt={expiresAt}
                  approver={approver}
                  onDecided={reload}
                />
              </div>
            ))}
        </div>
      )}
    </section>
  );
}
