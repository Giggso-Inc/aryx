/** @type {import('next').NextConfig} */
const nextConfig = {
  // Server-side proxy for Shay API. The /api/* paths are now handled by
  // app/api/[...path]/route.ts which injects x-aryx-api-key before forwarding
  // to the Aryx API. Only Shay routes remain as rewrites here.
  async rewrites() {
    const isDev = process.env.NODE_ENV === "development";
    const shayTarget = isDev
      ? "http://localhost:8090"
      : process.env.SHAY_API_URL_INTERNAL || "http://shay-api:8000";
    return {
      beforeFiles: [],
      afterFiles: [
        { source: "/shay/api/v1/workspaces", destination: `${shayTarget}/api/v1/workspaces/` },
        { source: "/shay/api/v1/gg-datasources", destination: `${shayTarget}/api/v1/gg-datasources/` },
        { source: "/shay/api/:path*", destination: `${shayTarget}/api/:path*` },
        { source: "/shay/api/docs", destination: `${shayTarget}/api/docs` },
        { source: "/shay/api/openapi.json", destination: `${shayTarget}/api/openapi.json` },
      ],
      fallback: [],
    };
  },
  async redirects() {
    return [
      {
        source: "/api/shay/workspaces",
        destination: "/shay/api/v1/workspaces/",
        permanent: false,
      },
      {
        source: "/api/shay/workspaces/:workspaceId/members",
        destination: "/shay/api/v1/gg-workspaces/:workspaceId/members",
        permanent: false,
      },
      {
        source: "/api/shay/workspaces/:workspaceId/members/:path*",
        destination: "/shay/api/v1/gg-workspaces/:workspaceId/members/:path*",
        permanent: false,
      },
      {
        source: "/api/shay/gg-datasources",
        destination: "/shay/api/v1/gg-datasources/",
        permanent: false,
      },
      {
        source: "/api/shay/:path*",
        destination: "/shay/api/v1/:path*",
        permanent: false,
      },
    ];
  },

  // Make `next start` and `next build` happy in a slim Docker image.
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;
