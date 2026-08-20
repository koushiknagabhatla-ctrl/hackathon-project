"use client";

/**
 * StatusRail — the critical-incident strip. It sits under the navbar, never
 * inside it, so it can carry urgency without fighting the primary chrome for
 * attention. It only exists while a critical incident is open, and while it
 * exists the navbar stops compressing.
 *
 * It also publishes its own height as --rail-h so page content offsets cleanly.
 */

import Link from "next/link";
import { useEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { duration, ageSeconds } from "@/lib/format";
import { useShell } from "./ShellState";
import s from "./shell.module.css";

export function StatusRail() {
  const { criticalIncidents } = useShell();
  const ref = useRef<HTMLDivElement>(null);
  const top = criticalIncidents[0];

  useEffect(() => {
    const root = document.documentElement;
    const h = top ? `${ref.current?.offsetHeight ?? 44}px` : "0px";
    root.style.setProperty("--rail-h", h);
    return () => root.style.setProperty("--rail-h", "0px");
  }, [top]);

  if (!top) return null;

  return (
    <div className={s.rail} ref={ref} role="region" aria-label="Critical incident status">
      <div className={s.railInner}>
        <span className={s.railMark}>
          <Icon name="critical" size={13} />
          Critical
        </span>
        <span className={s.railTitle}>{top.title}</span>
        <span className={s.railMeta}>
          {top.state.replace("_", " ")} · open {duration(ageSeconds(top.opened_at))}
          {criticalIncidents.length > 1 && ` · +${criticalIncidents.length - 1} more`}
        </span>
        <Link className={s.railLink} href={`/incidents/${top.id}`}>
          Open incident
          <Icon name="arrowRight" size={14} />
        </Link>
        <span className="sr-only" role="status" aria-live="assertive">
          {criticalIncidents.length} critical incident
          {criticalIncidents.length > 1 ? "s" : ""} open. Most recent: {top.title}.
        </span>
      </div>
    </div>
  );
}

export default StatusRail;
