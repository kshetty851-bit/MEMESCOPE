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
    // The browser always speaks to its own origin, and everything behind the
    // alpha gate depends on that: the session cookie is first-party, so a
    // same-origin proxy keeps it working with no CORS and no SameSite=None.
    // That is the reason this rewrite exists and the reason the fix below is a
    // proxy target rather than an absolute client URL.
    //
    // ── WHY THIS IS AN ENV VAR AND NOT A CONSTANT ─────────────────────────
    //
    // It used to be the constant `http://backend:8000` — the Docker compose
    // service name. That resolves inside the compose network and nowhere else,
    // and `www.memescope.site` is served by Vercel, where no such host exists.
    // Every `/api/*` call from the live site therefore failed DNS and returned
    // 502: the alpha gate could not unlock, so nothing behind it ever loaded.
    // It went unnoticed because the OVH container sets NEXT_PUBLIC_API_URL and
    // so calls the API absolutely, bypassing this rewrite entirely — the one
    // deployment that exercised this line was the one that did not need it.
    //
    // `API_PROXY_TARGET` is the real knob and should be set per environment.
    // The Vercel fallback is a default so a deployment cannot silently 502
    // again while somebody works out where to put a variable; setting it in
    // the Vercel project config takes precedence and is the tidier home.
    const target =
      process.env.API_PROXY_TARGET ||
      (process.env.VERCEL ? "https://api.memescope.site" : "http://backend:8000");
    return [
      {
        source: "/api/:path*",
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
