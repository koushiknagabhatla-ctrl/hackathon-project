/**
 * RiskBadge — R0..R5 with the tier, the word, an icon and a 5-step bar.
 * Four carriers, so it survives greyscale, colour blindness and a screenshot.
 *
 *   <RiskBadge tier={action.risk_tier} />
 *   <RiskBadge tier="R4" reason="blast radius 1,240 premises" />
 */

import type { RiskTier } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { cx } from "@/lib/format";
import s from "./ui.module.css";

const META: Record<RiskTier, { label: string; steps: number; tone: string; icon: IconName }> = {
  R0: { label: "Read only", steps: 0, tone: "toneInfo", icon: "info" },
  R1: { label: "Low", steps: 1, tone: "toneInfo", icon: "info" },
  R2: { label: "Moderate", steps: 2, tone: "toneMinor", icon: "minor" },
  R3: { label: "Elevated", steps: 3, tone: "toneMajor", icon: "major" },
  R4: { label: "High", steps: 4, tone: "toneCritical", icon: "critical" },
  R5: { label: "Severe", steps: 5, tone: "toneCritical", icon: "critical" },
};

export interface RiskBadgeProps {
  tier: RiskTier;
  /** Short explanation of why this tier was computed. Rendered as a tooltip + SR text. */
  reason?: string;
  /** Hide the word, keep tier + steps. For very dense tables only. */
  compact?: boolean;
  className?: string;
}

export function RiskBadge({ tier, reason, compact, className }: RiskBadgeProps) {
  const m = META[tier] ?? META.R0;
  return (
    <span
      className={cx(s.risk, s[m.tone], className)}
      title={reason ? `${tier} ${m.label} — ${reason}` : `${tier} — ${m.label}`}
    >
      <Icon name={m.icon} size={14} />
      <span className={s.riskTier}>{tier}</span>
      {!compact && <span className={s.riskLabel}>{m.label}</span>}
      <span className={s.riskSteps} aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={s.riskStep} data-on={i < m.steps} />
        ))}
      </span>
      <span className="sr-only">
        Risk tier {tier}, {m.label}.{reason ? ` ${reason}.` : ""}
      </span>
    </span>
  );
}

export default RiskBadge;
