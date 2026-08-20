"use client";

/**
 * Preloader — a boot moment, not a decoration.
 *
 * The number is REAL. It is the fraction of actual readiness promises that
 * have settled: the API health probe, the evidence index, the policy/ops
 * metrics and the font/map layer. It cannot reach 100 while anything is still
 * in flight, and a probe that fails is reported as DEGRADED rather than
 * silently counted as ready.
 *
 * It is skipped entirely on any navigation after the first in a session —
 * screens show their own local skeletons instead. Under prefers-reduced-motion
 * the reveal is instant.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { gsap, reducedMotion } from "@/lib/motion";
import s from "./preloader.module.css";

const BOOT_KEY = "auralis.booted";

type StageState = "pending" | "ready" | "degraded";

interface Stage {
  key: string;
  label: string;
  run: () => Promise<unknown>;
}

const STAGES: Stage[] = [
  {
    key: "city",
    label: "Connecting city state",
    run: () => api.get("/v1/health"),
  },
  {
    key: "evidence",
    label: "Evidence index ready",
    run: () => api.get("/v1/data-health"),
  },
  {
    key: "policy",
    label: "Policy engine ready",
    run: () => api.get("/v1/metrics/ops"),
  },
  {
    key: "map",
    label: "Map layer ready",
    run: () =>
      typeof document !== "undefined" && "fonts" in document
        ? document.fonts.ready
        : Promise.resolve(),
  },
];

export function Preloader() {
  // Assume booted during SSR so the markup never flashes a loader for a
  // returning visitor; the effect corrects it on first mount.
  const [show, setShow] = useState(false);
  const [states, setStates] = useState<StageState[]>(() => STAGES.map(() => "pending"));
  const [pct, setPct] = useState(0);
  const [stageLabel, setStageLabel] = useState(STAGES[0].label);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.sessionStorage.getItem(BOOT_KEY)) return;
    setShow(true);
  }, []);

  useEffect(() => {
    if (!show) return;
    let alive = true;
    const startedAt = Date.now();
    let settled = 0;

    const bump = (i: number, ok: boolean) => {
      if (!alive) return;
      settled += 1;
      setStates((prev) => {
        const next = [...prev];
        next[i] = ok ? "ready" : "degraded";
        return next;
      });
      // Real progress: settled promises over total. Never ahead of the work.
      setPct(Math.round((settled / STAGES.length) * 100));
      const nextPending = STAGES[settled];
      if (nextPending) setStageLabel(nextPending.label);
    };

    Promise.all(
      STAGES.map((stage, i) =>
        stage
          .run()
          .then(() => bump(i, true))
          .catch(() => bump(i, false)),
      ),
    ).then(() => {
      if (!alive) return;
      window.sessionStorage.setItem(BOOT_KEY, "1");
      // Keep the boot moment perceptible but short: 1.2s ceiling when cached.
      const elapsed = Date.now() - startedAt;
      const hold = Math.max(0, 520 - elapsed);
      setTimeout(() => {
        if (!alive) return;
        if (reducedMotion() || !rootRef.current) {
          setShow(false);
          return;
        }
        gsap.to(rootRef.current, {
          clipPath: "inset(0% 0% 100% 0%)",
          duration: 0.62,
          ease: "power3.inOut",
          onComplete: () => alive && setShow(false),
        });
      }, hold);
    });

    return () => {
      alive = false;
    };
  }, [show]);

  if (!show) return null;

  const showCounter = pct >= 15;
  const showLines = pct >= 60 || states.some((st) => st !== "pending");

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
      <div className={s.centre}>
        <div className={s.wordmark}>Auralis</div>
        {showCounter && (
          <div className={s.counter}>
            <span className={s.count}>{String(pct).padStart(2, "0")}</span>
            <span className={s.of}>/ 100</span>
          </div>
        )}
        <div className={s.stage} aria-live="polite">
          {showCounter ? stageLabel : " "}
        </div>
      </div>

      <div className={s.bottom}>
        <div className={s.track}>
          <div className={s.fill} style={{ width: `${pct}%` }} />
        </div>
        {showLines && (
          <ul className={s.lines}>
            {STAGES.map((stage, i) => (
              <li key={stage.key} className={s.line} data-state={states[i]}>
                <span className={s.lineMark}>
                  {states[i] === "ready" ? (
                    <Icon name="check" size={14} />
                  ) : states[i] === "degraded" ? (
                    <Icon name="major" size={14} />
                  ) : (
                    <Icon name="clock" size={14} />
                  )}
                </span>
                <span>{stage.label}</span>
                <span className={s.lineNote}>
                  {states[i] === "pending"
                    ? "…"
                    : states[i] === "ready"
                      ? "OK"
                      : "DEGRADED"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default Preloader;
