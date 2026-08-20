/**
 * Skeleton — content-shaped placeholders. Never a row of generic grey bars:
 * each variant is the silhouette of the thing that is loading, so the layout
 * does not jump when the data lands.
 *
 *   <Skeleton variant="incident" count={3} />
 *   <Skeleton variant="metric" count={4} />
 *   <Skeleton variant="map" />
 *   <Skeleton variant="text" lines={3} />
 *
 * A skeleton is for a fetch in flight. If the fetch FAILED, replace it with
 * <ErrorState/> — never leave a skeleton spinning forever.
 */

import s from "./ui.module.css";
import { cx } from "@/lib/format";

export type SkeletonVariant =
  | "text"
  | "metric"
  | "incident"
  | "claim"
  | "chip"
  | "map"
  | "row";

export interface SkeletonProps {
  variant?: SkeletonVariant;
  /** How many silhouettes to render. */
  count?: number;
  /** Text lines, `variant="text"` only. */
  lines?: number;
  label?: string;
  className?: string;
}

const bar = (w: string, h = 12, key?: number) => (
  <span key={key} className={s.sk} style={{ width: w, height: h, display: "block" }} />
);

function One({ variant, lines }: { variant: SkeletonVariant; lines: number }) {
  switch (variant) {
    case "metric":
      return (
        <div className={s.skCard} style={{ minHeight: 118 }}>
          {bar("42%", 10)}
          {bar("58%", 34)}
          {bar("34%", 10)}
        </div>
      );
    case "incident":
      return (
        <div className={s.skCard}>
          <div className={s.skRow}>
            {bar("62%", 20)}
            <span style={{ marginLeft: "auto" }}>{bar("84px", 22)}</span>
          </div>
          {bar("40%", 10)}
          <div className={s.skRow} style={{ gap: 3 }}>
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <span
                key={i}
                className={s.sk}
                style={{ flex: 1, height: 4, borderRadius: 2 }}
              />
            ))}
          </div>
          <div className={s.skChips}>
            {bar("128px", 26)}
            {bar("104px", 26)}
          </div>
        </div>
      );
    case "claim":
      return (
        <div className={s.skCard} style={{ borderLeft: "4px solid var(--line)" }}>
          {bar("96px", 10)}
          {bar("100%", 14)}
          {bar("74%", 14)}
          <div className={s.skChips}>{bar("140px", 24)}</div>
        </div>
      );
    case "chip":
      return <span className={s.sk} style={{ width: 140, height: 28, borderRadius: 999 }} />;
    case "map":
      return (
        <div className={s.skMap}>
          <span
            className={s.sk}
            style={{ position: "absolute", inset: 0, borderRadius: 0 }}
          />
        </div>
      );
    case "row":
      return (
        <div className={s.skRow} style={{ padding: "12px 0" }}>
          {bar("18%", 12)}
          {bar("30%", 12)}
          {bar("14%", 12)}
          {bar("22%", 12)}
        </div>
      );
    default:
      return (
        <div style={{ display: "grid", gap: 8 }}>
          {Array.from({ length: lines }, (_, i) =>
            bar(i === lines - 1 ? "62%" : "100%", 12, i),
          )}
        </div>
      );
  }
}

export function Skeleton({
  variant = "text",
  count = 1,
  lines = 3,
  label = "Loading",
  className,
}: SkeletonProps) {
  return (
    <div
      className={cx(className)}
      style={{ display: "grid", gap: 16 }}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      {Array.from({ length: count }, (_, i) => (
        <One key={i} variant={variant} lines={lines} />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export default Skeleton;
