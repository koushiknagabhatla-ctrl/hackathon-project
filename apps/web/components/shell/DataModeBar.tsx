"use client";

/**
 * DataModeBar — the honesty valve.
 *
 * The web app deploys to Vercel where the Python API is not reachable, so
 * lib/api.ts falls back to a bundled snapshot for reads. The moment that
 * happens this bar appears and stays: hatched border, orange, permanent, with
 * an assertive live-region announcement. Demo data is never allowed to pass as
 * observed city state.
 */

import { useDataMode } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import s from "./shell.module.css";

export function DataModeBar() {
  const mode = useDataMode();
  if (mode !== "fixture") return null;

  return (
    <div className={s.demoBar} role="status" aria-live="polite">
      <span className={s.demo}>
        <Icon name="synthetic" size={14} />
        Demo data — API not connected
      </span>
    </div>
  );
}

export default DataModeBar;
