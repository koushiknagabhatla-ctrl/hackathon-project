"use client";

/**
 * Boot moment. The counter is the real measured load and runs on every full
 * page load, refresh included; client-side route changes are RouteTransition's
 * job. Composition follows bgrem.site: oversized counter top-left, wordmark
 * and progress rule on the bottom edge.
 */

import { useEffect, useRef, useState } from "react";
import { trackLoadProgress } from "@/lib/loadProgress";
import { gsap, reducedMotion } from "@/lib/motion";
import s from "./preloader.module.css";

const WORD = "AURALIS";

export function Preloader() {
  const [show, setShow] = useState(true);
  const [pct, setPct] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const exited = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const startedAt = performance.now();
    let handle: { stop: () => void } | null = null;

    const exit = () => {
      if (exited.current) return;
      exited.current = true;
      handle?.stop();

      const root = rootRef.current;
      if (reducedMotion() || !root) {
        setShow(false);
        return;
      }

      const hold = Math.max(0, 400 - (performance.now() - startedAt));
      const tl = gsap.timeline({ delay: hold / 1000, onComplete: () => setShow(false) });
      tl.to(root.querySelectorAll<HTMLElement>(`.${s.fade}`), {
        opacity: 0,
        y: -10,
        duration: 0.3,
        ease: "power2.in",
        stagger: 0.05,
      });
      tl.to(root, { clipPath: "inset(0% 0% 100% 0%)", duration: 0.8, ease: "expo.inOut" }, "-=0.1");
    };

    handle = trackLoadProgress((p, done) => {
      setPct(Math.round(p * 100));
      if (fillRef.current) fillRef.current.style.transform = `scaleX(${p})`;
      if (done) exit();
    });

    // A stalled subresource must never hold the app hostage.
    const failsafe = setTimeout(exit, 6000);
    return () => {
      clearTimeout(failsafe);
      handle?.stop();
    };
  }, []);

  if (!show) return null;

  return (
    <div
      className={s.root}
      ref={rootRef}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-label="Loading Auralis"
      style={{ clipPath: "inset(0% 0% 0% 0%)" }}
    >
      <div className={`${s.counter} ${s.fade}`} aria-hidden="true">
        <span className={s.count}>{pct}</span>
        <span className={s.mark}>%</span>
      </div>

      <div className={`${s.baseline} ${s.fade}`} aria-hidden="true">
        <div className={s.wordmark}>
          {WORD.split("").map((ch, i) => (
            <span key={i} className={s.letter} style={{ animationDelay: `${i * 48}ms` }}>
              {ch}
            </span>
          ))}
        </div>
        <span className={s.status}>City intelligence</span>
      </div>

      <div className={`${s.rule} ${s.fade}`} aria-hidden="true">
        <span className={s.ruleFill} ref={fillRef} />
      </div>
    </div>
  );
}

export default Preloader;
