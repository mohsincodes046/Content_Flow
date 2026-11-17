import type { NextConfig } from "next";

// The live backend. On Vercel builds it is the default proxy target, so production
// never points at localhost even when no environment variable is set.
const LIVE_API_ORIGIN = "https://content-flow-wqzd.onrender.com";
const onVercel = Boolean(process.env.VERCEL);

// When set (or on Vercel), the browser talks to this app only, and /api/* is
// proxied to the backend. That keeps the session cookie first-party. Unset in
// local development, where the browser calls the API directly.
// Render's private-network `hostport` value has no scheme (e.g. "contentflow-api:10000").
const rawApiOrigin = (process.env.CONTENT_FLOW_API_INTERNAL_URL?.trim() || (onVercel ? LIVE_API_ORIGIN : "")).replace(/\/$/, "");
const apiOrigin = rawApiOrigin && !/^https?:\/\//.test(rawApiOrigin) ? `http://${rawApiOrigin}` : rawApiOrigin;

const nextConfig: NextConfig = {
  cacheComponents: true,
  // Inlined into the browser bundle: with a proxy the browser uses relative /api URLs.
  env: { CONTENT_FLOW_DEFAULT_API_URL: apiOrigin ? "/" : "http://localhost:8000" },
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
