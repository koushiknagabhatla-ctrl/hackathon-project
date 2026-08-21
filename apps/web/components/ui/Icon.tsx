/**
 * Icon — the whole icon set, inline. No icon library, no runtime cost.
 *
 * Icons exist because severity / verification / permission may never be
 * colour-only. Every status component pairs colour + text + one of these.
 *
 * Usage: <Icon name="critical" size={16} />  (decorative by default)
 */

export type IconName =
  | "critical"
  | "major"
  | "minor"
  | "info"
  | "check"
  | "difference"
  | "failed"
  | "unknown"
  | "lock"
  | "shield"
  | "clock"
  | "source"
  | "synthetic"
  | "map"
  | "search"
  | "menu"
  | "close"
  | "chevronDown"
  | "chevronRight"
  | "arrowRight"
  | "arrowLeft"
  | "offline"
  | "queued"
  | "refresh"
  | "action"
  | "trace"
  | "activity"
  | "layers"
  | "user"
  | "external"
  | "fact"
  | "forecast"
  | "recommendation";

// 24x24, stroke, currentColor. Keep them geometric — this is an ops product.
const PATHS: Record<IconName, string> = {
  critical: "M12 3.5 2.5 20h19L12 3.5Z M12 10v4.2 M12 17.2h.01",
  major: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 7.6v5 M12 16.2h.01",
  minor: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 11v5.5 M12 7.8h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 11v5.5 M12 7.8h.01",
  check: "M20 6.5 9.4 17.1 4 11.7",
  difference: "M4 8h6l4 8h6 M4 16h6 M17 5l3 3-3 3 M17 13l3 3-3 3",
  failed: "M6 6l12 12 M18 6 6 18",
  unknown:
    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M9.4 9.4a2.6 2.6 0 1 1 3.5 2.4c-.6.3-.9.8-.9 1.5v.5 M12 17.2h.01",
  lock: "M6 10.5h12v9.5H6v-9.5Z M8.6 10.5V7.8a3.4 3.4 0 0 1 6.8 0v2.7 M12 14.3v2.4",
  shield: "M12 3 4.5 6.2v5.4c0 4.4 3 8.1 7.5 9.4 4.5-1.3 7.5-5 7.5-9.4V6.2L12 3Z M8.8 12.2l2.3 2.3 4.1-4.1",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 7.2V12l3.2 2",
  source: "M4.5 6.5c0-1.6 3.4-2.8 7.5-2.8s7.5 1.2 7.5 2.8-3.4 2.8-7.5 2.8-7.5-1.2-7.5-2.8Z M4.5 6.5v11c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8v-11 M4.5 12c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8",
  synthetic: "M9.5 3.5h5 M10.5 3.5v5.2L5.4 18a2.2 2.2 0 0 0 1.9 3.3h9.4A2.2 2.2 0 0 0 18.6 18l-5.1-9.3V3.5 M7.6 14.5h8.8",
  map: "M9 4.2 3.5 6.6v13.2L9 17.4l6 2.4 5.5-2.4V4.2L15 6.6 9 4.2Z M9 4.2v13.2 M15 6.6v13.2",
  search: "M11 18.2a7.2 7.2 0 1 0 0-14.4 7.2 7.2 0 0 0 0 14.4Z M16.4 16.4 20.5 20.5",
  menu: "M4 7h16 M4 12h16 M4 17h16",
  close: "M6 6l12 12 M18 6 6 18",
  chevronDown: "M6 9.5 12 15.5 18 9.5",
  chevronRight: "M9.5 6 15.5 12 9.5 18",
  arrowRight: "M4.5 12h15 M13.5 6l6 6-6 6",
  arrowLeft: "M19.5 12h-15 M10.5 6l-6 6 6 6",
  offline: "M3 3l18 18 M8.8 15.6a4.6 4.6 0 0 1 6.4 0 M5.2 12.1a9.6 9.6 0 0 1 3.4-2.2 M2 8.6A14.6 14.6 0 0 1 6.6 6 M17.6 9.6a9.6 9.6 0 0 1 3.4 2.5 M12.4 6.1c3 .1 5.9 1 8.2 2.5 M12 19.2h.01",
  queued: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 7.5V12l3 1.8 M8 3.4 4.2 5.6 M16 3.4l3.8 2.2",
  refresh: "M20 12a8 8 0 1 1-2.6-5.9 M20 4v4.4h-4.4",
  action: "M13.2 2.5 4.5 13.6h6.1l-.8 7.9 8.7-11.1h-6.1l.8-7.9Z",
  trace: "M4 18.5h4.5l3-13h4.5 M16 3.5l3 2-3 2 M4 18.5l2.5-2 M4 18.5l2.5 2",
  activity: "M3 12.5h4l2.6-7 4 14 2.8-7H21",
  layers: "M12 3 3 7.6l9 4.6 9-4.6L12 3Z M3 12.5 12 17l9-4.5 M3 17 12 21.5 21 17",
  user: "M12 12.4a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4Z M4.4 20.5a7.8 7.8 0 0 1 15.2 0",
  external: "M14 4.5h5.5V10 M19.5 4.5 11 13 M18 14.5v5H4.5V6H10",
  fact: "M5 4.5h9.5L19 9v10.5H5V4.5Z M14 4.5V9h5 M8.2 13.4l2 2 3.6-3.9",
  forecast: "M3.5 16.5c2-5.5 4.5-8 7-8s3.6 3 6 3c1.6 0 3-1 4-2.4 M3.5 20.5h17",
  recommendation:
    "M9.4 18.6h5.2 M10 21.2h4 M12 3a5.8 5.8 0 0 0-3.4 10.5c.6.5 1 1.2 1 2h4.8c0-.8.4-1.5 1-2A5.8 5.8 0 0 0 12 3Z",
};

export interface IconProps {
  name: IconName;
  size?: number;
  /** Give it a label only when the icon is the sole carrier of meaning. */
  label?: string;
  className?: string;
  strokeWidth?: number;
}

export function Icon({
  name,
  size = 16,
  label,
  className,
  strokeWidth = 1.7,
}: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
    >
      {label ? <title>{label}</title> : null}
      {PATHS[name].split(" M").map((d, i) => (
        <path key={i} d={i === 0 ? d : `M${d}`} />
      ))}
    </svg>
  );
}

export default Icon;
