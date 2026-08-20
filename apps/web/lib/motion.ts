"use client";

/**
 * lib/motion.ts — the Auralis motion system. GSAP + ScrollTrigger.
 *
 * Non-negotiables baked in here:
 *  - transform / opacity / clip-path only. Never width, height, top, margin.
 *  - ScrollTrigger is for storytelling sections only. NEVER per list row.
 *  - every animation runs inside a gsap.context() that the caller reverts.
 *  - prefers-reduced-motion kills parallax, scrub and route wipes; state
 *    changes and essential feedback still happen, instantly.
 *
 * Lane E usage:
 *   useGsap((ctx, scope) => { sectionReveal(scope); }, []);   // auto cleanup
 *   await routeExit(el); revealMap(mapEl, layerEls);
 */

import { useEffect, useRef, type DependencyList, type RefObject } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/** Durations in seconds (GSAP units). Mirrors the --t-* tokens in globals.css. */
export const DUR = {
  press: 0.09,
  hover: 0.16,
  menu: 0.15,
  page: 0.6,
  reveal: 0.55,
  drawer: 0.38,
  toast: 0.28,
  map: 0.9,
} as const;

export const EASE = {
  out: "power3.out",
  inOut: "power2.inOut",
  spring: "back.out(1.25)",
} as const;

let registered = false;
function ensurePlugins() {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);
  registered = true;
}

/** Live check — the user can flip this mid-session. */
export function reducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Pointer-device check. Hover transforms are pointer-only. */
export function finePointer(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

type Target = gsap.TweenTarget;

/** Page enter: opacity 0->1 + y 18->0 over ~600ms. */
export function pageEnter(target: Target) {
  if (reducedMotion()) {
    gsap.set(target, { opacity: 1, y: 0, clipPath: "none" });
    return gsap.timeline();
  }
  return gsap.fromTo(
    target,
    { opacity: 0, y: 18 },
    { opacity: 1, y: 0, duration: DUR.page, ease: EASE.out, clearProps: "transform" },
  );
}

/** Route exit: current view leaves via clip + fade on the shared vertical axis. */
export function routeExit(target: Target): Promise<void> {
  if (reducedMotion()) return Promise.resolve();
  return new Promise((resolve) => {
    gsap.to(target, {
      opacity: 0,
      y: -10,
      duration: 0.18,
      ease: "power2.in",
      onComplete: () => resolve(),
    });
  });
}

/**
 * Section reveal: y 24->0, opacity 0->1, 30-60ms stagger, ScrollTrigger once.
 * Only call this on storytelling sections. Mark children `.js-reveal`.
 */
export function sectionReveal(
  scope: Element | null,
  selector = ".js-reveal",
  opts: { stagger?: number; start?: string } = {},
) {
  if (!scope) return;
  const items = Array.from(scope.querySelectorAll<HTMLElement>(selector));
  if (!items.length) return;

  if (reducedMotion()) {
    gsap.set(items, { opacity: 1, y: 0 });
    return;
  }
  ensurePlugins();
  gsap.fromTo(
    items,
    { opacity: 0, y: 24 },
    {
      opacity: 1,
      y: 0,
      duration: DUR.reveal,
      ease: EASE.out,
      stagger: opts.stagger ?? 0.045,
      scrollTrigger: {
        trigger: scope,
        start: opts.start ?? "top 82%",
        once: true,
      },
    },
  );
}

/**
 * Map reveal: soft clip mask opens, then data layers fade in BY PRIORITY.
 * `layers` is ordered most-important-first.
 */
export function revealMap(map: Element | null, layers: Element[] = []) {
  if (!map) return;
  if (reducedMotion()) {
    gsap.set(map, { clipPath: "inset(0% 0% 0% 0%)", opacity: 1 });
    gsap.set(layers, { opacity: 1 });
    return;
  }
  const tl = gsap.timeline();
  tl.fromTo(
    map,
    { clipPath: "inset(6% 8% 6% 8% round 18px)", opacity: 0.2 },
    {
      clipPath: "inset(0% 0% 0% 0% round 18px)",
      opacity: 1,
      duration: DUR.map,
      ease: EASE.out,
    },
  );
  if (layers.length) {
    tl.fromTo(
      layers,
      { opacity: 0 },
      { opacity: 1, duration: 0.4, ease: "none", stagger: 0.09 },
      "-=0.45",
    );
  }
  return tl;
}

/** Drawer: x/clip 24px, 300-420ms, spring-ish. `dir` is the edge it comes from. */
export function drawerIn(el: Element | null, dir: "right" | "left" | "bottom" = "right") {
  if (!el) return;
  if (reducedMotion()) {
    gsap.set(el, { x: 0, y: 0, opacity: 1 });
    return;
  }
  const from =
    dir === "bottom" ? { y: 24, opacity: 0 } : { x: dir === "right" ? 24 : -24, opacity: 0 };
  return gsap.fromTo(el, from, {
    x: 0,
    y: 0,
    opacity: 1,
    duration: DUR.drawer,
    ease: EASE.spring,
  });
}

export function drawerOut(
  el: Element | null,
  dir: "right" | "left" | "bottom" = "right",
): Promise<void> {
  if (!el || reducedMotion()) return Promise.resolve();
  return new Promise((resolve) => {
    gsap.to(el, {
      x: dir === "right" ? 24 : dir === "left" ? -24 : 0,
      y: dir === "bottom" ? 24 : 0,
      opacity: 0,
      duration: 0.22,
      ease: "power2.in",
      onComplete: () => resolve(),
    });
  });
}

/** Toast: y 12->0 + fade. Auto-dismiss is the caller's job and only if non-critical. */
export function toastIn(el: Element | null) {
  if (!el) return;
  if (reducedMotion()) {
    gsap.set(el, { y: 0, opacity: 1 });
    return;
  }
  return gsap.fromTo(
    el,
    { y: 12, opacity: 0 },
    { y: 0, opacity: 1, duration: DUR.toast, ease: EASE.out },
  );
}

/**
 * Telemetry counter. Writes into the element's textContent — the caller is
 * responsible for the numeral font (.num). Skips the tween under reduced motion.
 */
export function countTo(
  el: HTMLElement | null,
  to: number,
  opts: { from?: number; duration?: number; decimals?: number; pad?: number } = {},
) {
  if (!el) return;
  const decimals = opts.decimals ?? 0;
  const fmt = (v: number) => {
    const s = v.toFixed(decimals);
    return opts.pad ? s.padStart(opts.pad, "0") : s;
  };
  if (reducedMotion()) {
    el.textContent = fmt(to);
    return;
  }
  const state = { v: opts.from ?? 0 };
  return gsap.to(state, {
    v: to,
    duration: opts.duration ?? 0.9,
    ease: EASE.out,
    onUpdate: () => {
      el.textContent = fmt(state.v);
    },
  });
}

/**
 * Scoped GSAP with guaranteed cleanup. Returns the scope ref to spread on the
 * wrapper element. Every tween created inside is reverted on unmount / route
 * change, which is what stops ScrollTrigger leaking between pages.
 */
export function useGsap<T extends HTMLElement = HTMLDivElement>(
  fn: (ctx: gsap.Context, scope: T) => void,
  deps: DependencyList = [],
): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    ensurePlugins();
    const el = ref.current;
    if (!el) return;
    const ctx = gsap.context((self) => fn(self, el), el);
    return () => {
      ctx.revert();
      ScrollTrigger.refresh();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

export { gsap, ScrollTrigger };
