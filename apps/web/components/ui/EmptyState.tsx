/**
 * EmptyState — nothing here, and why. Every empty state says what would put
 * something here, so it is never a dead end.
 *
 *   <EmptyState title="No open incidents" body="The city is quiet." icon="check" />
 *   <EmptyState title="No plans yet" body="..." action={{ label: "Generate plan", onClick: gen }} />
 */

import Link from "next/link";
import { Icon, type IconName } from "./Icon";
import { cx } from "@/lib/format";
import s from "./ui.module.css";

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
