import type { ComponentType, SVGProps } from "react";

import {
  IconHq,
  IconLedger,
  IconSettings,
  IconSpark,
} from "@/components/layout/nav-icons";

/**
 * THE NAVIGATION MAP.
 *
 * Data, not markup, so the rail, the mobile drawer and the topbar's section
 * label all read one source and cannot disagree about what exists.
 *
 * The `status` field is the important part. Three destinations — Trending, New
 * Launches and Watchlist — are backed by live API endpoints
 * (`/market/trending`, `/tokens/latest`, `/watchlists`) but have no screen yet.
 * They are listed so the information architecture is settled now and the shell
 * does not need rebuilding when they land, and they are rendered as plainly
 * unavailable rather than as links.
 *
 * They are **not** links to empty pages. A nav item that navigates to a blank
 * screen is a worse lie than one that says "not yet": the first wastes a click
 * and teaches the user the product is broken, the second sets an expectation.
 */

export type NavStatus = "ready" | "planned";

export interface NavItem {
  /** Route path. Present on `ready` items only. */
  href?: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  status: NavStatus;
  /** Why it is not available yet. Shown to the user, so keep it plain. */
  note?: string;
}

export interface NavGroup {
  /** Section heading in the expanded rail. */
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Strategy",
    items: [
      // Per-lab pages are removed by default; the ones below are listed
      // deliberately rather than by drift, and hq.test.tsx records that.
      //
      // The Movers, Matrix and KOL Labs held that exception until 2026-09-10,
      // the Breakout Lab until 2026-09-12 and the Dex Lab until 2026-09-13 —
      // each deleted on the operator's instruction, code and records together.
      // The Rafiq, Forex and Momentum Labs, the Robinhood Chain recorder and
      // the paper wallet went the same way on 2026-09-25.
      // Rafiqv2: a collaborator's six books on one engine, with their own
      // tables and flag. Paper only.
      {
        href: "/rafiqv2-lab",
        label: "Rafiqv2 Lab",
        icon: IconSpark,
        status: "ready",
        note: "Research simulation. Six books on one engine, $1,000 each.",
      },
      // pump.fun launches climbing the bonding curve. Watch only, like the
      // NSE tracker below — no book, nothing ranked — so it is named for what
      // it records rather than for a strategy it does not have.
      {
        href: "/graduation-lab",
        label: "Graduation Lab",
        icon: IconSpark,
        status: "ready",
        note: "Watch only. pump.fun curves into graduation; no book.",
      },
      // Karthik's own book: his money on one rule, judged thirty days after it
      // started. Its own destination rather than a ninth panel on the
      // graduation board, so that his money's record and a pre-registered
      // experiment cannot have their dates confused with one another.
      {
        href: "/karthik-lab",
        label: "Karthik's Lab",
        icon: IconSpark,
        status: "ready",
        note: "Paper only. $400 at $200 a trade on the quiet rule, judged 23 Oct.",
      },
      // Indian equities, not Solana, and the only destination here with no
      // book at all — it watches and records. Listed beside the labs because
      // that is where a reader looks for one, and named for the market so it
      // cannot be confused with the Solana Breakout Lab above it.
      {
        href: "/breakouts",
        label: "NSE Breakouts",
        icon: IconSpark,
        status: "ready",
        note: "Watch only. NSE equities into daily resistance; no book.",
      },
    ],
  },
  {
    label: "Execution",
    items: [
      {
        href: "/real-wallet",
        label: "Real wallet",
        icon: IconLedger,
        status: "ready",
      },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/hq", label: "HQ", icon: IconHq, status: "ready" },
    ],
  },
];

export const NAV_FOOTER: NavItem[] = [
  { href: "/settings", label: "Settings", icon: IconSettings, status: "ready" },
];

const ALL_ITEMS = [...NAV_GROUPS.flatMap((group) => group.items), ...NAV_FOOTER];

/**
 * Which nav item owns a pathname.
 *
 * Longest match wins so `/tokens/So11…` does not light up an unrelated prefix,
 * and so a future `/record/archive` still marks Track Record as current.
 */
export function activeItem(pathname: string): NavItem | null {
  let best: NavItem | null = null;
  for (const item of ALL_ITEMS) {
    if (!item.href) continue;
    const matches = pathname === item.href || pathname.startsWith(`${item.href}/`);
    if (matches && (!best?.href || item.href.length > best.href.length)) {
      best = item;
    }
  }
  return best;
}

/**
 * What the topbar calls the current screen.
 *
 * Token Intelligence is deliberately absent from the rail — it is reached from
 * a token, not from navigation — so it is named here instead. Without this the
 * topbar would show no section at all on the deepest screen in the product.
 */
export function sectionLabel(pathname: string): string {
  if (pathname === "/tokens" || pathname.startsWith("/tokens/")) {
    return "Token intelligence";
  }
  return activeItem(pathname)?.label ?? "MEMESCOPE";
}
