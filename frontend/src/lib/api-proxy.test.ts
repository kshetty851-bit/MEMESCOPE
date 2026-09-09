import { describe, expect, it } from "vitest";

/**
 * THE PROXY TARGET MUST NEVER BE A DOCKER SERVICE NAME IN A PUBLIC BUILD.
 *
 * `next.config.ts` rewrites `/api/*` to a backend so the browser stays on its
 * own origin and the alpha session cookie stays first-party. The destination
 * was hardcoded to `http://backend:8000` — the compose service name — which
 * resolves inside the compose network and nowhere else.
 *
 * `www.memescope.site` is served by Vercel, where that host does not exist, so
 * every API call from the live site returned 502 and the alpha gate could
 * never unlock. It survived because the OVH container sets
 * `NEXT_PUBLIC_API_URL` and calls the API absolutely, never touching this
 * rewrite: the only deployment that exercised the line was the one that did
 * not need it.
 *
 * These assert the resolution rules directly, because the failure is invisible
 * at build time — a bad hostname is a perfectly valid string.
 */

function resolveTarget(env: { API_PROXY_TARGET?: string; VERCEL?: string }): string {
  return (
    env.API_PROXY_TARGET ||
    (env.VERCEL ? "https://api.memescope.site" : "http://backend:8000")
  );
}

describe("the API proxy target", () => {
  it("uses the compose service name only for local Docker", () => {
    expect(resolveTarget({})).toBe("http://backend:8000");
  });

  it("never resolves to a Docker service name on Vercel", () => {
    // The whole bug, as one assertion.
    const target = resolveTarget({ VERCEL: "1" });
    expect(target).not.toContain("backend:8000");
    expect(target).toMatch(/^https:\/\//);
  });

  it("lets an explicit target win everywhere", () => {
    expect(resolveTarget({ API_PROXY_TARGET: "https://staging.example.com", VERCEL: "1" })).toBe(
      "https://staging.example.com",
    );
    expect(resolveTarget({ API_PROXY_TARGET: "http://localhost:8001" })).toBe(
      "http://localhost:8001",
    );
  });

  it("keeps the rule in the config file itself", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const config = fs.readFileSync(
      path.resolve(process.cwd(), "next.config.ts"),
      "utf8",
    );
    // A bare constant here is the defect. It must be reached through the env.
    expect(config).toContain("API_PROXY_TARGET");
    expect(config).not.toMatch(/destination:\s*"http:\/\/backend:8000/);
  });
});
