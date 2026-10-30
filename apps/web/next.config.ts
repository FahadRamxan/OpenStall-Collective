import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The UI tests build into their own folder (playwright.config.ts sets NEXT_DIST_DIR), so they never
  // replace the normal build in .next with one that talks to the e2e API.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
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
