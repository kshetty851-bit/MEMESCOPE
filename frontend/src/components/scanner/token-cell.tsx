"use client";

import Link from "next/link";

import { TokenAvatar } from "@/components/brand/token-avatar";
import { shortMint } from "@/lib/freshness";
import { tokenNaming } from "@/lib/radar-row";
import { cn } from "@/lib/utils";

/**
 * THE TOKEN CELL — the anchor of every row, and the fix for Phase 1's biggest
 * structural finding.
 *
 * The card this replaces offered Copy, Chart, DEX and Solscan. Three of those
 * four left the product, and none of them went to `/tokens/[mint]` — so the
 * deepest screen MEMESCOPE has was unreachable from the screen people actually
 * use. Here the token's own name is the link, it points inward, and the
 * external destinations are demoted to a secondary menu.
 *
 * A real `<Link>`, not a click handler on the row. Row-level click is a
 * convenience layered on top; this is what keyboard and screen-reader users
 * navigate with, and what middle-click and "open in new tab" act on.
 *
 * The mint is always shown. The audit found nine distinct live mints named
 * TNOS and five named SAOF — a symbol alone cannot identify a token here.
 */
export function TokenCell({
  mint,
  name,
  symbol,
  imageUrl,
  /**
   * Whether the paper wallet holds or has held this token.
   *
   * Carried over from the card, where it was a deliberate design point: it is a
   * *fact*, never a control. The strategy enters on its own published rule with
   * no manual step, so there is nothing here to click.
   */
  paperState = "not-held",
  className,
}: {
  mint: string;
  name: string | null;
  symbol: string | null;
  imageUrl?: string | null;
  paperState?: "not-held" | "open" | "closed";
  className?: string;
}) {
  const { primary, secondary } = tokenNaming({ mint_address: mint, name, symbol });

  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <TokenAvatar mint={mint} imageUrl={imageUrl} size={22} />

      <span className="flex min-w-0 flex-col leading-tight">
        <Link
          href={`/tokens/${mint}`}
          className={cn(
            "truncate text-sm font-medium text-ink",
            "transition-colors duration-[var(--duration-instant)] hover:text-accent",
            // The link's hit area covers the name only; the row handles the
            // rest. Stretching it across the cell would swallow the mint text
            // and make selecting an address impossible.
            "rounded-sm",
          )}
        >
          {primary}
          <span className="sr-only"> — open token intelligence</span>
        </Link>

        <span className="flex min-w-0 items-center gap-1.5">
          {secondary ? (
            <span className="truncate text-xs text-ink-3">{secondary}</span>
          ) : null}
          <span data-numeric className="shrink-0 text-xs text-ink-4">
            {shortMint(mint)}
          </span>
          {paperState !== "not-held" ? (
            <span
              className={cn(
                "shrink-0 rounded-sm px-1 text-label uppercase leading-none",
                paperState === "open" ? "text-accent" : "text-ink-4",
              )}
            >
              {paperState === "open" ? "Held" : "Traded"}
              <span className="sr-only">
                {paperState === "open"
                  ? " — the paper wallet holds a position in this token"
                  : " — the paper wallet has traded and closed this token"}
              </span>
            </span>
          ) : null}
        </span>
      </span>
    </span>
  );
}
