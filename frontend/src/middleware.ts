import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Temporary alpha routing.
 *
 * During private alpha, the access-code homepage is the only entry gate. The
 * real auth pages remain in the tree for later, but they are not part of the
 * current product flow and should not appear after unlocking alpha access.
 */
const BYPASSED_ROUTES = new Set(["/login", "/register"]);

export function middleware(request: NextRequest) {
  if (BYPASSED_ROUTES.has(request.nextUrl.pathname)) {
    const target = new URL("/", request.url);
    // Temporary, deliberately: a permanent redirect would be cached by the
    // browser after the real auth flow replaces the alpha access gate.
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
