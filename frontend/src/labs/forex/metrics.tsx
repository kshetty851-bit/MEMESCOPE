"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Stat } from "@/components/ui/stat";

import {
  DASH,
  count,
  dec,
  humanize,
  minutes,
  noteText,
  pct,
  price,
  signTone,
  signedDec,
  usd,
  utc,
} from "./format";
import type { MetricsOut, TradeOut } from "./types";

const TONE = { up: "up", down: "down", flat: "flat" } as const;

function Tile({
  id,
  label,
  display,
  tone,
  hint,
  children,
}: {
  id: string;
  label: string;
  display?: string | null;
  tone?: "up" | "down" | "flat" | "default";
  hint?: string | null;
  children?: React.ReactNode;
}) {
  return (
    <div data-testid={`metric-${id}`}>
      <Stat
        boxed
        size="md"
        label={label}
        display={display}
        tone={tone}
        hint={hint ?? undefined}
        className="h-full"
      >
        {children}
      </Stat>
    </div>
  );
}

const toneOf = (v: string | number | null | undefined) => TONE[signTone(v)];

/**
 * The eighteen headline tiles. Every figure is the API's; null renders a dash
 * (or, for Sharpe, "not meaningful" with the API's own note), never a zero.
 * Costs are shown as the share of gross profit the API computed, with the
 * three components beneath — not summed here.
 */
export function MetricTiles({ metrics: m }: { metrics: MetricsOut }) {
  const sharpeNote = noteText(m.sharpe_note);
  return (
    <div
      data-testid="metric-tiles"
      className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6"
    >
      <Tile
        id="starting-balance"
        label="Starting balance"
        display={usd(m.starting_balance)}
      />
      <Tile id="ending-balance" label="Ending balance" display={usd(m.ending_balance)} />
      <Tile
        id="net-pnl"
        label="Net P&L"
        display={usd(m.net_profit, { signed: true })}
        tone={toneOf(m.net_profit)}
      />
      <Tile
        id="net-return"
        label="Net return"
        display={pct(m.net_return_pct, { signed: true })}
        tone={toneOf(m.net_return_pct)}
      />
      <Tile
        id="win-rate"
        label="Win rate"
        display={pct(m.win_rate_pct)}
        hint={`${m.wins} won · ${m.losses} lost · ${m.breakeven} flat`}
      />
      <Tile id="trades" label="Trades" display={count(m.total_trades)} />
      <Tile id="avg-win" label="Average win" display={usd(m.avg_win)} tone="up" />
      <Tile id="avg-loss" label="Average loss" display={usd(m.avg_loss)} tone="down" />
      <Tile
        id="profit-factor"
        label="Profit factor"
        display={m.profit_factor === null ? null : dec(m.profit_factor)}
      />
      <Tile
        id="expectancy-usd"
        label="Expectancy ($ / trade)"
        display={m.expectancy_usd === null ? null : usd(m.expectancy_usd, { signed: true })}
        tone={toneOf(m.expectancy_usd)}
      />
      <Tile
        id="expectancy-r"
        label="Expectancy (R / trade)"
        display={m.expectancy_r === null ? null : `${signedDec(m.expectancy_r)} R`}
        tone={toneOf(m.expectancy_r)}
        hint={noteText(m.significance_note)}
      />
      <Tile
        id="max-drawdown"
        label="Max drawdown"
        display={pct(m.max_drawdown_pct)}
        tone="down"
        hint={m.max_drawdown_usd ? usd(m.max_drawdown_usd) : null}
      />
      <Tile
        id="sharpe"
        label="Sharpe"
        display={m.sharpe === null ? "not meaningful" : dec(m.sharpe)}
        hint={
          m.sharpe === null
            ? (sharpeNote ?? "Too little data for a ratio.")
            : m.sortino === null
              ? null
              : `Sortino ${dec(m.sortino)}`
        }
      />
      <Tile
        id="loss-streak"
        label="Longest losing streak"
        display={count(m.longest_loss_streak)}
      />
      <Tile
        id="long-short"
        label="Long / short"
        display={`${count(m.long_trades)} / ${count(m.short_trades)}`}
        hint={`Net ${usd(m.long_net, { signed: true })} / ${usd(m.short_net, { signed: true })} · win ${pct(m.long_win_rate, { digits: 0 })} / ${pct(m.short_win_rate, { digits: 0 })}`}
      />
      <Tile
        id="costs"
        label="Costs, % of gross profit"
        display={pct(m.costs_pct_of_gross_profit)}
        hint={`Commission ${usd(m.total_commission)} · spread and slippage ${usd(m.total_spread_slippage)} · financing ${usd(m.total_financing)}`}
      />
      <Tile
        id="margin"
        label="Margin utilisation (max)"
        display={pct(m.max_margin_utilization_pct)}
        hint={`Average ${pct(m.avg_margin_utilization_pct)}`}
      />
      <Tile
        id="frequency"
        label="Trades per month"
        display={
          m.monthly_trade_frequency === null ? null : dec(m.monthly_trade_frequency, 1)
        }
        hint={`Average hold ${minutes(m.avg_trade_duration_minutes)}`}
      />
    </div>
  );
}

