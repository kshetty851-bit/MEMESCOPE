import type { ComponentType, SVGProps } from "react";

import {
  IconHq,
  IconLedger,
  IconScanner,
  IconSettings,
  IconSpark,
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
    ],
  },
  {
    label: "Strategy",
    items: [
      { href: "/wallet", label: "Paper wallet", icon: IconWallet, status: "ready" },
      // The Five-Minute Lab. Its own destination on the operator's instruction,
      // against the pattern that removed the other per-lab pages — so it is
      // listed here deliberately rather than by drift, and the test below
      // records that this one is intended.
      // Movers: the turnover filter against its own control. Named for the
      // pump.fun list it was built to anticipate, not for a result it has.
      { href: "/movers-lab", label: "Movers Lab", icon: IconWallet, status: "ready" },
      // KOL: follows wallets that were repeatedly early into winners. Listed
      // while it is still waiting for history — the page explains the wait,
      // and a lab you cannot find is a lab nobody checks.
      // Matrix: two populations x four clocks x three book shapes, laid out
      // as a grid so a difference between neighbours is attributable to the
      // one thing that differs. Its own page because the operator asked to
      // see both sections side by side.
      { href: "/matrix-lab", label: "Matrix Lab", icon: IconSpark, status: "ready" },
      { href: "/kol-lab", label: "KOL Lab", icon: IconWallet, status: "ready" },
      // A collaborator's five strategies, on five separate $1,000 paper books
      // over their own tables. Named for whose rules it runs so it can never be
      // read as another generation of the labs above it, and listed beside them
      // because that is where a reader looks for a lab.
      {
        href: "/rafiq-lab",
        label: "Rafiq Lab",
        icon: IconSpark,
        status: "ready",
        note: "Research simulation. Five supplied strategies, $1,000 each.",
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
