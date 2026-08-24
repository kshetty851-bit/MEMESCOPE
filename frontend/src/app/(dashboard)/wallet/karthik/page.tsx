"use client";

import { useMemo } from "react";
import { EntriesPausedBanner } from "@/components/paper/entries-paused-banner";

import { WalletSwitch } from "@/components/paper/wallet-switch";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Label, Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat } from "@/components/ui/stat";
import { ErrorState } from "@/components/ui/states";
import {
  useKarthikPositions,
  useKarthikSkipped,
  useKarthikWallet,
} from "@/hooks/use-karthik";
import { duration, exitLabel, multiple, price, skipLabel } from "@/lib/karthik";
import { clock, formatDelay, pct, stamp, tone, usd } from "@/lib/paper";
import type { KarthikPosition, KarthikSkipped } from "@/types/karthik";

/**
 * THE KARTHIK PAPER WALLET
 *
 * A second paper experiment, deliberately simpler than the first, and shown on
 * its own page so no figure here can ever be read as the Original wallet's.
 * They share no capital, no positions and no history.
 *
 * The strategy is printed at the top at full size rather than tucked into a
 * tooltip. Every number below only means something against the rule that
 * produced it, and the rule is four clauses long: $10 per new Track Record
 * token, sell everything at 1.25x, no stop loss, no time exit.
 *
 * Like the Original wallet, this page is built to be able to report a **loss**
 * prominently. A wallet with no stop is a wallet that will hold losers to zero,
 * and the `Dead / zero` count is shown at the same size as the wins.
 *
 * Every figure is derived. Where no observation supports a number it renders
 * "—", never zero: "we have not measured this" and "this is zero" are different
 * claims, and only one of them belongs to a position nobody has priced.
 */

function timeCell(iso: string | null) {
  const shown = clock(iso);
  if (!shown) return <span className="text-ink-3">NOT AVAILABLE</span>;
  return (
    <span title={stamp(iso) ?? undefined} className="tabular-nums">
      {shown}
    </span>
  );
}

function num(value: string | null, className?: string) {
  if (value === null) return <span className="text-ink-3">—</span>;
  return <span className={`tabular-nums ${className ?? ""}`}>{value}</span>;
}

function signed(value: string | null) {
  if (value === null) return <span className="text-ink-3">—</span>;
  const sign = tone(value);
  return (
    <span
      className={`tabular-nums ${
        sign === "positive" ? "text-up" : sign === "negative" ? "text-down" : ""
      }`}
    >
      {usd(value)}
    </span>
  );
}

function token(position: KarthikPosition) {
  return (
    <div className="flex min-w-0 flex-col">
      <span className="truncate font-medium text-ink">
        {position.symbol ?? position.mint_address.slice(0, 8)}
      </span>
      <span className="truncate font-mono text-[11px] text-ink-3">
        {position.mint_address}
      </span>
    </div>
  );
}

const OPEN_COLUMNS: Column<KarthikPosition>[] = [
  { key: "token", header: "Token", width: "180px", pinned: true, cell: token },
  {
    key: "detected",
    header: "Detected",
    cell: (row) => timeCell(row.detected_at),
  },
  {
    key: "track_record",
    header: "Track record",
    cell: (row) => timeCell(row.track_record_at),
  },
  { key: "entry_time", header: "Entry", cell: (row) => timeCell(row.opened_at) },
  {
    key: "delay",
    header: "Entry delay",
    align: "right",
    // Measured from the Track Record admission, because that is the event this
    // wallet trades. The detection delay is on the row too, in the title.
    cell: (row) => (
      <span
        title={
          row.detection_delay_seconds === null
            ? "No discovery record, so the delay from first sight is unavailable"
            : `${formatDelay(row.detection_delay_seconds)} from first detection`
        }
      >
        {num(formatDelay(row.track_record_delay_seconds))}
      </span>
    ),
  },
  {
    key: "entry_price",
    header: "Entry",
    align: "right",
    cell: (row) => num(price(row.entry_price)),
  },
  {
    key: "current_price",
    header: "Current",
    align: "right",
    cell: (row) => num(price(row.current_price)),
  },
  {
    key: "current_multiple",
    header: "Multiple",
    align: "right",
    cell: (row) => num(multiple(row.current_multiple)),
  },
  {
    key: "target",
    header: "Target",
    align: "right",
    // The rule, on every row. Constant by design: there is one target and it
    // never moves, which is exactly what a reader should be able to see.
    cell: (row) => (
      <span className="tabular-nums" title={`${price(row.target_price)}`}>
        {multiple(row.target_multiple)}
      </span>
    ),
  },
  {
    key: "value",
    header: "Value",
    align: "right",
    cell: (row) => num(usd(row.current_value)),
  },
  {
    key: "pnl",
    header: "P&L",
    align: "right",
    cell: (row) => signed(row.unrealized_pnl),
  },
  {
    key: "age",
    header: "Age",
    align: "right",
    cell: (row) => num(duration(row.age_seconds)),
  },
];