const EXIT_LABEL: Record<string, string> = {
  stop_loss: "Stop loss",
  take_profit: "Take profit",
  session_end: "Session end",
  margin_closeout: "Margin closeout",
  end_of_data: "End of data",
};

const PAGE = 25;

/** Every trade, winners and losers alike, paged client-side. */
export function TradeLog({
  trades,
  priceDecimals = 5,
}: {
  trades: TradeOut[];
  priceDecimals?: number;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(trades.length / PAGE));
  const safe = Math.min(page, pages - 1);
  const slice = trades.slice(safe * PAGE, safe * PAGE + PAGE);
  const px = (v: number | null) => <span data-numeric>{price(v, priceDecimals)}</span>;

  const columns: Column<TradeOut>[] = [
    { key: "id", header: "#", cell: (t) => <span data-numeric>{t.id}</span> },
    {
      key: "dir",
      header: "Side",
      cell: (t) => (
        <Badge tone={t.direction === "long" ? "safe" : "danger"}>{t.direction}</Badge>
      ),
    },
    {
      key: "entry_time",
      header: "Entry",
      cell: (t) => <span data-numeric>{utc(t.entry_time)}</span>,
    },
    {
      key: "exit_time",
      header: "Exit",
      cell: (t) => <span data-numeric>{utc(t.exit_time)}</span>,
    },
    { key: "entry", header: "Entry price", align: "right", cell: (t) => px(t.entry_price) },
    { key: "exit", header: "Exit price", align: "right", cell: (t) => px(t.exit_price) },
    { key: "sl", header: "SL", align: "right", cell: (t) => px(t.stop_price) },
    { key: "tp", header: "TP", align: "right", cell: (t) => px(t.take_profit_price) },
    {
      key: "dur",
      header: "Held",
      align: "right",
      cell: (t) => <span data-numeric>{minutes(t.duration_minutes)}</span>,
    },
    {
      key: "reason",
      header: "Exit reason",
      cell: (t) => (
        <span>
          {EXIT_LABEL[t.exit_reason] ?? humanize(t.exit_reason)}
          {t.ambiguous_exit ? (
            <span
              className="ml-1 text-ink-3"
              title="Stop and target were both inside one bar; resolved as the stop."
            >
              (ambiguous)
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "gross",
      header: "Gross",
      align: "right",
      cell: (t) => (
        <span data-numeric className={signText(t.gross_pnl)}>
          {usd(t.gross_pnl, { signed: true })}
        </span>
      ),
    },
    {
      key: "net",
      header: "Net",
      align: "right",
      cell: (t) => (
        <span data-numeric className={signText(t.net_pnl)}>
          {usd(t.net_pnl, { signed: true })}
        </span>
      ),
    },
    {
      key: "r",
      header: "R",
      align: "right",
      cell: (t) => (
        <span data-numeric className={signText(t.r_multiple)}>
          {t.r_multiple === null ? DASH : signedDec(t.r_multiple)}
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-2" data-testid="trade-log">
      <DataTable
        caption="Every trade in the run"
        columns={columns}
        rows={slice}
        getRowId={(t) => String(t.id)}
        stickyHeader={false}
        minWidth="1100px"
        empty={
          <p className="px-3 py-8 text-center text-sm text-ink-3">
            This run took no trades.
          </p>
        }
      />
      <div className="flex items-center justify-between gap-3 text-xs text-ink-3">
        <span data-testid="trade-range">
          {trades.length === 0
            ? "0 trades"
            : `Trades ${safe * PAGE + 1}–${safe * PAGE + slice.length} of ${trades.length}`}
        </span>
        <span className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={safe === 0}
            onClick={() => setPage(safe - 1)}
          >
            Previous
          </Button>
          <span data-numeric>
            Page {safe + 1} of {pages}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={safe >= pages - 1}
            onClick={() => setPage(safe + 1)}
          >
            Next
          </Button>
        </span>
      </div>
    </div>
  );
}

function signText(v: string | number | null | undefined): string {
  const tone = signTone(v);
  return tone === "up" ? "text-up" : tone === "down" ? "text-down" : "";
}
