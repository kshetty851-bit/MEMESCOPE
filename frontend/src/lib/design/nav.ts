import type { ComponentType, SVGProps } from "react";

import {
  IconBookmark,
  IconHq,
  IconLedger,
  IconScanner,
  IconSettings,
  IconSpark,
  IconTrend,
  IconWallet,
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
    label: "Markets",
    items: [
      {
        href: "/command",
        label: "Scanner",
        icon: IconScanner,
        status: "ready",
      },
      {
        href: "/trending",
        label: "Trending",
        icon: IconTrend,
        status: "ready",
      },
      {
        href: "/launches",
        label: "New launches",
        icon: IconSpark,
        status: "ready",
      },
    ],
  },
  {
    label: "Intelligence",
    items: [
      {
        href: "/record",
        label: "Track record",
        icon: IconLedger,
        status: "ready",
      },
      {
        href: "/watchlist",
        label: "Watchlist",
        icon: IconBookmark,
        status: "ready",
      },
    ],
  },
  {
    label: "Strategy",
    items: [
      { href: "/wallet", label: "Paper wallet", icon: IconWallet, status: "ready" },
      // The Arena sits beside the wallet because that is where a reader looks
      // for it — but it is a research simulation, and the page says so above
      // the fold. Its equity is not the Paper Wallet's equity.
      {
        href: "/strategy-lab/forward-arena",
        label: "Forward Arena",
        icon: IconSpark,
        status: "ready",
      },
    ],
  },
  {
    label: "Operations",
    items: [
      // HQ renders system state as an organisation. Its own group rather than
      // an entry under Strategy: it observes every subsystem, so filing it
      // beneath one of them would misdescribe what it shows.
      { href: "/hq", label: "HQ", icon: IconHq, status: "ready" },
    ],
  },
];

/** Pinned to the bottom of the rail, away from the working set. */
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
