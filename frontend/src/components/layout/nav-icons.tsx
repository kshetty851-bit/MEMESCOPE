import type { SVGProps } from "react";

/**
 * Navigation icons.
 *
 * Hand-drawn on a 24 grid at 1.5 stroke rather than pulled from an icon
 * package: nine glyphs do not justify a dependency, and a set drawn to one
 * spec stays consistent in a way a mixed set never does.
 *
 * No emoji. The Track Record's ⭐/🏆/🚀/👑 tier badges are the reason that rule
 * exists — emoji render as full-colour illustrations that ignore the palette,
 * change shape per platform, and read as a casino.
 *
 * Every icon is `aria-hidden`. They sit beside real text labels in the rail,
 * and in the collapsed rail the accessible name comes from the link itself.
 */

function Base(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={16}
      height={16}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    />
  );
}

/** Scanner — an aperture sweeping a field. Echoes the MEMESCOPE mark. */
export function IconScanner(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3" />
    </Base>
  );
}

/** Trending — a rising trace. */
export function IconTrend(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M3 16.5l5-5 3.5 3.5L21 6" />
      <path d="M21 11V6h-5" />
    </Base>
  );
}

/** New launches — emergence. */
export function IconSpark(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 3v5M12 16v5M4.5 12h5M14.5 12h5" />
      <path d="M6.7 6.7l2.6 2.6M14.7 14.7l2.6 2.6M17.3 6.7l-2.6 2.6M9.3 14.7l-2.6 2.6" />
    </Base>
  );
}

/** Track record — an append-only ledger. */
export function IconLedger(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="4" y="3.5" width="16" height="17" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </Base>
  );
}

/** Watchlist — a bookmark, not a star. Stars read as ratings. */
export function IconBookmark(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M6.5 3.5h11a1 1 0 011 1v16l-6.5-4-6.5 4v-16a1 1 0 011-1z" />
    </Base>
  );
}

/** Paper wallet. */
export function IconWallet(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10h18" />
      <circle cx="16.5" cy="14.5" r="1.25" />
    </Base>
  );
}

export function IconSettings(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 14.5a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-1.8-.3 1.6 1.6 0 00-1 1.5v.2a2 2 0 11-4 0v-.1a1.6 1.6 0 00-1-1.5 1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 00-1.5-1H3a2 2 0 110-4h.1a1.6 1.6 0 001.5-1 1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H10a1.6 1.6 0 001-1.5V3a2 2 0 114 0v.1a1.6 1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V10a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z" />
    </Base>
  );
}

/* --- Shell chrome --------------------------------------------------------- */

export function IconMenu(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Base>
  );
}

export function IconSearch(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </Base>
  );
}

/** Rail collapse. Points the way the rail will move. */
export function IconCollapse(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M14 7l-5 5 5 5" />
      <path d="M19 4v16" />
    </Base>
  );
}

export function IconExpand(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M10 7l5 5-5 5" />
      <path d="M5 4v16" />
    </Base>
  );
}

export function IconExit(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3" />
      <path d="M10 8l-4 4 4 4M6 12h9" />
    </Base>
  );
}

/**
 * HQ.
 *
 * A room seen in isometric — the same projection the screen itself uses, so
 * the glyph previews the thing it links to. Drawn as a floor diamond with two
 * standing figures rather than a building: HQ is about the people, and a tower
 * would read as "company info".
 */
export function IconHq(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 4l8 5-8 5-8-5 8-5z" />
      <path d="M9.5 11.5v3M14.5 11.5v3" />
      <path d="M4 9v6l8 5 8-5V9" />
    </Base>
  );
}

/**
 * STRATEGY LAB.
 *
 * A flask, drawn as an outline with a fill line partway up. Deliberately not a
 * wallet, a chart or a coin: every one of those would file research beside the
 * things it must never be confused with. Laboratory glassware says "experiment"
 * without saying "money".
 */
export function IconFlask(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M10 3h4" />
      <path d="M10.5 3v6.2L5.4 17.4A1.6 1.6 0 006.8 20h10.4a1.6 1.6 0 001.4-2.6L13.5 9.2V3" />
      <path d="M8.2 14h7.6" />
    </Base>
  );
}
