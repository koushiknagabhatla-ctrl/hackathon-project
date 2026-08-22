"use client";

/**
 * Route transition.
 *
 * The App Router has no exit hook, so the exit plays on a capture-phase click
 * of an internal link, then the push happens. The incoming view animates on
 * mount.
 *
 * Performance notes, because this runs on every navigation:
 *  - transform + opacity only, so the compositor does the work
 *  - will-change is set for the duration and cleared after, never left on
 *  - the exit is capped at 160ms; past that a transition reads as latency
 *  - a second click while one is running is ignored rather than queued
 *  - reduced-motion skips both halves and navigates immediately
 */

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { reducedMotion } from "@/lib/motion";

const EXIT_MS = 160;
const ENTER_MS = 380;
const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

export function RouteTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const navigating = useRef(false);

  // Incoming view.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    navigating.current = false;

    if (reducedMotion()) {
      el.style.opacity = "1";
      el.style.transform = "none";
      return;
    }

    // Web Animations API: no library on the navigation hot path.
    el.style.willChange = "opacity, transform";
    const anim = el.animate(
      [
        { opacity: 0, transform: "translate3d(0, 10px, 0)" },
        { opacity: 1, transform: "translate3d(0, 0, 0)" },
      ],
      { duration: ENTER_MS, easing: EASE, fill: "both" }
    );
    const clear = () => {
      el.style.willChange = "";
      anim.commitStyles?.();
      anim.cancel();
      el.style.opacity = "";
      el.style.transform = "";
    };
    anim.addEventListener("finish", clear, { once: true });
    return () => {
      anim.removeEventListener("finish", clear);
      el.style.willChange = "";
    };
  }, [pathname]);

  // Outgoing view.
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

      // Ignore a second click while a transition is already running.
      if (navigating.current) {
        e.preventDefault();
        return;
      }

      const el = ref.current;
      if (!el) return;

      e.preventDefault();
      navigating.current = true;

      el.style.willChange = "opacity, transform";
      const anim = el.animate(
        [
          { opacity: 1, transform: "translate3d(0, 0, 0)" },
          { opacity: 0, transform: "translate3d(0, -6px, 0)" },
        ],
        { duration: EXIT_MS, easing: "cubic-bezier(0.4, 0, 1, 1)", fill: "forwards" }
      );

      // Navigate when the exit finishes, or on a timer if the animation is
      // throttled in a background tab. Never leave the click unhandled.
      let pushed = false;
      const go = () => {
        if (pushed) return;
        pushed = true;
        router.push(href);
      };
      anim.addEventListener("finish", go, { once: true });
      setTimeout(go, EXIT_MS + 60);
    };

    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [pathname, router]);

  return <div ref={ref}>{children}</div>;
}

export default RouteTransition;
