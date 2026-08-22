import type { NextConfig } from "next";

const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const isProd = process.env.NODE_ENV === "production";

/**
 * CSP. Dev needs 'unsafe-eval' for React Refresh; production does not get it.
 * 'unsafe-inline' on styles stays because Next injects inline <style>.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  // API_ORIGIN is listed explicitly: CCTV snapshots are served by the API, and
  // in dev that is plain http, which `https:` does not cover.
  `img-src 'self' data: blob: https: ${API_ORIGIN}`,
  "font-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN} https://api.maptiler.com https://*.maptiler.com https://tiles.openfreemap.org https://*.openstreetmap.org`,
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  "upgrade-insecure-requests",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    // Geolocation stays on: the location prompt needs it. Everything else off.
    value: "camera=(), microphone=(self), geolocation=(self), payment=(), usb=(), magnetometer=(), interest-cohort=()",
  },
  ...(isProd
    ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
    : []),
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  compress: true,

  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      {
        // Content-hashed, so it can be cached hard.
        source: "/_next/static/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/fonts/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        // The worker must never be served stale or it cannot ship its own fix.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
};

export default nextConfig;
