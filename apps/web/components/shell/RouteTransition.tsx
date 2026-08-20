"use client";

/**
 * RouteTransition — the shared-axis route change, in one place.
 *
 * The App Router has no exit hook, so the exit is done where the intent
 * actually happens: a capture-phase click handler on internal links plays the
 * outgoing clip/fade, then pushes. The incoming view animates in on mount.
 * Every link in the app gets this, including Lane E's, with no extra work.
 *
 * Under prefers-reduced-motion both halves are skipped and navigation is
 * immediate — the state change still happens, just without the movement.
 */

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { pageEnter, routeExit, reducedMotion } from "@/lib/motion";

export function RouteTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);

  // incoming
  useEffect(() => {
    pageEnter(ref.current);
  }, [pathname]);

  // outgoing
  useEffect(() => {
    if (reducedMotion()) return;
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as HTMLElement)?.closest?.("a");
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href || !href.startsWith("/")) return;
      if (a.target && a.target !== "_self") return;
      if (a.hasAttribute("download")) return;
      const [path] = href.split("#");
      if (path === pathname) return;

      e.preventDefault();
      void routeExit(ref.current).then(() => router.push(href));
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [pathname, router]);

  return <div ref={ref}>{children}</div>;
}

export default RouteTransition;
