/**
 * StaleBadge — freshness, stated. Colour + word + icon, never colour alone.
 *
 * <StaleBadge ageS={ev.age_s} fresh={ev.fresh} slaS={connector.freshness_sla_s} />
 */

import { Icon } from "./Icon";
import { duration } from "@/lib/format";
import s from "./ui.module.css";
import { cx } from "@/lib/format";

export interface StaleBadgeProps {
  /** Age of the datum in seconds. */
  ageS: number | null | undefined;
  /** Server's verdict. If omitted it is derived from ageS vs slaS. */
  fresh?: boolean;
  /** Freshness SLA for the connector, used only when `fresh` is absent. */
  slaS?: number;
  /** Hide the age, show only the word. */
  compact?: boolean;
}

export function StaleBadge({ ageS, fresh, slaS = 300, compact }: StaleBadgeProps) {
  const isFresh = fresh ?? (ageS !== null && ageS !== undefined && ageS <= slaS);
  const word = isFresh ? "Fresh" : "Stale";
  return (
    <span
      className={cx(s.stale, isFresh && s.staleFresh)}
      title={`${word} — observed ${duration(ageS)} ago`}
    >
      <Icon name={isFresh ? "check" : "clock"} size={13} />
      {word}
      {!compact && (
        <span className={s.chipMeta} style={{ fontWeight: 500 }}>
          {duration(ageS)}
        </span>
      )}
      <span className="sr-only">
        {isFresh
          ? `Data is fresh, observed ${duration(ageS)} ago.`
          : `Data is stale, observed ${duration(ageS)} ago, beyond the freshness window.`}
      </span>
    </span>
  );
}

export default StaleBadge;
