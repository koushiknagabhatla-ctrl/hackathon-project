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

/** Centre of the navbar. Five highest-value destinations, nothing more. */
export const PRIMARY: NavItem[] = [
  {
    href: "/",
    label: "Home",
    blurb: "City operational overview, live GIS twin, and module launchpads.",
    icon: "layers",
    group: "operate",
  },
  {
    href: "/command",
    label: "Command",
    blurb: "Live incidents, twin and the evidence that supports them.",
    icon: "activity",
    group: "operate",
  },
  {
    href: "/emergency",
    label: "Emergency 112",
    blurb: "Multi-signal accident corroboration & ERSS 112 CAD dispatch.",
    icon: "shield",
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
    blurb: "Reconstruct any decision from evidence to effect.",
    icon: "trace",
    group: "assure",
  },
  {
    href: "/data-health",
    label: "Data health",
    blurb: "Connector freshness, quality and open conflicts.",
    icon: "source",
    group: "assure",
  },
  {
    href: "/simulation",
    label: "Simulation",
    blurb: "Counterfactuals in the sandbox twin. Never production.",
    icon: "synthetic",
    group: "assure",
  },
];

/** Everything else, grouped, behind "More". */
export const SECONDARY: NavItem[] = [
  {
    href: "/audit",
    label: "Audit ledger",
    blurb: "Append-only, hash-chained record with chain verification.",
    icon: "shield",
    group: "assure",
  },
  {
    href: "/governance",
    label: "Governance",
    blurb: "Policy bundles, agent authority and the kill switch.",
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
    href: "/public",
    label: "Public status",
    blurb: "The redacted, disclosure-delayed view the city sees.",
    icon: "user",
    group: "communicate",
  },
  {
    href: "/field",
    label: "Field",
    blurb: "Offline-capable work orders for crews on the ground.",
    icon: "map",
    group: "operate",
  },
];

export const GROUP_LABEL: Record<NavItem["group"], string> = {
  operate: "Operate",
  assure: "Assure",
  communicate: "Communicate",
};

export const ALL_NAV: NavItem[] = [...PRIMARY, ...SECONDARY];

/**
 * Mobile bottom bar — exactly five, fixed.
 * "Incidents" is the command surface and "Twin" is the trace surface; there is
 * no separate route for either in the contract.
 */
export const BOTTOM_NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Home", icon: "layers" },
  { href: "/command", label: "Incidents", icon: "activity" },
  { href: "/trace", label: "Twin", icon: "trace" },
  { href: "/actions", label: "Actions", icon: "action" },
];

/** True when `pathname` is inside `href`. Used for aria-current. */
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
