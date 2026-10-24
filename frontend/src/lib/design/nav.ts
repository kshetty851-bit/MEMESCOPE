import type { ComponentType, SVGProps } from "react";

import {
  IconHq,
  IconLedger,
  IconNews,
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
    // The live crypto newspaper, the first page after sign-in (Karthik, 2026-10-17).
    label: "Newsroom",
    items: [{ href: "/home", label: "Home", icon: IconNews, status: "ready" }],
  },
  {
    // Everything MEMESCOPE has seen, measured and traded (Karthik, 2026-10-22).
    label: "Record",
    items: [{ href: "/track-record", label: "Track record", icon: IconLedger, status: "ready" }],
  },
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
      // the paper wallet went the same way on 2026-09-25; Rafiqv2 and NSE
      // Breakouts on 2026-10-01.
      // pump.fun launches climbing the bonding curve. Watch only, like the
      // NSE tracker below — no book, nothing ranked — so it is named for what
      // it records rather than for a strategy it does not have.
      // Pre-trade AI Lab: off the menu 2026-10-24 (Karthik: "fix all 3") -- its
      // container is stopped (0 trades in 4 weeks); the page and its data stay.
      // Karthik's own book: his money on one rule, judged thirty days after it
      // started. Its own destination rather than a ninth panel on the
      // graduation board, so that his money's record and a pre-registered
      // experiment cannot have their dates confused with one another.
      {
        href: "/karthik-lab",
        label: "Karthik's Lab",
        icon: IconSpark,
        status: "ready",
        note: "Paper only. $300 at $50 a trade on $40k+ quiet pools (short names under $50k).",
      },
      {
        href: "/pump-catcher-lab",
        label: "Pump Catcher Lab",
        icon: IconSpark,
        status: "ready",
        note: "Paper only. Karthik Lab's coins and rules, sold at +30% or 10 minutes instead of 5.",
      },
      // Karthik, 2026-10-05: small pools at every size, and ten user wallets
      // sharing the same coins.
      {
        href: "/pool-lab",
        label: "Pool Lab",
        icon: IconSpark,
        status: "ready",
        note: "Paper only. $10k pools at 10x sizes; $50k pools on ten wallets.",
      },
      // Karthik, 2026-10-10: does paying DexScreener (profile, boosts) pay?
      {
        href: "/boost-lab",
        label: "Boost Lab",
        icon: IconSpark,
        status: "ready",
        note: "Paper only. Coins with a paid DexScreener profile or boosts, sold at 4 minutes.",
      },
      {
        href: "/longwatch-lab",
        label: "Long-watch Lab",
        icon: IconSpark,
        status: "ready",
        note: "Paper only. Watches every graduation for 48 h; Second Wind book, $25 a buy from $500 (Runner off).",
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
      // Karthik, 2026-10-14: the main wallet's days and trades since the 50-50
      // start; under the real wallet ("move partners wallet below real wallet").
      {
        href: "/partners-lab",
        label: "Partners Wallet",
        icon: IconLedger,
        status: "ready",
        note: "Real money. Karthik & Rafiq's main wallet: every day's P&L and %, every trade with its strategy.",
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
