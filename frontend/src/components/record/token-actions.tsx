"use client";

import Link from "next/link";
import { useState } from "react";

/**
 * TOKEN ACTIONS
 *
 * The one-click paths out of a row: copy the address, open the chart, open the
 * explorer, open the token page.
 *
 * This exists because the record was previously a dead end — a trader could
 * read that something ran 36× and had no way to go look at it. The mint was
 * displayed truncated, so it could not even be selected by hand.
 *
 * Every destination is an external site the reader chooses to visit; none is
 * fetched or embedded, so nothing here sends data anywhere on its own.
 */

function IconLink({
  href,
  title,
  children,
}: {
  href: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={title}
      aria-label={title}
      className="rounded px-1.5 py-1 text-ink-faint transition-colors hover:bg-elevated hover:text-ink"
      onClick={(event) => event.stopPropagation()}
    >
      {children}
    </a>
  );
}

export function TokenActions({ mint }: { mint: string }) {
  const [copied, setCopied] = useState(false);

  async function copy(event: React.MouseEvent) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(mint);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard can be blocked by permissions. Say nothing rather than
      // claim a copy that did not happen.
      setCopied(false);
    }
  }

  return (
    <div className="flex items-center gap-0.5">
      <button
        type="button"
        onClick={copy}
        title={copied ? "Copied" : "Copy mint address"}
        aria-label="Copy mint address"
        className="rounded px-1.5 py-1 text-ink-faint transition-colors hover:bg-elevated hover:text-ink"
      >
        {copied ? "✓" : "⧉"}
      </button>
      <IconLink
        href={`https://dexscreener.com/solana/${mint}`}
        title="Open chart on DexScreener"
      >
        ↗
      </IconLink>
      <IconLink href={`https://solscan.io/token/${mint}`} title="Open on Solscan">
        ⎋
      </IconLink>
      <Link
        href={`/tokens/${mint}`}
        title="Open token page"
        aria-label="Open token page"
        className="rounded px-1.5 py-1 text-ink-faint transition-colors hover:bg-elevated hover:text-ink"
        onClick={(event) => event.stopPropagation()}
      >
        →
      </Link>
    </div>
  );
}
