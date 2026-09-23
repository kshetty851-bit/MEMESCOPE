"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useKarthikBook } from "./hooks";
import type { KarthikTrade } from "./types";

/**
 * KARTHIK'S LAB — ONE BOOK, PAPER ONLY.
 *
 * $500 on one rule, started when he asked for it and judged thirty days later.
 * It holds no wallet and has never placed an order; the real wallet is its own
 * page and its own switch.
 *
 * THREE FIGURES SIT BESIDE THE BALANCE, because the balance alone has misled
 * every reading of this lab so far:
 *
 *  - WITHOUT ITS BEST TRADE. The arm this copies made +$1,060, of which two
 *    coins were +429% and +527%; the other 177 trades made about $100 between
 *    them. A balance that is one coin is not a strategy, and the only way to
 *    see that on a page is to print the number with the coin removed.
 *  - LOWEST. A book that reached its balance by way of half its money is one
 *    nobody would still have been holding.
 *  - RUGS. On the copied arm all four landed on a single day. They cluster,
 *    and an average hides that.
 *
 * The JUDGE DATE is fixed in the backend and printed here rather than computed
 * from today, so it cannot quietly move to whenever the number looks best.
 */

function usd(value: string | number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function Figure({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="rounded-lg border border-line bg-ink/[0.02] p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div
        className={`mt-1 text-xl font-semibold tabular-nums ${
          tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""
        }`}
      >
        {value}
      </div>
      {hint ? <div className="mt-1 text-[12px] text-ink-dim">{hint}</div> : null}
    </div>
  );
}

function Row({ trade }: { trade: KarthikTrade }) {
  const pct = Number(trade.pct);
  return (
    <tr className="border-t border-line/60">
      <td className="py-1.5 pr-3 tabular-nums">
        {new Date(trade.opened_at).toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </td>
      <td className="py-1.5 pr-3 font-medium">{trade.symbol || "—"}</td>
      <td className="py-1.5 pr-3 text-right tabular-nums text-ink-dim">
        {trade.pool_usd ? usd(trade.pool_usd) : "—"}
      </td>
      <td
        className={`py-1.5 pr-3 text-right tabular-nums ${
          pct >= 0 ? "text-up" : "text-down"
        }`}
      >
        {pct >= 0 ? "+" : ""}
        {pct.toFixed(2)}%
      </td>
      <td
        className={`py-1.5 text-right tabular-nums ${
          Number(trade.pnl_usd) >= 0 ? "text-up" : "text-down"
        }`}
      >
        {usd(trade.pnl_usd)}
      </td>
    </tr>
  );
}

export function KarthikLabPage() {
  const { data, isLoading, isError, refetch } = useKarthikBook();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data) {
    return (
      <ErrorState
        title="Could not load Karthik's book"
        body="The book is a walk over the arm's own closed trades, so this failing means the page could not reach the API — not that the arm has stopped trading."
        onRetry={() => void refetch()}
      />
    );
  }

  const up = Number(data.pnl_usd) >= 0;
  const withoutBest = Number(data.without_best_usd);
  const days = Math.max(
    0,
    Math.ceil(
      (new Date(data.judge_at).getTime() - Date.now()) / 86_400_000,
    ),
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Karthik&apos;s Lab</h1>
        <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-ink-dim">
          {usd(data.capital_usd)} at {usd(data.ticket_usd)} a trade on one rule:{" "}
          <b>{data.rule}</b>. Started {day(data.started_at)}, <b>judged{" "}
          {day(data.judge_at)}</b> — {days} days to go. Paper only: this book
          holds no wallet and has never placed an order.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Figure
          label="Balance"
          value={usd(data.balance_usd)}
          tone={up ? "up" : "down"}
          hint={`${up ? "+" : ""}${usd(data.pnl_usd)} on ${usd(data.capital_usd)}`}
        />
        <Figure
          label="Without its best trade"
          value={usd(withoutBest)}
          tone={withoutBest >= 0 ? "up" : "down"}
          hint="the same book minus one coin"
        />
        <Figure
          label="Lowest it has been"
          value={usd(data.lowest_usd)}
          hint="what holding it actually felt like"
        />
        <Figure
          label="Rugs"
          value={String(data.rugs)}
          hint={`of ${data.trades} trades · ${data.wins} wins`}
        />
      </div>

      <Panel>
        <PanelHeader>
          <PanelTitle>
            Every trade{" "}
            <span className="font-normal text-ink-dim">
              &middot; sells at {data.hold_minutes} minutes
              {data.skipped ? ` · ${data.skipped} skipped for want of cash` : ""}
            </span>
          </PanelTitle>
        </PanelHeader>
        {data.trades_list.length === 0 ? (
          <EmptyState
            title="No trades yet"
            body="The rule buys a graduation over $75k whose pool is still quiet. On the arm it copies that is about sixty a day, so the first one usually arrives within the hour."
          />
        ) : (
          <div className="overflow-x-auto p-3">
            <table className="w-full text-[13px]">
              <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
                <tr>
                  <th className="py-1 pr-3 text-left font-normal">bought</th>
                  <th className="py-1 pr-3 text-left font-normal">coin</th>
                  <th className="py-1 pr-3 text-right font-normal">pool</th>
                  <th className="py-1 pr-3 text-right font-normal">result</th>
                  <th className="py-1 text-right font-normal">money</th>
                </tr>
              </thead>
              <tbody>
                {data.trades_list.map((trade) => (
                  <Row key={`${trade.symbol}-${trade.opened_at}`} trade={trade} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
        Read the second figure before the first. The arm this copies made
        +$1,060 over 179 trades — and two coins, up 429% and 527%, are almost
        all of it; the other 177 made about $100 between them, while four rugs
        all landed on one day. A balance that is one coin is a lottery ticket,
        not a strategy, and thirty days is long enough for that to show.
      </p>
    </div>
  );
}
