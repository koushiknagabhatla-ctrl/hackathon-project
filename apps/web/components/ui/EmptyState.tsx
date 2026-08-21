/**
 * EmptyState — nothing here, and why. Every empty state says what would put
 * something here, so it is never a dead end.
 *
 *   <EmptyState title="No open incidents" body="The city is quiet." icon="check" />
 *   <EmptyState title="No plans yet" body="..." action={{ label: "Generate plan", onClick: gen }} />
 */

import Link from "next/link";
import { Icon, type IconName } from "./Icon";
import { cx, stamp } from "@/lib/format";
import s from "./ui.module.css";

export interface NoDataProps {
  /** Why the value is absent. Defaults to "not verified". */
  reason?: "unverified" | "unavailable" | "stale" | "never";
  /** Last time this value WAS verified, if it ever was. */
  lastVerifiedAt?: string | null;
  className?: string;
}

const NO_DATA_COPY: Record<NonNullable<NoDataProps["reason"]>, string> = {
  unverified: "No verified data",
  unavailable: "Source unavailable",
  stale: "Stale, not current",
  never: "Never reported",
};

/**
 * NoData — the correct rendering of an absent value, anywhere one would sit.
 *
 * A missing reading is NEVER a zero, a dash or a plausible number. This reads
 * as a deliberate statement so it can never be mistaken for a measurement, and
 * carries the last verified time when one exists.
 *
 *   <NoData />
 *   <NoData reason="unavailable" lastVerifiedAt={conn.last_seen_at} />
 */
export function NoData({ reason = "unverified", lastVerifiedAt, className }: NoDataProps) {
  const label = NO_DATA_COPY[reason];
  return (
    <span className={cx(s.nodata, className)} role="note">
      <Icon name={reason === "stale" ? "clock" : "offline"} size={12} />
      {label}
      {lastVerifiedAt && (
        <span className={s.nodataSince}>· last verified {stamp(lastVerifiedAt)}</span>
      )}
      <span className="sr-only">
        {label}.
        {lastVerifiedAt
          ? ` The last verified value was recorded at ${stamp(lastVerifiedAt)}.`
          : " This value has never been verified from a configured source."}
      </span>
    </span>
  );
}

export interface EmptyStateProps {
  title: string;
  body?: string;
  icon?: IconName;
  action?: { label: string; onClick?: () => void; href?: string };
  /** Dashed, transparent variant for inline slots inside an existing card. */
  inline?: boolean;
  className?: string;
}

export function EmptyState({
  title,
  body,
  icon = "layers",
  action,
  inline,
  className,
}: EmptyStateProps) {
  return (
    <div className={cx(s.state, inline && s.stateDashed, className)}>
      <span className={s.stateIcon} aria-hidden="true">
        <Icon name={icon} size={20} />
      </span>
      <h3 className={s.stateTitle}>{title}</h3>
      {body && <p className={s.stateBody}>{body}</p>}
      {action &&
        (action.href ? (
          <Link className="btn" href={action.href}>
            {action.label}
          </Link>
        ) : (
          <button type="button" className="btn" onClick={action.onClick}>
            {action.label}
          </button>
        ))}
    </div>
  );
}

export default EmptyState;
