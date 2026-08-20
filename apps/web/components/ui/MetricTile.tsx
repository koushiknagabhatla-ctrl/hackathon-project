"use client";

/**
 * MetricTile — one number, in the Auralis numeral face, with an honest delta.
 * The delta carries a word and an arrow, not just a colour, and states the
 * comparison window so the number is never context-free.
 *
 *   <MetricTile label="Time to detect" value={42} unit="s" delta={-12} deltaLabel="vs 24h" />
 *   <MetricTile label="LLM cost" value={0.42} unit="USD" decimals={2} foot="this incident" />
 *   <MetricTile label="Chain" value="verified" />        // strings pass straight through
 */

import { useEffect, useRef } from "react";
import { Icon } from "./Icon";
import { countTo, reducedMotion } from "@/lib/motion";
import { cx, num } from "@/lib/format";
import s from "./ui.module.css";

export interface MetricTileProps {
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  /** Signed change. Rendered with an arrow, a sign and `deltaLabel`. */
  delta?: number | null;
  deltaLabel?: string;
  /** Set when a falling number is the good outcome (latency, cost, errors). */
  lowerIsBetter?: boolean;
  decimals?: number;
  /** Small caption under the value. */
  foot?: string;
  /** Count the value up on mount. Off under prefers-reduced-motion. */
  animate?: boolean;
  className?: string;
}

export function MetricTile({
  label,
  value,
  unit,
  delta,
  deltaLabel,
  lowerIsBetter,
  decimals = 0,
  foot,
  animate,
  className,
}: MetricTileProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const numeric = typeof value === "number" ? value : null;

  useEffect(() => {
    if (!animate || numeric === null || reducedMotion()) return;
    countTo(ref.current, numeric, { decimals });
  }, [animate, numeric, decimals]);

  const display =
    value === null || value === undefined
      ? "—"
      : typeof value === "number"
        ? num(value, decimals)
        : value;

  const improving =
    delta === null || delta === undefined || delta === 0
      ? null
      : lowerIsBetter
        ? delta < 0
        : delta > 0;

  return (
    <div className={cx(s.metric, className)}>
      <span className={s.metricLabel}>{label}</span>
      <span className={s.metricValue}>
        <span ref={ref}>{display}</span>
        {unit && <span className={s.metricUnit}>{unit}</span>}
      </span>
      {delta !== null && delta !== undefined && (
        <span className={s.metricDelta}>
          <Icon
            name={improving === null ? "info" : improving ? "check" : "major"}
            size={13}
          />
          <span className={s.metricDeltaValue}>
            {delta > 0 ? "+" : ""}
            {num(delta, decimals)}
            {unit ? ` ${unit}` : ""}
          </span>
          <span>{deltaLabel ?? "change"}</span>
          <span className="sr-only">
            {improving === null
              ? "no change"
              : improving
                ? "improving"
                : "worsening"}
          </span>
        </span>
      )}
      {foot && <span className={s.metricFoot}>{foot}</span>}
    </div>
  );
}

export default MetricTile;
