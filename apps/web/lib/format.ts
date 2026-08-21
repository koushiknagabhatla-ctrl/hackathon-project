/**
 * Small shared formatters. Deliberately dumb, no i18n layer until asked.
 *
 * NOTHING here ever returns a dash, a zero or a plausible-looking number for
 * missing data. "No verified data" is the correct output and it says so, so a
 * gap can never be mistaken for a reading.
 */

/** The one string the whole app uses when a value was never verified. */
const NO_DATA = "No verified data";

/** "2m 22s" / "3h 04m" / "just now". Used for evidence age and incident age. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return NO_DATA;
  const s = Math.max(0, Math.round(seconds));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${String(m % 60).padStart(2, "0")}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export const formatAge = duration;

/** "14:32:07" in the viewer's locale, stable between server and client. */
export function clock(iso: string | null | undefined): string {
  if (!iso) return NO_DATA;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return NO_DATA;
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** "20 Aug, 14:32" */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return NO_DATA;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return NO_DATA;
  return `${d.toLocaleDateString([], { day: "2-digit", month: "short" })}, ${clock(iso)}`;
}

/** Seconds since an ISO timestamp, floored at 0. */
export function ageSeconds(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return null;
  return Math.max(0, Math.round((Date.now() - d) / 1000));
}

export function num(value: number, decimals = 0): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
