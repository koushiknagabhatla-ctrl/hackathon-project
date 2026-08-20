"use client";

/**
 * 404 — branded recovery state with safe navigation.
 *
 * "The city is still here. This page is not."
 * A minimal line-art city grid with one orange route fragment that stops
 * before the missing node. The route draws itself in 500ms; no looping.
 */

import Link from "next/link";
import s from "./not-found.module.css";

export default function NotFound() {
  return (
    <section className={`container ${s.wrap}`}>
      <div>
        <span className={s.code}>404 · NOT FOUND</span>
        <h1 className={s.title}>This route does not exist.</h1>
        <p className={s.sub}>
          The city is still here. This page is not. The incident queue, the evidence
          ledger and the command centre are all exactly where you left them.
        </p>
        <div className={s.actions}>
          <Link className="btn btn--primary" href="/command">
            Back to Command Center
          </Link>
          <Link className="btn" href="/">
            Return home
          </Link>
        </div>
      </div>

      {/* city grid SVG with the orange route fragment */}
      <svg className={s.art} viewBox="0 0 480 360" aria-hidden="true">
        {/* grid */}
        {Array.from({ length: 7 }).map((_, i) => (
          <line key={`h${i}`} className={s.grid} x1={0} y1={i * 60} x2={480} y2={i * 60} />
        ))}
        {Array.from({ length: 9 }).map((_, i) => (
          <line key={`v${i}`} className={s.grid} x1={i * 60} y1={0} x2={i * 60} y2={360} />
        ))}

        {/* city blocks */}
        {[
          [60, 60, 60, 60], [180, 60, 60, 60], [300, 60, 120, 60],
          [60, 180, 120, 60], [240, 180, 60, 60], [360, 180, 60, 60],
          [60, 300, 60, 60], [180, 300, 120, 60], [360, 300, 60, 60],
        ].map(([x, y, w, h], i) => (
          <g key={`b${i}`}>
            <rect className={s.blockFill} x={x} y={y} width={w} height={h} rx={4} />
            <rect className={s.block} x={x} y={y} width={w} height={h} rx={4} />
          </g>
        ))}

        {/* the one orange route fragment that stops */}
        <polyline
          className={s.route}
          points="0,240 60,240 120,240 180,240 240,240 300,240 300,180 300,120 360,120"
        />
        <circle className={s.routeEnd} cx={360} cy={120} r={5} />

        {/* the missing node */}
        <circle className={s.missing} cx={420} cy={120} r={14} />
        <line className={s.missingMark} x1={413} y1={113} x2={427} y2={127} />
        <line className={s.missingMark} x1={427} y1={113} x2={413} y2={127} />
        <text className={s.missingLabel} x={408} y={152}>NOT FOUND</text>
      </svg>
    </section>
  );
}