const CLOSED_COLUMNS: Column<KarthikPosition>[] = [
  { key: "token", header: "Token", width: "180px", pinned: true, cell: token },
  { key: "detected", header: "Detected", cell: (row) => timeCell(row.detected_at) },
  {
    key: "track_record",
    header: "Track record",
    cell: (row) => timeCell(row.track_record_at),
  },
  { key: "entry_time", header: "Entry", cell: (row) => timeCell(row.opened_at) },
  { key: "exit_time", header: "Exit", cell: (row) => timeCell(row.closed_at) },
  {
    key: "hold",
    header: "Hold",
    align: "right",
    cell: (row) => num(duration(row.hold_seconds)),
  },
  {
    key: "entry_price",
    header: "Entry",
    align: "right",
    cell: (row) => num(price(row.entry_price)),
  },
  {
    key: "exit_price",
    header: "Exit",
    align: "right",
    cell: (row) => num(price(row.exit_price)),
  },
  {
    key: "exit_multiple",
    header: "Exit x",
    align: "right",
    cell: (row) => num(multiple(row.exit_multiple)),
  },
  {
    key: "pnl",
    header: "P&L",
    align: "right",
    cell: (row) => signed(row.realized_pnl),
  },
  {
    key: "reason",
    header: "Exit reason",
    // The evidence behind the close, on hover. A `dead_zero` row carries the
    // provider's own report; a target carries the price and the depth it sold
    // into. Neither is prose composed here.
    cell: (row) => (
      <span
        title={row.exit_evidence ?? undefined}
        className={
          row.exit_reason === "dead_zero"
            ? "text-down"
            : row.exit_reason === "target_1_25x"
              ? "text-up"
              : undefined
        }
      >
        {exitLabel(row.exit_reason) ?? "—"}
      </span>
    ),
  },
];

const SKIPPED_COLUMNS: Column<KarthikSkipped>[] = [
  {
    key: "token",
    header: "Token",
    width: "260px",
    pinned: true,
    cell: (row) => (
      <span className="font-mono text-[11px] text-ink-2">{row.mint_address}</span>
    ),
  },
  {
    key: "track_record",
    header: "Track record time",
    cell: (row) => timeCell(row.track_record_at),
  },
  { key: "reason", header: "Reason", cell: (row) => skipLabel(row.reason) ?? row.reason },
];

