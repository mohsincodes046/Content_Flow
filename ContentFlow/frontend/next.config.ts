import type { NextConfig } from "next";

// When set (e.g. on Render), the browser talks to this app only, and /api/* is
// proxied to the backend. That keeps the session cookie first-party. Unset in
// local development, where the browser calls the API directly.
// Render's private-network `hostport` value has no scheme (e.g. "contentflow-api:10000").
const rawApiOrigin = process.env.CONTENT_FLOW_API_INTERNAL_URL?.trim().replace(/\/$/, "");
const apiOrigin = rawApiOrigin && !/^https?:\/\//.test(rawApiOrigin) ? `http://${rawApiOrigin}` : rawApiOrigin;

const nextConfig: NextConfig = {
  cacheComponents: true,
  experimental: {
    // Proxied request bodies are cut off at 10 MB by default, which breaks media
    // uploads. Keep this just above the API's 50 MB limit so the API stays the
    // authority and returns its own 413 for oversized files.
    proxyClientMaxBodySize: "52mb",
  },
  async rewrites() {
    if (!apiOrigin) return { beforeFiles: [], afterFiles: [], fallback: [] };
    return {
      // beforeFiles so /api/* can never be captured by the /[section] page route.
      beforeFiles: [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }],
      afterFiles: [],
      fallback: [],
    };
  },
  partialPrefetching: true,
  turbopack: {
    root: __dirname,
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
