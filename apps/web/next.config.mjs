/** @type {import('next').NextConfig} */
const nextConfig = {
  // Server-side proxy: the browser hits /api/... on the Next.js host; the
  // Next server rewrites that to the FastAPI URL. In local dev we use the
  // published localhost ports; in Docker we use service names. The browser
  // never needs to know the API host — fixes CORS and keeps one bundle.
  //
  // Using afterFiles so that explicit app/api/.../route.ts handlers take
  // precedence over this catch-all rewrite (e.g. the draft-brief route
  // handler that avoids ECONNRESET on long LLM calls).
  async rewrites() {
    const isDev = process.env.NODE_ENV === "development";
    const target = isDev
      ? "http://localhost:8088"
      : process.env.ARYX_API_URL_INTERNAL || "http://api:8000";
    const shayTarget = isDev
      ? "http://localhost:8090"
      : process.env.SHAY_API_URL_INTERNAL || "http://shay-api:8000";
    return {
      beforeFiles: [],
      afterFiles: [
        { source: "/api/:path*", destination: `${target}/:path*` },
        { source: "/shay/api/:path*", destination: `${shayTarget}/api/:path*` },
        { source: "/shay/api/docs", destination: `${shayTarget}/api/docs` },
        { source: "/shay/api/openapi.json", destination: `${shayTarget}/api/openapi.json` },
      ],
      fallback: [],
    };
  },
  // Make `next start` and `next build` happy in a slim Docker image.
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;
