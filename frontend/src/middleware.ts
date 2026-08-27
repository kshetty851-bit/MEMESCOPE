import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Temporary alpha routing.
 *
 * The alpha access code is the product's entry gate. It is a cookie, not an
 * account, and that distinction had a consequence nobody had noticed: it grants
 * no user session, so while `/login` and `/register` were both redirected away,
 * there was no way to obtain one at all — and every endpoint behind an account
 * role was unreachable by construction. The execution wallet is the only such
 * surface, which is why it told its own owner they were not an administrator.
 *
 * There is also no password-reset flow, so an account whose password nobody
 * knows cannot be recovered — only replaced. Reaching `/login` alone was
 * therefore not enough to fix anything.
 *
 * Both routes are reachable again. What that widens is small and deliberate:
 * registration still requires the alpha code to reach the site at all, and a new
 * account is created with the ordinary `user` role, which grants nothing beyond
 * what the alpha cookie already did. The administrator role is grantable only in
 * the database, and it remains the thing that guards the wallet.
 */
export function middleware(_request: NextRequest) {
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
