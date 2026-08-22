"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * Which paper wallet is being read.
 *
 * Two independent experiments, and the switch is a **link, not a tab**. Routes
 * rather than client state because the two wallets share nothing: no capital,
 * no positions, no history and no cache entry. A tab holding both in one
 * component is one refactor away from a page that sums them, which is the one
 * thing neither wallet's figures could survive.
 *
 * It also means each wallet has an address. "Look at Karthik" is a URL.
 */

const WALLETS = [
  { href: "/wallet", label: "Original" },
  { href: "/wallet/karthik", label: "Karthik" },
] as const;

export function WalletSwitch() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Paper wallet"
      className="inline-flex items-center gap-1 rounded-md border border-line bg-surface p-1"
    >
      {WALLETS.map((wallet) => {
        // Exact match, not prefix: `/wallet/karthik` starts with `/wallet`, so a
        // prefix test would light up both.
        const active = pathname === wallet.href;
        return (
          <Link
            key={wallet.href}
            href={wallet.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-raised text-ink"
                : "text-ink-3 hover:bg-raised/50 hover:text-ink-2",
            )}
          >
            {wallet.label}
          </Link>
        );
      })}
    </nav>
  );
}
