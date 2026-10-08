"use client";

import { Num } from "@/components/ui/num";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Stat } from "@/components/ui/stat";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";

import { EXIT_LABEL, dec, pct, signTone, signedDec, usd, when } from "./format";
import type { MetricsOut, OpenPositionOut, TradeOut } from "./types";

/** The seven headline figures, identical on the live book and a backtest. */
export function MetricsStats({ metrics }: { metrics: MetricsOut }) {
  return (
    <div
      className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7"
      data-testid="metrics-stats"
    >
      <Stat
        boxed
        label="Net P&L"
        value={metrics.net_pnl}
        display={usd(metrics.net_pnl, { signed: true })}
        signed
        hint={pct(metrics.return_pct, { signed: true }) + " return"}
      />
      <Stat
        boxed
        label="Win rate"
        value={metrics.win_rate}
        display={pct(metrics.win_rate, { digits: 1 })}
        hint={`${metrics.wins}W / ${metrics.losses}L`}
      />
      <Stat
        boxed
        label="Profit factor"
        value={metrics.profit_factor}
        display={dec(metrics.profit_factor)}
        hint={metrics.profit_factor === null ? "No losing trade yet" : undefined}
      />
      <Stat
        boxed
        label="Expectancy"
        value={metrics.expectancy}
        display={usd(metrics.expectancy, { signed: true })}
        signed
        hint="Per trade"
      />
      <Stat
        boxed
        label="Max drawdown"
        value={metrics.max_drawdown_pct}
        display={pct(metrics.max_drawdown_pct)}
      />
      <Stat boxed label="Trades" value={metrics.trades} display={String(metrics.trades)} />
      <Stat
        boxed
        label="Ending equity"
        value={metrics.ending_equity}
        display={usd(metrics.ending_equity)}
      />
    </div>
  );
}

/** LONG against SHORT, one column each. Same metrics as the headline row. */
export function SideTable({ long, short }: { long: MetricsOut; short: MetricsOut }) {
  const rows: Array<{
    label: string;
    cell: (m: MetricsOut) => React.ReactNode;
  }> = [
    { label: "Trades", cell: (m) => <Num value={m.trades} display={String(m.trades)} /> },
    { label: "Wins", cell: (m) => <Num value={m.wins} display={String(m.wins)} /> },
    { label: "Losses", cell: (m) => <Num value={m.losses} display={String(m.losses)} /> },
    {
      label: "Win rate",
      cell: (m) => <Num value={m.win_rate} display={pct(m.win_rate, { digits: 1 })} />,
    },
    {
      label: "Net P&L",
      cell: (m) => (
        <Num value={m.net_pnl} display={usd(m.net_pnl, { signed: true })} signed />
      ),
    },
    {
      label: "Return",
      cell: (m) => (
        <Num value={m.return_pct} display={pct(m.return_pct, { signed: true })} signed />
      ),
    },
    {
      label: "Profit factor",
      cell: (m) => <Num value={m.profit_factor} display={dec(m.profit_factor)} />,
    },
    {
      label: "Expectancy",
      cell: (m) => (
        <Num value={m.expectancy} display={usd(m.expectancy, { signed: true })} signed />
      ),
    },
    {
      label: "Max drawdown",
      cell: (m) => <Num value={m.max_drawdown_pct} display={pct(m.max_drawdown_pct)} />,
    },
  ];

  return (
    <div className="overflow-x-auto rounded-md border border-line" data-testid="side-table">
      <table className="w-full text-sm tabular-nums">
        <caption className="sr-only">LONG calls compared with SHORT calls</caption>
        <thead>
          <tr className="bg-sunken text-label uppercase text-ink-3">
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Metric
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium text-up">
              Long
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium text-down">
              Short
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t border-line-subtle bg-surface">
              <th scope="row" className="px-3 py-1.5 text-left font-normal text-ink-3">
                {row.label}
              </th>
              <td className="px-3 py-1.5 text-right" data-side="long">
                {row.cell(long)}
              </td>
              <td className="px-3 py-1.5 text-right" data-side="short">
                {row.cell(short)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SideBadge({ side }: { side: "long" | "short" }) {
  return <Badge tone={side === "long" ? "safe" : "danger"}>{side.toUpperCase()}</Badge>;
}

export function TradesTable({ trades, caption }: { trades: TradeOut[]; caption: string }) {
  const columns: Column<TradeOut>[] = [
    { key: "side", header: "Side", cell: (t) => <SideBadge side={t.side} /> },
    {
      key: "entry_at",
      header: "Entry time",
      cell: (t) => <span data-numeric>{when(t.entry_at)}</span>,
    },
    {
      key: "entry_price",
      header: "Entry",
      align: "right",
      cell: (t) => <span data-numeric>{usd(t.entry_price)}</span>,
    },
    {
      key: "exit_at",
      header: "Exit time",
      cell: (t) => <span data-numeric>{when(t.exit_at)}</span>,
    },
    {
      key: "exit_price",
      header: "Exit",
      align: "right",
      cell: (t) => <span data-numeric>{usd(t.exit_price)}</span>,
    },
    {
      key: "reason",
      header: "Exit reason",
      cell: (t) => EXIT_LABEL[t.exit_reason] ?? t.exit_reason,
    },
    {
      key: "fees",
      header: "Fees",
      align: "right",
      cell: (t) => <span data-numeric>{usd(t.fees)}</span>,
    },
    {
      key: "pnl",
      header: "P&L",
      align: "right",
      cell: (t) => <Num value={t.pnl} display={usd(t.pnl, { signed: true })} signed />,
    },
    {
      key: "r",
      header: "R",
      align: "right",
      cell: (t) => (
        <Num
          value={t.r_multiple}
          display={`${signedDec(t.r_multiple)}R`}
          tone={signTone(t.r_multiple)}
        />
      ),
    },
  ];

  return (
    <DataTable
      caption={caption}
      columns={columns}
      rows={trades}
      getRowId={(t) => `${t.side}-${t.entry_at}-${t.exit_at}`}
      minWidth="52rem"
      maxHeight="28rem"
      empty={
        <p className="px-3 py-10 text-center text-sm text-ink-3">No closed paper trades.</p>
      }
    />
  );
}

export function OpenPositionCard({ position }: { position: OpenPositionOut | null }) {
  return (
    <Panel density="compact" data-testid="open-position">
      <PanelHeader className="mb-3">
        <PanelTitle>Open paper position</PanelTitle>
        {position ? <SideBadge side={position.side} /> : null}
      </PanelHeader>
      {position ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Opened", when(position.entry_at)],
              ["Entry", usd(position.entry_price)],
              ["TP", usd(position.take_profit)],
              ["SL", usd(position.stop_loss)],
              ["Quantity", position.quantity],
              ["Notional", usd(position.notional)],
              ["Mark", usd(position.mark_price)],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="flex flex-col gap-0.5">
              <dt className="text-label uppercase text-ink-3">{label}</dt>
              <dd data-numeric>{value}</dd>
            </div>
          ))}
          <div className="flex flex-col gap-0.5">
            <dt className="text-label uppercase text-ink-3">Unrealised P&L</dt>
            <dd>
              <Num
                value={position.unrealised_pnl}
                display={usd(position.unrealised_pnl, { signed: true })}
                signed
              />
            </dd>
          </div>
        </dl>
      ) : (
        <p className="text-sm text-ink-3">No position is open.</p>
      )}
    </Panel>
  );
}
