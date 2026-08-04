"use client";

import Link from "next/link";

import { FreshnessLabel, NoMarketData } from "@/components/ui/freshness";
import { Skeleton } from "@/components/ui/skeleton";
import { exitLabel, pct, usd } from "@/lib/paper";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PaperPosition } from "@/types/paper";

/**
 * EVERY SIMULATED TRADE
 *
 * Open and closed in one shape, because they are the same object at different
 * points in its life. Losers are never filtered out and never sorted below
 * winners — the default order is the order things happened.
 *
 * Two columns carry the honesty of the whole table:
 *
 *  - **Stop and target** are the levels fixed at entry. Showing them beside the
 *    outcome is what lets a reader check that the exit followed the rule rather
 *    than taking the result on trust.
 *  - **Peak** stops at the exit for a closed trade. A high the token printed
 *    after the position closed belongs to the token, not to the trade, and
 *    crediting it would be the most flattering error available here.
 */

function Cell({
  value,
  tone,
  className,
}: {
  value: string | null;
  tone?: "positive" | "negative" | "neutral";
  className?: string;
}) {
  return (
    <td
      className={cn(
        "py-2.5 text-right tabular-nums",
        value === null && "text-ink-faint",
        tone === "positive" && "text-safe",
        tone === "negative" && "text-danger",
        (!tone || tone === "neutral") && value !== null && "text-ink-dim",
        className,
      )}
    >
      {value ?? "—"}
    </td>
  );
}

function signTone(value: string | null): "positive" | "negative" | "neutral" {
  if (value === null) return "neutral";
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "neutral";
  return parsed > 0 ? "positive" : "negative";
}

export function PositionsTable({
  positions,
  isPending,
  emptyLabel,
}: {
  positions: PaperPosition[];
  isPending: boolean;
  emptyLabel: string;
}) {
  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-10" />
        ))}
      </div>
    );
  }

  if (positions.length === 0) {
    return <p className="text-sm text-ink-faint">{emptyLabel}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-sm">
        <thead>
          <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
            <th className="py-2 text-left font-medium">Token</th>
            <th className="py-2 text-right font-medium">Entry</th>
            <th className="py-2 text-right font-medium">Stop</th>
            <th className="py-2 text-right font-medium">Target</th>
            <th className="py-2 text-right font-medium">
              {positions[0]?.status === "closed" ? "Exit" : "Current"}
            </th>
            <th className="py-2 text-right font-medium">Result</th>
            <th className="py-2 text-right font-medium">Peak</th>
            <th className="py-2 text-right font-medium">P/L</th>
            <th className="py-2 text-right font-medium">Status</th>
            <th className="py-2 text-right font-medium">Quote</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => {
            const closed = position.status === "closed";
            return (
              <tr
                key={position.mint_address}
                className="border-b border-line/50 transition-colors hover:bg-elevated/40"
              >
                <td className="py-2.5 pr-4">
                  <Link
                    href={`/tokens/${position.mint_address}`}
                    className="text-ink hover:underline"
                  >
                    {position.symbol ?? position.name ?? `${position.mint_address.slice(0, 4)}…`}
                  </Link>
                  <span className="ml-2 text-xs text-ink-faint">
                    #{position.entry_rank} at entry
                  </span>
                </td>
                <Cell value={formatPrice(position.entry_price)} />
                <Cell value={formatPrice(position.stop_price)} />
                <Cell value={formatPrice(position.target_price)} />
                <Cell value={formatPrice(position.current_price)} />
                <Cell
                  value={pct(position.current_pct)}
                  tone={signTone(position.current_pct)}
                />
                <Cell value={pct(position.peak_pct)} tone="neutral" />
                <Cell value={usd(position.pnl_usd)} tone={signTone(position.pnl_usd)} />
                <td className="py-2.5 text-right">
                  <span
                    className={cn(
                      "rounded-chip border px-1.5 py-0.5 text-label uppercase tracking-wide",
                      closed
                        ? "border-line bg-elevated text-ink-faint"
                        : "border-plasma/25 bg-plasma/[0.07] text-plasma",
                    )}
                  >
                    {closed ? (exitLabel(position.exit_reason) ?? "Closed") : "Open"}
                  </span>
                </td>
                {/* An open position is marked to a stored reading, not to a
                    live quote. Saying when it was observed is the difference
                    between a mark and a claim. A closed trade settled at its
                    exit and shows nothing here — a finished result cannot go
                    stale. */}
                <td className="py-2.5 text-right">
                  {closed ? (
                    <span className="text-xs text-ink-faint">settled</span>
                  ) : position.current_price_at ? (
                    <FreshnessLabel capturedAt={position.current_price_at} />
                  ) : (
                    <NoMarketData />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
