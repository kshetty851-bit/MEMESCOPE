"use client";

import { TokenIdentity } from "@/components/brand/token-identity";
import { Skeleton } from "@/components/ui/skeleton";
import { exitLabel, hours, pct, usd } from "@/lib/paper";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PaperAuditEntry } from "@/types/paper";

/**
 * THE PERMANENT RECORD
 *
 * Every completed trade, written once at the moment it closed and never
 * rewritten. This table renders what was stored; it computes nothing.
 *
 * That distinction is the point. The wallet's summary above is derived fresh
 * from the positions on every read, but the market cap and pool depth beside
 * each trade here are the ones observed at the time — the snapshots that
 * carried them are pruned, so a figure re-derived later would eventually be
 * "unavailable" for the oldest trades first.
 *
 * **Gross and net sit side by side.** Where the venue reported no depth at one
 * end, net is blank with its reason rather than zero: a half-costed round trip
 * is worse than an uncosted one, because it looks complete.
 */

function Cell({
  value,
  tone,
  hint,
}: {
  value: string | null;
  tone?: "positive" | "negative" | "neutral";
  hint?: string | null;
}) {
  return (
    <td
      className={cn(
        "py-2.5 text-right tabular-nums",
        value === null && "text-ink-3",
        tone === "positive" && "text-up",
        tone === "negative" && "text-down",
        (!tone || tone === "neutral") && value !== null && "text-ink-2",
      )}
      title={hint ?? undefined}
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

function marketCap(value: string | null): string | null {
  if (value === null) return null;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return null;
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(2)}M`;
  if (amount >= 1_000) return `$${(amount / 1_000).toFixed(1)}K`;
  return `$${amount.toFixed(0)}`;
}

function modelLabel(value: string | null): string {
  if (value === "jupiter_quote_v2") return "Jupiter";
  if (value === "legacy_constant_product_v1" || value === null) return "Legacy";
  return value;
}

export function AuditLog({
  items,
  total,
  disclosure,
  isPending,
}: {
  items: PaperAuditEntry[];
  total: number;
  disclosure: string;
  isPending: boolean;
}) {
  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-10" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-sm text-ink-3">
        Nothing has closed yet. A trade enters this record the moment its
        trailing stop triggers, and never leaves it.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1080px] text-sm">
          <thead>
            <tr className="border-b border-line text-label uppercase tracking-wide text-ink-3">
              <th className="py-2 text-left font-medium">Token</th>
              <th className="py-2 text-right font-medium">Entry</th>
              <th className="py-2 text-right font-medium">Entry mcap</th>
              <th className="py-2 text-right font-medium">Exit</th>
              <th className="py-2 text-right font-medium">Exit mcap</th>
              <th className="py-2 text-right font-medium">Held</th>
              <th className="py-2 text-right font-medium">Gross</th>
              <th className="py-2 text-right font-medium">Fees</th>
              <th className="py-2 text-right font-medium">Slippage</th>
              <th className="py-2 text-right font-medium">Net</th>
              <th className="py-2 text-right font-medium">Execution</th>
              <th className="py-2 text-right font-medium">Exit rule</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr
                key={`${row.mint_address}-${row.exit_at}`}
                className="border-b border-line/50 transition-colors hover:bg-raised/40"
              >
                <td className="py-2.5 pr-4">
                  <TokenIdentity
                    mint={row.mint_address}
                    symbol={row.symbol}
                    imageUrl={row.image_url}
                    size="xs"
                    compact
                  />
                  <span className="ml-2 text-xs text-ink-3">
                    v{row.strategy_version}
                  </span>
                </td>
                <Cell value={formatPrice(row.entry_price)} />
                <Cell value={marketCap(row.entry_market_cap)} />
                <Cell value={formatPrice(row.exit_price)} />
                <Cell value={marketCap(row.exit_market_cap)} />
                <Cell value={hours(row.hold_hours)} />
                <Cell
                  value={pct(row.gross_return_pct)}
                  tone={signTone(row.gross_return_pct)}
                />
                {/* Fee and impact are charged at both ends, against the depth
                    observed at each. The exit costs more when the position grew
                    — cost is progressive, not flat. */}
                <Cell value={usd(row.fee_usd)} hint={row.cost_unavailable_reason} />
                <Cell value={usd(row.slippage_usd)} hint={row.cost_unavailable_reason} />
                <Cell
                  value={pct(row.net_return_pct)}
                  tone={signTone(row.net_return_pct)}
                  hint={row.cost_unavailable_reason}
                />
                <td
                  className="py-2.5 text-right text-xs text-ink-3"
                  title={
                    row.execution_fallback_reason ??
                    row.exit_execution_route ??
                    row.entry_execution_route ??
                    undefined
                  }
                >
                  {modelLabel(row.execution_model_version)}
                </td>
                <td className="py-2.5 text-right text-xs text-ink-3">
                  {exitLabel(row.exit_reason) ?? row.exit_reason}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length < total ? (
        <p className="text-xs text-ink-3">
          Showing {items.length} of {total} recorded trades.
        </p>
      ) : null}
      <p className="text-xs leading-relaxed text-ink-3">{disclosure}</p>
    </div>
  );
}
