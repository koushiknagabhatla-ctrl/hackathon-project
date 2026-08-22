"use client";

/**
 * Registers /sw.js, and repairs the registration left by the build that
 * shipped without one.
 *
 * A worker registered against a script that 404s keeps its cache and throws on
 * every automatic update check. That is the stale-page failure, so this first
 * verifies the script is fetchable and unregisters the worker when it is not.
 */

import { useEffect } from "react";

async function scriptIsReachable(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    return res.ok && (res.headers.get("content-type") ?? "").includes("javascript");
  } catch {
    return false;
  }
}

export function ServiceWorkerRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const { protocol, hostname } = window.location;
    if (protocol !== "https:" && hostname !== "localhost" && hostname !== "127.0.0.1") return;

    let reloading = false;
    const onControllerChange = () => {
      if (reloading) return;
      reloading = true;
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);

    const timer = setTimeout(async () => {
      try {
        const reachable = await scriptIsReachable("/sw.js");

        // Clear any registration whose script cannot be fetched. Without this
        // a worker from an older build keeps serving its cache forever.
        const existing = await navigator.serviceWorker.getRegistrations();
        for (const reg of existing) {
          const url =
            reg.active?.scriptURL ?? reg.installing?.scriptURL ?? reg.waiting?.scriptURL;
          if (!reachable || !url || !(await scriptIsReachable(url))) {
            await reg.unregister().catch(() => undefined);
            const keys = await caches.keys().catch(() => [] as string[]);
            await Promise.all(keys.map((k) => caches.delete(k).catch(() => false)));
          }
        }

        if (!reachable) return;

        const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
        if (reg.waiting) reg.waiting.postMessage("auralis:skip-waiting");

        reg.addEventListener("updatefound", () => {
          const next = reg.installing;
          if (!next) return;
          next.addEventListener("statechange", () => {
            if (next.state === "installed" && navigator.serviceWorker.controller) {
              next.postMessage("auralis:skip-waiting");
            }
          });
        });

        await reg.update().catch(() => undefined);
      } catch {
        // Offline support is a bonus, never a hard requirement.
      }
    }, 1200);

    return () => {
      clearTimeout(timer);
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
    };
  }, []);

  return null;
}

export default ServiceWorkerRegister;
