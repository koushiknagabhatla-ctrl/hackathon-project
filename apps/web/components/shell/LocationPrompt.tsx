"use client";

/** Offers to switch to the city the device is actually in. Asked once. */

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import {
  locateUser,
  rememberChoice,
  rememberDenied,
  shouldOfferLocation,
  sourceLabel,
  type GeoResult,
} from "@/lib/geolocate";
import { useShell } from "./ShellState";
import s from "./shell.module.css";

type Phase = "hidden" | "offer" | "locating" | "result" | "error";

export function LocationPrompt() {
  const { location, setLocation, setPreciseCoords } = useShell();
  const [phase, setPhase] = useState<Phase>("hidden");
  const [result, setResult] = useState<GeoResult | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      if (shouldOfferLocation()) setPhase("offer");
    }, 2500);
    return () => clearTimeout(t);
  }, []);

  const run = async () => {
    setPhase("locating");
    const r = await locateUser();
    setResult(r);

    if (r.status !== "ok" || !r.coords || !r.match) {
      if (r.permissionDenied) rememberDenied();
      setPhase("error");
      return;
    }

    if (!r.match.insideCoverage) {
      setPhase("error");
      return;
    }

    if (r.match.location.id !== location.id) setLocation(r.match.location);
    setPreciseCoords({ lat: r.coords.lat, lon: r.coords.lon, accuracyM: r.accuracyM ?? 0 });
    rememberChoice(r.match.location.id);
    setPhase("result");
    setTimeout(() => setPhase("hidden"), 7000);
  };

  const dismiss = () => {
    rememberDenied();
    setPhase("hidden");
  };

  if (phase === "hidden") return null;

  return (
    <div className={s.geoBar} role="status" aria-live="polite">
      <span className={s.geoIcon}>
        <Icon name="map" size={15} />
      </span>

      {phase === "offer" && (
        <>
          <span className={s.geoText}>Use your location to set the city?</span>
          <button type="button" className={s.geoPrimary} onClick={run}>
            Use my location
          </button>
          <button type="button" className={s.geoGhost} onClick={dismiss}>
            Not now
          </button>
        </>
      )}

      {phase === "locating" && <span className={s.geoText}>Locating…</span>}

      {phase === "result" && result?.match && (
        <span className={s.geoText}>
          Switched to <strong>{result.match.location.name}</strong> —{" "}
          {sourceLabel(result.source, result.accuracyM)}
          {result.match.distanceKm >= 1 && `, ${result.match.distanceKm.toFixed(1)} km from its centre`}.
        </span>
      )}

      {phase === "error" && (
        <>
          <span className={s.geoText}>
            {result?.match && !result.match.insideCoverage
              ? `You appear to be ~${result.match.distanceKm.toFixed(0)} km from the nearest covered city (${result.match.location.name}), so nothing was switched.`
              : "No location source answered — GPS, network and IP all failed. Pick a city from the switcher."}
          </span>
          <button type="button" className={s.geoGhost} onClick={() => setPhase("hidden")}>
            Dismiss
          </button>
        </>
      )}
    </div>
  );
}

export default LocationPrompt;
