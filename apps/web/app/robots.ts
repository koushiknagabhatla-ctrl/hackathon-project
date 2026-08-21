import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/actions/", "/governance/", "/simulation/"],
      },
    ],
    sitemap: "https://citysense.auralis.io/sitemap.xml",
  };
}
