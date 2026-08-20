"use client";

/**
 * EvidenceChip — the single way evidence is shown anywhere in Auralis.
 *
 * Shows source + observation age + freshness. Hovering underlines the source
 * and expands the trust tier. Clicking opens the trace for that evidence id.
 * Stale, conflicting, quarantined and synthetic evidence each get their own
 * word-level label — never a colour on its own.
 *
 *   <EvidenceChip evidence={ref} onOpenTrace={(id) => openDrawer(id)} />
 *   <EvidenceChip evidence={ref} />            // links to /trace?evidence=id
 *   <EvidenceChip evidence={ref} readOnly />   // no affordance, no click
 */

import Link from "next/link";
import type { EvidenceRef } from "@/lib/types";
import { duration, cx } from "@/lib/format";
import { Icon } from "./Icon";
import s from "./ui.module.css";

export interface EvidenceChipProps {
  evidence: EvidenceRef;
  /** Called with the evidence id. Omit to link to /trace?evidence=<id>. */
  onOpenTrace?: (id: string) => void;
  /** Render as plain text with no click target. */
  readOnly?: boolean;
  /** Drop the age to save horizontal room in dense rows. */
  compact?: boolean;
  className?: string;
}

const TRUST_LABEL: Record<EvidenceRef["trust_tier"], string> = {
  statutory: "Statutory",
  certified: "Certified",
  verified: "Verified",
  crowdsourced: "Crowdsourced",
  unknown: "Unverified",
};

function flagFor(e: EvidenceRef): { text: string; cls: string } | null {
  if (e.evidence_class === "synthetic" || e.evidence_class === "synthetic-corroboration")
    return { text: "Synthetic", cls: s.chipFlagSynthetic };
  if (e.status === "conflict" || e.status === "conflicted")
    return { text: "Conflict", cls: s.chipFlagConflict };
  if (e.status === "superseded") return { text: "Superseded", cls: s.chipFlagConflict };
  if (e.status === "quarantined") return { text: "Quarantined", cls: s.chipFlagConflict };
  if (e.status !== "valid") return { text: e.status, cls: s.chipFlagConflict };
  if (!e.fresh) return { text: "Stale", cls: s.chipFlagStale };
  return null;
}

export function EvidenceChip({
  evidence: e,
  onOpenTrace,
  readOnly,
  compact,
  className,
}: EvidenceChipProps) {
  const flag = flagFor(e);
  const trust = TRUST_LABEL[e.trust_tier] ?? "Unverified";
  const description =
    `Evidence ${e.id} from ${e.source}. Trust ${trust}. ` +
    `${e.evidence_class} observed ${duration(e.age_s)} ago. ` +
    `${e.fresh ? "Fresh." : "Stale."}${flag ? ` Flagged ${flag.text}.` : ""}`;

  const inner = (
    <>
      <span
        className={cx(s.chipDot, !e.fresh && s.chipDotStale)}
        aria-hidden="true"
      />
      <span className={s.chipSource}>{e.source}</span>
      <span className={s.chipExpand} aria-hidden="true">
        &nbsp;· {trust}
      </span>
      {!compact && <span className={s.chipMeta}>{duration(e.age_s)}</span>}
      {flag && (
        <span className={cx(s.chipFlag, flag.cls)} aria-hidden="true">
          {flag.text}
        </span>
      )}
      <span className="sr-only">{description}</span>
    </>
  );

  const cls = cx(s.chip, flag?.cls === s.chipFlagSynthetic && s.hatch, className);

  if (readOnly) {
    return (
      <span className={cls} data-static="true">
        {inner}
      </span>
    );
  }

  if (onOpenTrace) {
    return (
      <button type="button" className={cls} onClick={() => onOpenTrace(e.id)}>
        {inner}
      </button>
    );
  }

  return (
    <Link className={cls} href={`/trace?evidence=${encodeURIComponent(e.id)}`}>
      {inner}
    </Link>
  );
}

/** Row wrapper so a list of chips wraps consistently everywhere. */
export function EvidenceChipRow({ children }: { children: React.ReactNode }) {
  return <div className={s.chipRow}>{children}</div>;
}

export default EvidenceChip;
