import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `AUTH_BYPASS` is resolved once at module load, so each case has to re-import
 * the middleware behind a fresh module registry. Stubbing the env after import
 * would change nothing.
 */
async function loadMiddleware(env: {
  bypass: "true" | "false";
  environment?: "local" | "staging" | "production";
}) {
  vi.stubEnv("NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH", env.bypass);
  vi.stubEnv("NEXT_PUBLIC_ENVIRONMENT", env.environment ?? "local");
  vi.resetModules();
  const mod = await import("@/middleware");
  return mod.middleware;
}

function request(pathname: string) {
  return new NextRequest(new URL(pathname, "http://localhost:3000"));
}

/** A pass-through response carries no redirect target; a redirect does. */
function redirectTarget(response: Response): string | null {
  const location = response.headers.get("location");
  return location === null ? null : new URL(location).pathname;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("middleware", () => {
  describe("with the development auth bypass active", () => {
    it("serves the landing page rather than redirecting it", async () => {
      // The regression this file exists for. `/` was bypassed alongside the
      // auth pages, which meant the landing page rendered for nobody in the
      // only environment it was ever loaded in.
      const middleware = await loadMiddleware({ bypass: "true" });

      expect(redirectTarget(middleware(request("/")))).toBeNull();
    });

    it.each(["/login", "/register"])("sends %s to the command center", async (pathname) => {
      const middleware = await loadMiddleware({ bypass: "true" });

      const response = middleware(request(pathname));

      expect(redirectTarget(response)).toBe("/command");
      // Temporary, so the browser stops honouring it the moment the flag is
      // turned off. A 308 would outlive the flag in the cache.
      expect(response.status).toBe(307);
    });

    it.each(["/command", "/feed", "/division", "/system"])(
      "leaves %s untouched",
      async (pathname) => {
        const middleware = await loadMiddleware({ bypass: "true" });

        expect(redirectTarget(middleware(request(pathname)))).toBeNull();
      },
    );
  });

  describe("with the bypass off", () => {
    it.each(["/", "/login", "/register", "/command"])(
      "is a no-op on %s",
      async (pathname) => {
        const middleware = await loadMiddleware({ bypass: "false" });

        expect(redirectTarget(middleware(request(pathname)))).toBeNull();
      },
    );
  });

  it("ignores the flag entirely in a production build", async () => {
    // Mirrors the backend, which refuses to boot with the flag set in
    // production. Neither half can be talked into skipping auth there.
    const middleware = await loadMiddleware({
      bypass: "true",
      environment: "production",
    });

    expect(redirectTarget(middleware(request("/login")))).toBeNull();
  });
});
