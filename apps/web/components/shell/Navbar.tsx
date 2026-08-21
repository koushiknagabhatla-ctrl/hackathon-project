"use client";

/**
 * Navbar — 64px desktop / 56px mobile, fixed, transparent until you scroll.
 *
 *  - compresses on scroll down, returns instantly on scroll up
 *  - NEVER compresses or moves while a critical incident is open
 *  - active route = orange indicator + heavier text + aria-current="page"
 *  - "More" opens a mega-panel on hover (pointer devices) or on click,
 *    Escape closes it, Up/Down move between its items
 *  - under 1024px the destinations move into a full-screen sheet
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Icon } from "@/components/ui/Icon";
import { Drawer } from "@/components/ui/Drawer";
import { PRINCIPALS, getPrincipal, setPrincipal } from "@/lib/api";
import type { Role } from "@/lib/types";
import { useShell } from "./ShellState";
import { LocationSwitcher } from "./LocationSwitcher";
import { ALL_NAV, GROUP_LABEL, PRIMARY, SECONDARY, isActive } from "./nav";
import s from "./shell.module.css";

const ROLES: Role[] = ["operator", "approver", "auditor", "admin"];

function useScrollState(locked: boolean) {
  const [scrolled, setScrolled] = useState(false);
  const [compact, setCompact] = useState(false);
  const last = useRef(0);

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      setScrolled(y > 8);
      if (locked) {
        // A critical incident is open: the bar never moves.
        setCompact(false);
      } else if (y > last.current && y > 120) {
        setCompact(true);
      } else if (y < last.current) {
        setCompact(false);
      }
      last.current = y;
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [locked]);

  return { scrolled, compact };
}

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { criticalIncidents, streamStatus } = useShell();
  const critical = criticalIncidents.length > 0;
  const { scrolled, compact } = useScrollState(critical);

  const [moreOpen, setMoreOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [roleOpen, setRoleOpen] = useState(false);
  const [principal, setPrincipalState] = useState<string>("p_operator");

  const moreRef = useRef<HTMLDivElement>(null);
  const roleRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setPrincipalState(getPrincipal()), []);

  // route change closes everything
  useEffect(() => {
    setMoreOpen(false);
    setSheetOpen(false);
    setRoleOpen(false);
  }, [pathname]);

  // Escape closes any open menu; body scroll lock for the mobile sheet
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setMoreOpen(false);
      setRoleOpen(false);
      setSheetOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // the mobile bottom bar raises the same sheet
  useEffect(() => {
    const open = () => setSheetOpen(true);
    window.addEventListener("auralis:open-menu", open);
    return () => window.removeEventListener("auralis:open-menu", open);
  }, []);

  useEffect(() => {
    document.body.style.overflow = sheetOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [sheetOpen]);

  // click-outside for the two desktop popovers
  useEffect(() => {
    if (!moreOpen && !roleOpen) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (moreOpen && moreRef.current && !moreRef.current.contains(t)) setMoreOpen(false);
      if (roleOpen && roleRef.current && !roleRef.current.contains(t)) setRoleOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [moreOpen, roleOpen]);

  /** Up/Down move between links inside an open menu group. */
  const onMenuKey = useCallback((e: React.KeyboardEvent<HTMLElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = Array.from(
      e.currentTarget.querySelectorAll<HTMLElement>("[data-menuitem]"),
    );
    if (!items.length) return;
    e.preventDefault();
    const i = items.indexOf(document.activeElement as HTMLElement);
    const next =
      e.key === "ArrowDown"
        ? items[(i + 1 + items.length) % items.length]
        : items[(i - 1 + items.length) % items.length];
    next?.focus();
  }, []);

  const hoverOpen = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches)
      setMoreOpen(true);
  };
  const hoverClose = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setMoreOpen(false), 160);
  };

  const statusLabel =
    streamStatus === "live"
      ? "Live"
      : streamStatus === "connecting"
        ? "Connecting"
        : "Degraded";

  function chooseRole(role: Role) {
    const id = PRINCIPALS[role];
    setPrincipal(id);
    setPrincipalState(id);
    setRoleOpen(false);
    router.refresh();
  }

  const currentRole =
    (Object.entries(PRINCIPALS).find(([, id]) => id === principal)?.[0] as Role) ??
    "operator";

  return (
    <>
      <header
        className={s.nav}
        data-scrolled={scrolled}
        data-compact={compact}
        data-critical={critical}
      >
        <div className={s.inner}>
          <Link href="/" className={s.wordmark} aria-label="Auralis, home">
            Auralis
          </Link>

          <nav className={s.primary} aria-label="Primary">
            {PRIMARY.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={s.link}
                  data-active={active}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon name={item.icon} size={15} />
                  {item.label}
                  {active && <span className="sr-only">(current page)</span>}
                </Link>
              );
            })}

            <div
              className={s.panelWrap}
              ref={moreRef}
              onMouseEnter={hoverOpen}
              onMouseLeave={hoverClose}
              onKeyDown={onMenuKey}
            >
              <button
                type="button"
                className={s.link}
                aria-expanded={moreOpen}
                aria-haspopup="true"
                onClick={() => setMoreOpen((v) => !v)}
              >
                More
                <Icon name="chevronDown" size={14} />
              </button>
              {moreOpen && (
                <div className={s.panel} role="menu" aria-label="More destinations">
                  {(["operate", "assure", "communicate"] as const).map((g) => {
                    const items = SECONDARY.filter((i) => i.group === g);
                    if (!items.length) return null;
                    return (
                      <div key={g} className={s.panelGroup}>
                        <div className={s.panelGroupLabel}>{GROUP_LABEL[g]}</div>
                        {items.map((item) => {
                          const active = isActive(pathname, item.href);
                          return (
                            <Link
                              key={item.href}
                              href={item.href}
                              className={s.panelItem}
                              role="menuitem"
                              data-menuitem
                              data-active={active}
                              aria-current={active ? "page" : undefined}
                            >
                              <Icon name={item.icon} size={17} />
                              <div className={s.panelItemText}>
                                <span className={s.panelItemLabel}>{item.label}</span>
                                <span className={s.panelItemBlurb}>{item.blurb}</span>
                              </div>
                            </Link>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </nav>

          <div className={s.right}>
            <LocationSwitcher />

            <button
              type="button"
              className={s.ctl}
              onClick={() => setSearchOpen(true)}
              aria-label="Search incidents, evidence and actions"
            >
              <Icon name="search" size={17} />
            </button>

            <span
              className={s.status}
              role="status"
              aria-live="polite"
              title={`Realtime stream ${statusLabel}`}
            >
              <span className={s.dot} data-state={streamStatus} aria-hidden="true" />
              <span className={s.statusText}>{statusLabel}</span>
              <span className="sr-only">Realtime stream {statusLabel}.</span>
            </span>

            <div className={s.panelWrap} ref={roleRef} onKeyDown={onMenuKey}>
              <button
                type="button"
                className={`${s.ctl} ${s.ctlBordered}`}
                aria-expanded={roleOpen}
                aria-haspopup="true"
                onClick={() => setRoleOpen((v) => !v)}
              >
                <Icon name="user" size={16} />
                <span className={s.statusText}>{currentRole}</span>
              </button>
              {roleOpen && (
                <div
                  className={s.panel}
                  role="menu"
                  aria-label="Acting role"
                  style={{ gridTemplateColumns: "1fr", width: 260 }}
                >
                  <div className={s.panelGroup}>
                    <div className={s.panelGroupLabel}>Acting as</div>
                    {ROLES.map((r) => (
                      <button
                        key={r}
                        type="button"
                        className={s.panelItem}
                        role="menuitem"
                        data-menuitem
                        data-active={r === currentRole}
                        onClick={() => chooseRole(r)}
                        style={{ textAlign: "left", background: "none", border: 0, cursor: "pointer" }}
                      >
                        <Icon name={r === currentRole ? "check" : "user"} size={16} />
                        <span>
                          <span className={s.panelItemLabel}>{r}</span>
                          <span className={s.panelItemBlurb}>{PRINCIPALS[r]}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <button
              type="button"
              className={`${s.ctl} ${s.burger}`}
              onClick={() => setSheetOpen(true)}
              aria-label="Open menu"
              aria-expanded={sheetOpen}
            >
              <Icon name="menu" size={20} />
            </button>
          </div>
        </div>
      </header>

      {sheetOpen && (
        <div className={s.sheet} role="dialog" aria-modal="true" aria-label="Menu">
          <div className={s.sheetHead}>
            <span className={s.wordmark}>Auralis</span>
            <button
              type="button"
              className={`${s.ctl} ${s.ctlBordered}`}
              onClick={() => setSheetOpen(false)}
              aria-label="Close menu"
            >
              <Icon name="close" size={20} />
            </button>
          </div>
          <div className={s.sheetBody}>
            {(["operate", "assure", "communicate"] as const).map((g) => {
              const items = ALL_NAV.filter((i) => i.group === g);
              if (!items.length) return null;
              return (
                <section key={g} style={{ display: "grid", gap: 10 }}>
                  <h2 className={s.panelGroupLabel} style={{ border: 0, padding: 0 }}>
                    {GROUP_LABEL[g]}
                  </h2>
                  {items.map((item) => {
                    const active = isActive(pathname, item.href);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={s.sheetItem}
                        data-active={active}
                        aria-current={active ? "page" : undefined}
                        onClick={() => setSheetOpen(false)}
                      >
                        <Icon name={item.icon} size={20} />
                        <span className={s.sheetItemLabel}>{item.label}</span>
                        <Icon name="chevronRight" size={16} />
                        <span className={s.sheetItemBlurb}>{item.blurb}</span>
                      </Link>
                    );
                  })}
                </section>
              );
            })}
          </div>
        </div>
      )}

      <Drawer
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        title="Search"
        side="bottom"
      >
        <form
          className={s.searchForm}
          onSubmit={(e) => {
            e.preventDefault();
            const q = new FormData(e.currentTarget).get("q");
            setSearchOpen(false);
            router.push(`/command?q=${encodeURIComponent(String(q ?? ""))}`);
          }}
        >
          <input
            className={s.searchInput}
            name="q"
            type="search"
            autoFocus
            placeholder="Incident, evidence id, asset, action…"
            aria-label="Search query"
          />
          <button className="btn btn--primary" type="submit">
            Search
          </button>
        </form>
        <p className={s.searchHint}>
          Search covers incidents, evidence ids, assets and actions. Results open
          in the command centre.
        </p>
        <div className={s.searchList}>
          {ALL_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={s.sheetItem}
              onClick={() => setSearchOpen(false)}
            >
              <Icon name={item.icon} size={18} />
              <span className={s.sheetItemLabel}>{item.label}</span>
              <Icon name="arrowRight" size={16} />
            </Link>
          ))}
        </div>
      </Drawer>
    </>
  );
}

export default Navbar;
