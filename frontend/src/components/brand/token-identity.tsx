"use client";

import Link from "next/link";

import { TokenAvatar } from "@/components/brand/token-avatar";
import { shortenAddress } from "@/lib/format";
import { cn } from "@/lib/utils";

export type TokenIdentitySize = "xs" | "sm" | "md" | "lg";

const AVATAR_SIZE: Record<TokenIdentitySize, number> = {
  xs: 20,
  sm: 28,
  md: 36,
  lg: 56,
};

function displayName({
  mint,
  name,
  symbol,
}: {
  mint: string;
  name?: string | null;
  symbol?: string | null;
}) {
  return name?.trim() || symbol?.trim() || shortenAddress(mint, 6, 4);
}

export function TokenIdentity({
  mint,
  name,
  symbol,
  imageUrl,
  size = "sm",
  compact = false,
  showMint = true,
  link = "internal",
  className,
}: {
  mint: string;
  name?: string | null;
  symbol?: string | null;
  imageUrl?: string | null;
  size?: TokenIdentitySize;
  compact?: boolean;
  showMint?: boolean;
  link?: "internal" | "dexscreener" | "none";
  className?: string;
}) {
  const primary = displayName({ mint, name, symbol });
  const secondary = symbol && symbol !== primary ? symbol : null;
  const href =
    link === "internal"
      ? `/tokens/${mint}`
      : link === "dexscreener"
        ? `https://dexscreener.com/solana/${mint}`
        : null;
  const external = link === "dexscreener";

  const body = (
    <>
      <TokenAvatar mint={mint} imageUrl={imageUrl} size={AVATAR_SIZE[size]} />
      <span className="min-w-0">
        <span
          className={cn(
            "block truncate font-medium text-ink",
            size === "xs" ? "text-xs" : "text-sm",
          )}
        >
          {primary}
        </span>
        {!compact ? (
          <span className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            {secondary ? (
              <span className="truncate text-xs text-ink-3">{secondary}</span>
            ) : null}
            {showMint ? (
              <span className="font-mono text-xs text-ink-3/70" title={mint}>
                {shortenAddress(mint, 4, 4)}
              </span>
            ) : null}
          </span>
        ) : null}
      </span>
    </>
  );

  const shared = cn(
    "inline-flex min-w-0 items-center gap-2.5 text-left",
    href && "transition-colors hover:text-accent",
    className,
  );

  if (!href) {
    return <span className={shared}>{body}</span>;
  }

  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={shared}
        title={`Open ${primary} on DexScreener`}
      >
        {body}
      </a>
    );
  }

  return (
    <Link href={href} className={shared} title={`Open ${primary}`}>
      {body}
    </Link>
  );
}
