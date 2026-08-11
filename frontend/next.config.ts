import type { NextConfig } from "next";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // `standalone` emits a minimal server bundle, which keeps the runtime image small.
  output: "standalone",
  eslint: {
    dirs: ["src"],
  },
  typescript: {
    // Never ship a build that does not typecheck.
    ignoreBuildErrors: false,
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    // The browser always speaks to its own origin. In local Docker this keeps
    // the backend private to the compose network while allowing a temporary
    // HTTPS tunnel to expose one web entry point, including WebSocket upgrades.
    return [
      {
        source: "/api/:path*",
        destination: "http://backend:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
