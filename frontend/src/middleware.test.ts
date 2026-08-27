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
    "lets %s through, because the alpha code grants no account session",
    (pathname) => {
      // Redirecting these away left no way to obtain a user session at all, so
      // every endpoint behind an account role was unreachable by construction —
      // including the execution wallet, which then told its own owner they were
      // not an administrator. With no password-reset flow either, an account
      // nobody can sign into can only be replaced, so /register matters too.
      expect(redirectTarget(middleware(request(pathname)))).toBeNull();
    },
  );

  it.each(["/command", "/feed", "/division", "/system"])("leaves %s untouched", (pathname) => {
    expect(redirectTarget(middleware(request(pathname)))).toBeNull();
  });
});
