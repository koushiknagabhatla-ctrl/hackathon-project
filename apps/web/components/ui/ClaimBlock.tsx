/**
 * ClaimBlock — every AI-authored statement in Auralis renders through this.
 *
 * Fact, forecast and recommendation are visually separate: different accent
 * edge, different icon, an explicit uppercase label. Uncertainty is drawn as a
 * range on a track with both bounds in the numeral face — it is never a
 * footnote. A fact or forecast that arrives with no evidence renders as a loud
 * grounding violation rather than being quietly shown (invariant 1).
 *
 *   <ClaimBlock claim={c} evidence={refsFor(c)} onOpenTrace={openTrace} />
 *   <ClaimBlock claim={c} evidence={refs} point={forecast.median} />
 */

import type { CSSProperties } from "react";
import type { Claim, EvidenceRef } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { EvidenceChip } from "./EvidenceChip";
import { cx, num } from "@/lib/format";
import s from "./ui.module.css";

const KIND: Record<
  Claim["claim_class"],
  { label: string; icon: IconName; cls: string }
> = {
  fact: { label: "Fact", icon: "fact", cls: "claimFact" },
  forecast: { label: "Forecast", icon: "forecast", cls: "claimForecast" },
  recommendation: {
    label: "Recommendation",
    icon: "recommendation",
    cls: "claimRecommendation",
  },
};

export interface ClaimBlockProps {
  claim: Claim;
  /** The EvidenceRefs matching claim.evidence_ids. Pass whatever you hold. */
  evidence?: EvidenceRef[];
  /** Point estimate marked inside the range, e.g. a forecast median. */
  point?: number;
  onOpenTrace?: (evidenceId: string) => void;
  className?: string;
}

export function ClaimBlock({
  claim,
  evidence = [],
  point,
  onOpenTrace,
  className,
}: ClaimBlockProps) {
  const kind = KIND[claim.claim_class] ?? KIND.fact;
  const ungrounded =
    (claim.claim_class === "fact" || claim.claim_class === "forecast") &&
    claim.evidence_ids.length === 0;
  const u = claim.uncertainty;

  // The interval sits in the middle third of the track so both bounds stay
  // readable even when the interval itself is tiny.
  const span = u ? Math.max(u.upper - u.lower, 1e-9) : 0;
  const lo = u ? u.lower - span : 0;
  const hi = u ? u.upper + span : 1;
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100;

  const markStyle: CSSProperties =
    point === undefined
      ? {}
      : {
          position: "absolute",
          left: `calc(${pct(point)}% - 1px)`,
          top: 0,
          bottom: 0,
          width: 2,
          background: "var(--text)",
        };

  return (
    <article
      className={cx(
        s.claim,
        s[kind.cls],
        claim.status === "retracted" && s.claimRetracted,
        className,
      )}
      aria-label={`${kind.label}: ${claim.statement}`}
    >
      <header className={s.claimHead}>
        <span className={s.claimKind}>
          <Icon name={kind.icon} size={14} />
          {kind.label}
        </span>
        {claim.status !== "active" && (
          <span className={cx(s.chipFlag, s.chipFlagConflict)}>{claim.status}</span>
        )}
        {ungrounded && (
          <span className={cx(s.status, s.toneCritical)}>
            <Icon name="critical" size={13} />
            <span className={s.statusText}>Ungrounded — no evidence</span>
          </span>
        )}
      </header>

      <p className={s.claimStatement}>{claim.statement}</p>

      {u && (
        <div
          className={s.range}
          aria-label={`Uncertainty range ${u.lower} to ${u.upper} ${u.unit}`}
        >
          <div className={s.rangeHead}>
            <span>Uncertainty range</span>
            <span>{u.unit}</span>
          </div>
          <div className={s.rangeTrack}>
            <div
              className={s.rangeFill}
              style={{ left: `${pct(u.lower)}%`, right: `${100 - pct(u.upper)}%` }}
            />
            {point !== undefined && <div aria-hidden="true" style={markStyle} />}
          </div>
          <div className={s.rangeBounds}>
            <span>{num(u.lower, 2)}</span>
            {point !== undefined && <span>{num(point, 2)}</span>}
            <span>{num(u.upper, 2)}</span>
          </div>
        </div>
      )}

      {evidence.length > 0 && (
        <div className={s.chipRow}>
          {evidence.map((e) => (
            <EvidenceChip key={e.id} evidence={e} compact onOpenTrace={onOpenTrace} />
          ))}
        </div>
      )}

      <p className={s.claimAuthor}>
        {claim.author} · {claim.author_kind}
        {claim.confidence_basis ? ` · ${claim.confidence_basis}` : ""}
      </p>
    </article>
  );
}

export default ClaimBlock;
