import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { AUTH_BYPASS } from "@/lib/env";

/**
 * Development routing bypass.
 *
 * While `NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH` is on (and the build is not
 * production), the sign-in flow is taken out of the user's path: both auth
 * pages send the visitor straight to the Command Center, because a credential
 * form that grants nothing is a control that lies about what it does.
 *
 * `/` is deliberately NOT bypassed. It was, until Phase 5A, and the cost was
 * that the landing page - the product's front door - rendered for nobody in the
 * only environment anyone was running. Skipping the login screen is a
 * development convenience; skipping the landing page hides a shipped surface
 * and lets it rot unnoticed. The two are separate concerns and only one of them
 * belongs behind this flag.
 *
 * One control point rather than a redirect scattered through the auth pages, so
 * turning the flag off restores the original flow exactly - nothing is deleted
 * and no page keeps a conditional it would otherwise not need.
 *
 * With the flag off this middleware is a no-op on every request, leaving the
 * production path untouched.
 */
const BYPASSED_ROUTES = new Set(["/login", "/register"]);

const DASHBOARD = "/command";

export function middleware(request: NextRequest) {
  if (!AUTH_BYPASS) {
    return NextResponse.next();
  }

  if (BYPASSED_ROUTES.has(request.nextUrl.pathname)) {
    const target = new URL(DASHBOARD, request.url);
    // Temporary, deliberately: a permanent redirect would be cached by the
    // browser and would keep firing after the flag is turned back off.
    return NextResponse.redirect(target, 307);
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Everything except Next internals, the API proxy, and static files. Matching
   * assets would put this on the hot path for every image and chunk for no
   * reason.
   */
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
