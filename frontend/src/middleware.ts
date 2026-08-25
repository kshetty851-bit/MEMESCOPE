import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Temporary alpha routing.
 *
 * During private alpha the access-code homepage is the entry gate for the
 * product. It is **not** an account, though, and that distinction had a
 * consequence nobody had noticed: the alpha cookie grants no user session, so
 * while `/login` was also redirected away, no one could obtain one at all —
 * and every endpoint behind an account role was unreachable by construction.
 * The execution wallet is the only such surface, which is why it presented as
 * "available only to an account-level administrator" to the owner, who already
 * held that role.
 *
 * So `/login` is reachable again: an existing account can sign in and get a
 * session. `/register` stays closed, because the alpha code is still the thing
 * that decides who gets in — signing in is not the same as signing up.
 */
const BYPASSED_ROUTES = new Set(["/register"]);

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
