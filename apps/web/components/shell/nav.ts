import type { IconName } from "@/components/ui/Icon";

/**
 * The navigation model. One list, three surfaces: desktop navbar, desktop
 * "More" mega-panel, mobile sheet + bottom bar. Lane E should not hard-code
 * links to these routes anywhere else.
 */

export interface NavItem {
  href: string;
  label: string;
  /** One line, shown in the mega-panel and the mobile sheet. */
  blurb: string;
  icon: IconName;
  group: "operate" | "assure" | "communicate";
}

/**
 * Centre of the navbar. Five destinations, no more: past five the bar stops
 * being scannable and starts being a sitemap. Everything else is behind More.
 */
export const PRIMARY: NavItem[] = [
  {
    href: "/chat",
    label: "Auralis AI",
    blurb: "Conversational AI assistant connected to every city service.",
    icon: "recommendation",
    group: "operate",
  },
  {
    href: "/citysense",
    label: "CitySense AP",
    blurb: "Real-time Andhra Pradesh geospatial intelligence map across all 26 districts.",
    icon: "map",
    group: "operate",
  },
  {
    href: "/command",
    label: "Command",
    blurb: "Live incidents, the city twin and the evidence that supports them.",
    icon: "activity",
    group: "operate",
  },
  {
    href: "/actions",
    label: "Actions",
    blurb: "The authorisation queue and everything currently executing.",
    icon: "action",
    group: "operate",
  },
  {
    href: "/trace",
    label: "Trace",
    blurb: "Reconstruct any decision from claim to evidence to verified effect.",
    icon: "trace",
    group: "assure",
  },
  {
    href: "/data-health",
    label: "Data health",
    blurb: "Connector freshness, schema status and open conflicts.",
    icon: "source",
    group: "assure",
  },
  {
    href: "/audit",
    label: "Audit",
    blurb: "Append-only, hash-chained record with chain verification.",
    icon: "shield",
    group: "assure",
  },
];

/** Everything else, grouped, behind "More". */
export const SECONDARY: NavItem[] = [
  {
    href: "/alerts",
    label: "Hazard Alerts",
    blurb: "Predictive multi-signal hazard detection and early warning broadcasts.",
    icon: "critical",
    group: "operate",
  },
  {
    href: "/routes",
    label: "Safe Routes",
    blurb: "Turn-by-turn navigation with dynamic flood & accident avoidance.",
    icon: "map",
    group: "operate",
  },
  {
    href: "/report",
    label: "Report Issue",
    blurb: "Citizen issue reporting with AI visual inspection and triage.",
    icon: "activity",
    group: "communicate",
  },
  {
    href: "/emergency",
    label: "Emergency 112",
    blurb: "Multi-signal accident corroboration and ERSS 112 dispatch.",
    icon: "shield",
    group: "operate",
  },
  {
    href: "/field",
    label: "Field",
    blurb: "Offline-capable work orders for crews on the ground.",
    icon: "map",
    group: "operate",
  },
  {
    href: "/simulation",
    label: "Simulation",
    blurb: "Counterfactuals in the sandbox twin. Never production.",
    icon: "synthetic",
    group: "assure",
  },
  {
    href: "/governance",
    label: "Governance",
    blurb: "Policy bundles, roles, connectors, tool manifests and the kill switch.",
    icon: "lock",
    group: "assure",
  },
  {
    href: "/executive",
    label: "Executive",
    blurb: "Outcomes, cost and service levels for the city leadership.",
    icon: "layers",
    group: "communicate",
  },
  {
    href: "/analytics",
    label: "Analytics",
    blurb: "Operational KPIs, SLA compliance rates and AI gateway metrics.",
    icon: "trace",
    group: "communicate",
  },
  {
    href: "/public",
    label: "Public status",
    blurb: "The redacted, disclosure-delayed view the city sees.",
    icon: "user",
    group: "communicate",
  },
];

export const GROUP_LABEL: Record<NavItem["group"], string> = {
  operate: "Operate",
  assure: "Assure",
  communicate: "Communicate",
};

export const ALL_NAV: NavItem[] = [...PRIMARY, ...SECONDARY];

/**
 * Mobile bottom bar. Four destinations plus More, which raises the same
 * full-screen sheet the desktop burger opens, so nothing is unreachable.
 * Every target is at least 44x44px.
 */
export const BOTTOM_NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Home", icon: "layers" },
  { href: "/chat", label: "Auralis AI", icon: "recommendation" },
  { href: "/command", label: "Command", icon: "activity" },
  { href: "/actions", label: "Actions", icon: "action" },
];

/** True when `pathname` is inside `href`. Used for aria-current. */
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
