"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { TokenAvatar } from "@/components/brand/token-avatar";
import { CloneRiskBadge } from "@/components/decision/clone-risk-badge";
import { RowActions } from "@/components/scanner/row-actions";
import { WatchButton } from "@/components/token/watch-button";
import { Skeleton } from "@/components/ui/skeleton";
import { shortMint } from "@/lib/freshness";
import { tokenNaming } from "@/lib/radar-row";
import { cn } from "@/lib/utils";
import type { DiscoveredToken } from "@/types/api";
import type { TokenIdentity } from "@/types/identity";

/**
 * THE FILE HEADER.
 *
 * Sticky, because on a page this long the one thing a reader must never lose is
 * *which token they are looking at* — the audit found nine live mints named
 * TNOS and five named SAOF, so scrolling away from the identity is genuinely
 * dangerous here rather than merely inconvenient.
 *
 * `RowActions` is reused verbatim from the scanner rather than reimplemented.
 * The external destinations, their labels, their `rel` attributes and the
 * copy-mint behaviour are then identical on both screens by construction.
 */
export function TokenHeader({
  mint,
  token,
  identity,
  isPending,
}: {
  mint: string;
  token: DiscoveredToken | undefined;
  identity: TokenIdentity | undefined;
  isPending: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const naming = tokenNaming({
    mint_address: mint,
    name: token?.name ?? null,
    symbol: token?.symbol ?? null,
  });

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1_400);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <header className="sticky top-0 z-20 -mx-4 border-b border-line bg-canvas px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link
          href="/command"
          className={cn(
            "flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-xs text-ink-2",
            "transition-colors duration-[var(--duration-instant)]",
            "hover:bg-surface hover:text-ink",
          )}
        >
          <span aria-hidden>←</span> Scanner
        </Link>

        <span aria-hidden className="h-5 w-px shrink-0 bg-line" />

        {isPending ? (
          <Skeleton className="h-8 w-52" />
        ) : (
          <div className="flex min-w-0 items-center gap-2.5">
            <TokenAvatar mint={mint} imageUrl={token?.image_url} size={28} />
            <div className="min-w-0">
              <div className="flex min-w-0 items-baseline gap-2">
                <h1 className="truncate text-md font-medium tracking-tight text-ink">
                  {naming.primary}
                </h1>
                {naming.secondary ? (
                  <span className="truncate text-xs text-ink-3">{naming.secondary}</span>
                ) : null}
              </div>

              <div className="mt-0.5 flex min-w-0 items-center gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(mint);
                      setCopied(true);
                    } catch {
                      // Clipboard can be blocked by permissions policy. Say
                      // nothing rather than claim a copy that did not happen.
                    }
                  }}
                  className="group inline-flex items-center gap-1.5 rounded-sm text-xs text-ink-3 hover:text-ink-2"
                  aria-label={`Copy mint address ${mint}`}
                >
                  <span data-numeric>{shortMint(mint, 6, 6)}</span>
                  <span aria-hidden className="text-ink-4 group-hover:text-ink-3">
                    ⧉
                  </span>
                </button>
                {copied ? (
                  <span role="status" className="text-xs text-up">
                    Copied
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {/* Directly beside the name, because that is what it is about: a
            contested name is the one risk here a reader can act on with
            certainty. */}
        {identity ? (
          <CloneRiskBadge identity={identity} showWhy={false} className="shrink-0" />
        ) : null}

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <WatchButton mint={mint} />
          <RowActions mint={mint} symbol={token?.symbol ?? null} />
        </div>
      </div>
    </header>
  );
}
