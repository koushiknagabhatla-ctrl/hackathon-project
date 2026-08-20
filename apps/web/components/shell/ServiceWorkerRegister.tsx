"use client";

/**
 * Registers /sw.js so /field keeps working with no signal.
 *
 * Deliberately does NOT ask for notification or geolocation permission here.
 * Those are requested contextually, at the moment the operator asks for the
 * capability, never on first load.
 */

import { useEffect } from "react";

export function ServiceWorkerRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    if (window.location.protocol !== "https:" && window.location.hostname !== "localhost")
      return;
    const t = setTimeout(() => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* offline support is a bonus, never a hard requirement */
      });
    }, 1200);
    return () => clearTimeout(t);
  }, []);
  return null;
}

export default ServiceWorkerRegister;
