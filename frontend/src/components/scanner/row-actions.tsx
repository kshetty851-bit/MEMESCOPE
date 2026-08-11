"use client";

import { useEffect, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * SECONDARY ACTIONS — deliberately behind a menu.
 *
 * On the card these four sat inline, at the same weight as everything else, and
 * three of them navigated away from MEMESCOPE. Demoting them is the point: the
 * scanner's primary destination is the product's own Token Intelligence page,
 * reached from the token name.
 *
 * Every external destination is marked as external in its accessible name and
 * carries `rel="noopener noreferrer"`, so nobody follows one by accident and no
 * opened tab keeps a handle on this one.
 */

interface ExternalLink {
  label: string;
  href: string;
  description: string;
}

function externalLinks(mint: string): ExternalLink[] {
  return [
    {
      label: "Pump.fun",
      href: `https://pump.fun/coin/${mint}`,
      description: "the Pump.fun chart",
    },
    {
      label: "DexScreener",
      href: `https://dexscreener.com/solana/${mint}`,
      description: "DexScreener",
    },
    {
      label: "Solscan",
      href: `https://solscan.io/token/${mint}`,
      description: "Solscan",
    },
  ];
}

export function RowActions({ mint, symbol }: { mint: string; symbol: string | null }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const wrapper = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1_400);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copyMint() {
    try {
      await navigator.clipboard.writeText(mint);
      setCopied(true);
    } catch {
      // Clipboard can be blocked by permissions policy. Say nothing rather
      // than claim a copy that did not happen.
    }
  }

  const name = symbol ?? "this token";

  return (
    <div ref={wrapper} className="relative flex justify-end">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`More actions for ${name}`}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        className={cn(
          "grid size-6 place-items-center rounded-sm text-ink-3",
          "transition-colors duration-[var(--duration-instant)]",
          "hover:bg-overlay hover:text-ink",
          open && "bg-overlay text-ink",
        )}
      >
        <span aria-hidden className="text-sm leading-none">
          ⋯
        </span>
      </button>

      {open ? (
        <div
          id={id}
          role="menu"
          aria-label={`Actions for ${name}`}
          onClick={(event) => event.stopPropagation()}
          className={cn(
            "absolute right-0 top-full z-40 mt-1 w-44 overflow-hidden",
            "rounded-md border border-line bg-overlay py-1 shadow-e3",
          )}
        >
          <button
            type="button"
            role="menuitem"
            onClick={copyMint}
            className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-xs text-ink-2 hover:bg-raised hover:text-ink"
          >
            Copy mint address
            {copied ? (
              <span className="text-up" role="status">
                Copied
              </span>
            ) : null}
          </button>

          <span
            aria-hidden
            className="my-1 block h-px bg-line-subtle"
          />

          {externalLinks(mint).map((link) => (
            <a
              key={link.label}
              role="menuitem"
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between px-2.5 py-1.5 text-xs text-ink-2 hover:bg-raised hover:text-ink"
            >
              {link.label}
              <span aria-hidden className="text-ink-4">
                ↗
              </span>
              <span className="sr-only">— opens {link.description} in a new tab</span>
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}
