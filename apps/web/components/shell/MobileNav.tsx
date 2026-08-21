"use client";

/**
 * MobileNav — the five-destination bottom bar under 768px.
 * Home, Incidents, Twin, Actions, More. Every target is at least 44x44px.
 * "More" raises the same full-screen sheet the navbar burger opens.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui/Icon";
import { BOTTOM_NAV, isActive } from "./nav";
import { useShell } from "./ShellState";
import s from "./shell.module.css";

const OPEN_MENU_EVENT = "auralis:open-menu";

export function MobileNav() {
  const pathname = usePathname();
  const { criticalIncidents } = useShell();

  return (
    <nav className={s.bottom} aria-label="Primary, mobile">
      {BOTTOM_NAV.map((item) => {
        const active = isActive(pathname, item.href);
        const badge = item.href === "/command" ? criticalIncidents.length : 0;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={s.bottomItem}
            data-active={active}
            aria-current={active ? "page" : undefined}
          >
            <Icon name={item.icon} size={20} />
            {item.label}
            {badge > 0 && (
              <span className={s.bottomBadge} aria-hidden="true">
                {badge}
              </span>
            )}
            {badge > 0 && (
              <span className="sr-only">
                {badge} critical incident{badge > 1 ? "s" : ""}
              </span>
            )}
          </Link>
        );
      })}
      <button
        type="button"
        className={s.bottomItem}
        onClick={() => window.dispatchEvent(new CustomEvent(OPEN_MENU_EVENT))}
        aria-label="More destinations"
      >
        <Icon name="menu" size={20} />
        More
      </button>
    </nav>
  );
}

export default MobileNav;
