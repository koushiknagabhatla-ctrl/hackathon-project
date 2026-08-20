/**
 * IncidentCard — severity, lifecycle state and time in one scannable block.
 * Severity is an edge colour AND a word AND an icon. State is a 7-step track,
 * so progress reads without colour. Lifts 2px on hover, pointer devices only.
 *
 *   <IncidentCard incident={i} />                        // links to /incidents/:id
 *   <IncidentCard incident={i} onSelect={setSelected} /> // button instead
 *   <IncidentCard incident={i} evidence={refs} compact />
 */

import type { CSSProperties } from "react";
import Link from "next/link";
import type { EvidenceRef, Incident, IncidentState, Severity } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { EvidenceChip } from "./EvidenceChip";
import { cx, duration, ageSeconds, stamp } from "@/lib/format";
import s from "./ui.module.css";

const STATES: IncidentState[] = [
  "detected",
  "assessing",
  "planning",
  "awaiting_approval",
  "acting",
  "verifying",
  "closed",
];

export const INCIDENT_STATE_LABEL: Record<IncidentState, string> = {
  detected: "Detected",
  assessing: "Assessing",
  planning: "Planning",
  awaiting_approval: "Awaiting approval",
  acting: "Acting",
  verifying: "Verifying",
  closed: "Closed",
};

export const SEVERITY_META: Record<
  Severity,
  { label: string; icon: IconName; tone: string; color: string }
> = {
  critical: {
    label: "Critical",
    icon: "critical",
    tone: "toneCritical",
    color: "var(--sev-critical)",
  },
  major: { label: "Major", icon: "major", tone: "toneMajor", color: "var(--sev-major)" },
  minor: { label: "Minor", icon: "minor", tone: "toneMinor", color: "var(--sev-minor)" },
  info: { label: "Info", icon: "info", tone: "toneInfo", color: "var(--sev-info)" },
};

export interface IncidentCardProps {
  incident: Incident;
  /** Evidence chips shown under the meta row. Pass the refs you already hold. */
  evidence?: EvidenceRef[];
  /** Click handler. When absent the whole card links to /incidents/:id. */
  onSelect?: (id: string) => void;
  /** Override the link target. */
  href?: string;
  /** Drop the state track and evidence row for tight lists. */
  compact?: boolean;
  className?: string;
}

export function IncidentCard({
  incident,
  evidence = [],
  onSelect,
  href,
  compact,
  className,
}: IncidentCardProps) {
  const sev = SEVERITY_META[incident.severity] ?? SEVERITY_META.info;
  const idx = STATES.indexOf(incident.state);
  const age = ageSeconds(incident.opened_at);
  const style = { "--tone": sev.color } as CSSProperties;

  const body = (
    <>
      <div className={s.incidentHead}>
        <h3 className={s.incidentTitle}>{incident.title}</h3>
        <span className={cx(s.status, s[sev.tone])}>
          <Icon name={sev.icon} size={14} />
          <span className={s.statusText}>{sev.label}</span>
        </span>
      </div>

      <div className={s.incidentMeta}>
        <span className={s.statusText} style={{ color: "var(--text)" }}>
          {INCIDENT_STATE_LABEL[incident.state]}
        </span>
        <span aria-hidden="true">·</span>
        <span className={s.incidentTime} title={stamp(incident.opened_at)}>
          open {duration(age)}
        </span>
        <span aria-hidden="true">·</span>
        <span>{incident.incident_class}</span>
      </div>

      {!compact && (
        <div className={s.stateTrack} aria-hidden="true">
          {STATES.map((st, i) => (
            <span
              key={st}
              className={s.stateStep}
              data-done={i < idx}
              data-current={i === idx}
            />
          ))}
        </div>
      )}

      {!compact && evidence.length > 0 && (
        <div className={s.chipRow} style={{ marginTop: 14 }}>
          {evidence.slice(0, 3).map((e) => (
            <EvidenceChip key={e.id} evidence={e} compact readOnly />
          ))}
          {evidence.length > 3 && (
            <span className={s.chipMeta}>+{evidence.length - 3} more</span>
          )}
        </div>
      )}

      <span className="sr-only">
        {sev.label} incident, state {INCIDENT_STATE_LABEL[incident.state]}, opened{" "}
        {stamp(incident.opened_at)}, {evidence.length} evidence items, detector{" "}
        {incident.detector}.
      </span>
    </>
  );

  if (onSelect) {
    return (
      <button
        type="button"
        className={cx(s.incident, className)}
        style={{ ...style, textAlign: "left", width: "100%", cursor: "pointer" }}
        onClick={() => onSelect(incident.id)}
      >
        {body}
      </button>
    );
  }

  return (
    <Link
      className={cx(s.incident, className)}
      style={style}
      href={href ?? `/incidents/${incident.id}`}
    >
      {body}
    </Link>
  );
}

export default IncidentCard;