export default function KarthikWalletPage() {
  const wallet = useKarthikWallet();
  const positions = useKarthikPositions();
  const skipped = useKarthikSkipped();

  const items = useMemo(() => positions.data?.items ?? [], [positions.data]);
  const open = useMemo(() => items.filter((item) => item.status === "open"), [items]);
  const closed = useMemo(() => items.filter((item) => item.status === "closed"), [items]);

  if (wallet.isError) {
    return (
      <ErrorState
        body="The Karthik wallet is not responding. Positions already recorded are safe — this view will recover on its own."
        onRetry={() => void wallet.refetch()}
      />
    );
  }

  if (wallet.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 rounded-md" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-20 rounded-md" />
          ))}
        </div>
      </div>
    );
  }

  const header = (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <Label>Paper wallet</Label>
        <h1 className="mt-2 text-lg font-semibold text-ink">Karthik Paper Wallet</h1>
        {/* The rule, at full size. Served by the API so the sentence and the
            trades come from the same place and cannot drift apart. */}
        <p className="mt-1 text-sm font-medium text-ink-2">{wallet.data.strategy}</p>
        <p className="mt-2 max-w-2xl text-sm text-ink-3">{wallet.data.disclosure}</p>
      </div>
      <WalletSwitch />
    </header>
  );

  if (!wallet.data.activated) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <Panel density="compact" className="border-warn/20 bg-warn/[0.03]">
          <p className="text-sm leading-relaxed text-ink-2">
            Karthik has not been activated in this environment, so it holds no capital and
            has taken no position. This is a configuration state, not a result — a wallet
            that traded nothing and a wallet that was never started are different things,
            and this is the second.
          </p>
        </Panel>
      </div>
    );
  }

  const m = wallet.data.metrics!;

  return (
    <div className="flex flex-col gap-6">
      {header}

      {wallet.data.entries_paused ? (
        <EntriesPausedBanner reason={wallet.data.pause_reason} />
      ) : null}

      {/* When the wallet started is the eligibility rule, not decoration: every
          token admitted to the Track Record after this instant is Karthik's,
          and every token admitted before it never was. */}
      <Panel density="compact" className="border-line-strong bg-raised/40">
        <p className="text-sm text-ink">
          Activated {new Date(wallet.data.activated_at!).toLocaleString()} · trades only
          tokens that entered the Track Record after that instant
        </p>
        <p className="mt-1 text-xs text-ink-3">
          Historical backfill: {m.historical_backfill}. Trade size{" "}
          {usd(wallet.data.trade_size)} · take profit{" "}
          {wallet.data.take_profit_multiple}x, whole position · no stop loss · no time exit.
          {wallet.data.entries_paused
            ? " New entries are paused; open positions are still monitored and can still exit."
            : ""}
        </p>
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Full equity"
          display={usd(m.full_equity)}
          size="lg"
          hint={`from ${usd(m.starting_capital)} starting capital`}
        />
        <Stat
          label="Return"
          display={pct(m.return_pct)}
          size="lg"
          tone={
            tone(m.return_pct) === "positive"
              ? "up"
              : tone(m.return_pct) === "negative"
                ? "down"
                : "default"
          }
          hint="Cash plus the market value of the open book"
        />
        <Stat
          label="Available cash"
          display={usd(m.cash)}
          size="lg"
          hint="Below one trade size, an arriving opportunity is missed permanently"
        />
        <Stat
          label="Capital allocated"
          display={usd(m.capital_allocated)}
          size="lg"
          hint="Cost basis of the open book, not its market value"
        />
        <Stat label="Realised P&L" display={usd(m.realized_pnl)} />
        <Stat label="Unrealised P&L" display={usd(m.unrealized_pnl)} />
        <Stat label="Open positions" value={m.open_positions} />
        <Stat label="Closed positions" value={m.closed_positions} />
        <Stat label="Targets hit" value={m.targets_hit} />
        {/* Shown at the same size as the wins. A wallet with no stop loss will
            hold losers all the way down, and hiding that would be marketing. */}
        <Stat label="Dead / zero" value={m.dead_zero_count} />
        <Stat
          label="Win rate"
          display={m.win_rate_pct === null ? null : `${m.win_rate_pct}%`}
          hint={m.win_rate_pct === null ? "No trade has finished yet" : undefined}
        />
        <Stat
          label="Average hold"
          display={duration(m.average_hold_seconds)}
          hint={m.average_hold_seconds === null ? "No trade has finished yet" : undefined}
        />
      </div>

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>Experiment flow</PanelTitle>
        </PanelHeader>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Stat
            label="Track record opportunities"
            value={m.track_record_opportunities}
            hint="Admitted since activation"
          />
          <Stat label="Entered" value={m.entered} />
          <Stat
            label="Skipped — insufficient cash"
            value={m.skipped_insufficient_cash}
            hint="Permanent. Never queued for later"
          />
          <Stat
            label="Skipped — no market"
            value={m.skipped_no_market}
            hint="No fresh, tradeable price at the decision point"
          />
          <Stat
            label="Capture rate"
            display={m.capture_rate_pct === null ? null : `${m.capture_rate_pct}%`}
            hint={m.capture_rate_pct === null ? "No opportunity yet" : "Entered ÷ opportunities"}
          />
        </div>
      </Panel>

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>Open positions</PanelTitle>
        </PanelHeader>
        <DataTable
          columns={OPEN_COLUMNS}
          rows={open}
          getRowId={(row) => row.mint_address}
          caption="Karthik open positions"
          minWidth="1240px"
          isPending={positions.isPending}
          empty="No open position. Karthik enters on the next token to reach the Track Record."
        />
      </Panel>

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>Closed positions</PanelTitle>
        </PanelHeader>
        <DataTable
          columns={CLOSED_COLUMNS}
          rows={closed}
          getRowId={(row) => row.mint_address}
          caption="Karthik closed positions"
          minWidth="1240px"
          isPending={positions.isPending}
          empty="No trade has finished. With no stop and no time exit, a position ends only at 1.25x or when its pool is gone."
        />
      </Panel>

      <Panel density="compact">
        <PanelHeader>
          <PanelTitle>Skipped opportunities</PanelTitle>
        </PanelHeader>
        <DataTable
          columns={SKIPPED_COLUMNS}
          rows={skipped.data?.items ?? []}
          getRowId={(row) => row.mint_address}
          caption="Karthik skipped opportunities"
          minWidth="720px"
          isPending={skipped.isPending}
          empty="Nothing skipped. Every Track Record token since activation was entered."
        />
      </Panel>
    </div>
  );
}
