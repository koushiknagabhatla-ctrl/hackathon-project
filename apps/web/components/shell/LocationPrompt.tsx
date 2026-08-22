"use client";

/**
 * Offers to switch to the city the device is in.
 *
 * Failure here is usually the browser blocking the site, not the code, so the
 * message says how to unblock it and offers a retry. A dead end that just says
 * "could not be read" leaves the user with nothing to do.
 */

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

  const apply = (r: GeoResult) => {
    if (!r.match || !r.coords) return;
    if (r.match.location.id !== location.id) setLocation(r.match.location);
    setPreciseCoords({ lat: r.coords.lat, lon: r.coords.lon, accuracyM: r.accuracyM ?? 0 });
    rememberChoice(r.match.location.id);
    setPhase("result");
    setTimeout(() => setPhase("hidden"), 7000);
  };

  const run = async () => {
    setPhase("locating");
    const r = await locateUser();
    setResult(r);
    if (r.status === "ok" && r.coords && r.match?.insideCoverage) {
      apply(r);
      return;
    }
    if (r.permissionDenied) rememberDenied();
    setPhase("error");
  };

  const dismiss = () => {
    rememberDenied();
    setPhase("hidden");
  };

  if (phase === "hidden") return null;

  // Outside coverage still knows the closest covered city, so offer it rather
  // than stopping.
  const farMatch =
    result?.status === "ok" && result.match && !result.match.insideCoverage
      ? result.match
      : null;

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
          {result.match.distanceKm >= 1 &&
            `, ${result.match.distanceKm.toFixed(1)} km from its centre`}
          .
        </span>
      )}

      {phase === "error" && (
        <>
          <span className={s.geoText}>
            {farMatch ? (
              <>
                Your network places you near{" "}
                <strong>{farMatch.location.name}</strong>, about{" "}
                {farMatch.distanceKm.toFixed(0)} km outside the covered area.
              </>
            ) : result?.permissionDenied ? (
              <>
                Location is blocked for this site. Click the location icon in the
                address bar, choose <strong>Allow</strong>, then retry. On Brave,
                also check the Shields panel.
              </>
            ) : (
              <>No location source answered. Pick a city from the switcher.</>
            )}
          </span>

          {farMatch && (
            <button
              type="button"
              className={s.geoPrimary}
              onClick={() => result && apply(result)}
            >
              Use {farMatch.location.name}
            </button>
          )}
          {!farMatch && (
            <button type="button" className={s.geoPrimary} onClick={run}>
              Retry
            </button>
          )}
          <button type="button" className={s.geoGhost} onClick={() => setPhase("hidden")}>
            Dismiss
          </button>
        </>
      )}
    </div>
  );
}

export default LocationPrompt;
