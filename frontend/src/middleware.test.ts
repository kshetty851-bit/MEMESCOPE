import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "@/middleware";

function request(pathname: string) {
  return new NextRequest(new URL(pathname, "http://localhost:3000"));
}

/** A pass-through response carries no redirect target; a redirect does. */
function redirectTarget(response: Response): string | null {
  const location = response.headers.get("location");
  return location === null ? null : new URL(location).pathname;
}

describe("middleware", () => {
  it("serves the alpha landing page rather than redirecting it", () => {
    expect(redirectTarget(middleware(request("/")))).toBeNull();
  });

  it.each(["/login", "/register", "/login?auth=manual"])(
    "sends %s to the alpha landing page",
    (pathname) => {
      const response = middleware(request(pathname));

      expect(redirectTarget(response)).toBe("/");
      // Temporary, so the browser stops honouring it the moment the real auth
      // flow replaces the alpha gate. A 308 would outlive the product decision.
      expect(response.status).toBe(307);
    },
  );

  it.each(["/command", "/feed", "/division", "/system"])("leaves %s untouched", (pathname) => {
    expect(redirectTarget(middleware(request(pathname)))).toBeNull();
  });
});
