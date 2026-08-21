import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = "https://citysense.auralis.io";
  const now = new Date();

  const routes = [
    "",
    "/citysense",
    "/chat",
    "/command",
    "/alerts",
    "/report",
    "/routes",
    "/emergency",
    "/analytics",
    "/executive",
    "/public",
    "/data-health",
    "/audit",
    "/trace",
    "/field",
    "/simulation",
    "/governance",
    "/actions",
  ];

  return routes.map((route) => ({
    url: `${baseUrl}${route}`,
    lastModified: now,
    changeFrequency: route === "" || route === "/citysense" || route === "/alerts" ? "always" : "hourly",
    priority: route === "" ? 1.0 : route === "/citysense" || route === "/chat" || route === "/command" ? 0.9 : 0.7,
  }));
}
