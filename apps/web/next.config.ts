import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The UI tests build into their own folder (playwright.config.ts sets NEXT_DIST_DIR), so they never
  // replace the normal build in .next with one that talks to the e2e API.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  // Security headers on every page (prompt 46): no framing by other sites, no type guessing, the address sent to
  // other sites cut to the origin, and no camera or location; the microphone only for her voice notes here.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'" },
        ],
      },
    ];
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
