"use client";

/**
 * OfflineIndicator — the field PWA's connection truth, always visible.
 *
 * Three honest states, each with a word, an icon and a border treatment:
 *   offline  no network, work is being recorded locally
 *   queued   network is back, N submissions still waiting to sync
 *   synced   nothing outstanding
 *
 * Lane E owns the queue itself; this component just renders the count:
 *   <OfflineIndicator queued={pending.length} onSync={flush} />
 */

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import s from "./shell.module.css";

export interface OfflineIndicatorProps {
  /** Submissions recorded locally and not yet accepted by the API. */
  queued?: number;
  /** Called when the operator asks for a sync attempt. */
  onSync?: () => void;
}

export function OfflineIndicator({ queued = 0, onSync }: OfflineIndicatorProps) {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const state = !online ? "offline" : queued > 0 ? "queued" : "synced";
  const copy = {
    offline: "Offline — work is saved on this device",
    queued: `Queued — ${queued} waiting to sync`,
    synced: "Synced",
  }[state];
  const icon = { offline: "offline", queued: "queued", synced: "check" } as const;

  return (
    <div className={s.offline} data-state={state} role="status" aria-live="polite">
      <Icon name={icon[state]} size={15} />
      <span>
        {state === "queued" ? (
          <>
            Queued <span className={s.offlineCount}>{queued}</span>
          </>
        ) : state === "offline" ? (
          "Offline"
        ) : (
          "Synced"
        )}
      </span>
      {state === "queued" && onSync && (
        <button type="button" className="btn btn--sm" onClick={onSync}>
          Sync now
        </button>
      )}
      <span className="sr-only">{copy}</span>
    </div>
  );
}

export default OfflineIndicator;
