"use client";

import Link from "next/link";

import { usePaperWallet } from "@/hooks/use-paper";
import { pct, tone, usd } from "@/lib/paper";
import { cn } from "@/lib/utils";

/**
 * THE WALLET, IN ONE LINE
 *
 * Sits under the Radar so the ranking and the result of trading it are visible
 * together. That adjacency is the point: a Radar shown beside a losing wallet
 * is a more honest product than a Radar shown alone.
 *
 * Renders nothing at all when the wallet is switched off. A widget reading
 * "$1,000.00 · 0.00%" would look like a strategy that traded and broke even,
 * which is a different claim from "this is not running here".
 */
export function PaperWalletWidget() {
  const { data, isPending, isError } = usePaperWallet();

  if (isPending || isError || !data?.enabled) return null;

  const { metrics: m } = data;

  const figures: { label: string; value: string | null; tone?: string }[] = [
    { label: "Equity", value: usd(m.equity) },
    { label: "Return", value: pct(m.roi_pct), tone: tone(m.roi_pct) },
    { label: "Today", value: usd(data.pnl_today), tone: tone(data.pnl_today) },
    { label: "Open", value: String(m.open_positions) },
  ];

  return (
    <Link
      href="/wallet"
      className="group flex flex-wrap items-center gap-x-6 gap-y-3 rounded-card border border-line bg-surface/40 px-4 py-3 transition-colors hover:border-line-bright"
    >
      <span className="text-label uppercase tracking-wide text-ink-faint">
        Paper wallet
      </span>

      {figures.map((figure) => (
        <span key={figure.label} className="flex items-baseline gap-1.5">
          <span className="text-label uppercase tracking-wide text-ink-faint">
            {figure.label}
          </span>
          <span
            className={cn(
              "text-sm tabular-nums",
              figure.value === null && "text-ink-faint",
              figure.tone === "positive" && "text-safe",
              figure.tone === "negative" && "text-danger",
              (!figure.tone || figure.tone === "neutral") &&
                figure.value !== null &&
                "text-ink",
            )}
          >
            {figure.value ?? "—"}
          </span>
        </span>
      ))}

      <span className="ml-auto text-xs text-ink-faint transition-colors group-hover:text-ink">
        View wallet →
      </span>
    </Link>
  );
}
