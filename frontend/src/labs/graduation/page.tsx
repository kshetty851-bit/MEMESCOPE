"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import { useGraduationStatus } from "./hooks";
import type {
  Funnel,
  PaperBook,
  PaperPosition,
  RecentToken,
} from "./types";

/**
 * GRADUATION LAB
 *
 * pump.fun tokens on their way up the bonding curve, and what happens in the
 * hour after they graduate. A STATUS BOARD, not a strategy: it reports what
 * the recorder has seen and ranks nothing.
 *
 * Every figure is computed on the backend. Nothing here applies a threshold —
 * a rule written in the page would be a second, unpublished rule competing
 * with the one the recorder followed.
 */

const STAGES: { key: keyof Funnel; label: string; note: string }[] = [
  { key: "seen", label: "Seen", note: "admitted from the launch feed" },
  { key: "crossed_70", label: "70%", note: "tracked from here" },
  { key: "crossed_80", label: "80%", note: "" },
  { key: "crossed_90", label: "90%", note: "" },
  { key: "crossed_95", label: "95%", note: "" },
  { key: "graduated", label: "Graduated", note: "curve filled" },
];

function pct(part: number, whole: number): string {
  if (!whole) return "—";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

function progress(value: string | null): string {
  if (value === null) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-ink-dim">
        {label}
      </span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {note ? <span className="text-xs text-ink-dim">{note}</span> : null}
    </div>
  );
}

function TokenRow({ token }: { token: RecentToken }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2 pr-3 font-medium">
        {token.symbol ?? <span className="text-ink-dim">unnamed</span>}
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-ink-dim">
        {shortenAddress(token.mint)}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums">
        {progress(token.max_progress_pct)}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-ink-dim">
        {token.sample_count}
      </td>
      <td className="py-2 text-right">
        {token.migrated ? (
          <span className="rounded-full bg-up/15 px-2 py-0.5 text-[11px] text-up">
            graduated
          </span>
        ) : token.tracked ? (
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] text-accent">
            tracking
          </span>
        ) : (
          <span className="text-[11px] text-ink-dim">watching</span>
        )}
      </td>
    </tr>
  );
}

function signed(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value) * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function usd(value: string | number | null): string {
  if (value === null) return "—";
  const n = Number(value);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function signedUsd(value: string | null): string {
  if (value === null) return "—";
  return `${Number(value) >= 0 ? "+" : ""}${usd(value)}`;
}

const dexscreener = (mint: string) =>
  `https://dexscreener.com/solana/${mint}`;

/**
 * One trade. The mint is rendered in FULL and linked to the very feed the
 * marks come from, so every figure in the row can be checked against its
 * source rather than taken on trust.
 */
function TradeRow({ p, closed }: { p: PaperPosition; closed: boolean }) {
  const pnl = p.pnl_usd === null ? null : Number(p.pnl_usd);
  const tone =
    pnl === null ? "" : pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "";
  const held = closed
    ? Math.round(
        (new Date(p.closed_at!).getTime() - new Date(p.opened_at).getTime()) /
          60000,
      )
    : null;
  return (
    <tr className="border-t border-line align-top">
      <td className="py-2 pr-3">
        <a
          href={dexscreener(p.mint)}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-accent"
        >
          <span className="font-medium">
            {p.name ?? p.symbol ?? "unnamed"}
            {p.name && p.symbol ? (
              <span className="ml-1 text-ink-dim">{p.symbol}</span>
            ) : null}
          </span>
          <span className="block break-all font-mono text-[10px] leading-tight text-ink-dim">
            {p.mint}
          </span>
        </a>
      </td>
      <td className="py-2 pr-3 text-right tabular-nums">
        {usd(p.notional_usd)}
      </td>
      <td className={`py-2 pr-3 text-right font-medium tabular-nums ${tone}`}>
        {signedUsd(p.pnl_usd)}
      </td>
      <td className={`py-2 pr-3 text-right tabular-nums ${tone}`}>
        {signed(p.net_return)}
      </td>
      <td className="py-2 text-right text-[11px] text-ink-dim">
        {closed ? (
          <>
            {p.close_reason}
            <span className="block">{held}m held</span>
          </>
        ) : (
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-accent">
            open
          </span>
        )}
      </td>
    </tr>
  );
}

function TradeTable({
  rows,
  closed,
  empty,
}: {
  rows: PaperPosition[];
  closed: boolean;
  empty: string;
}) {
  if (!rows.length) return <p className="text-xs text-ink-dim">{empty}</p>;
  const total = rows.reduce((a, p) => a + Number(p.pnl_usd ?? 0), 0);
  // Summed, not `count x rows[0]`: the sizes are equal today and the sum
  // stays right if they ever are not.
  const deployed = rows.reduce((a, p) => a + Number(p.notional_usd), 0);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
            <th className="pb-2 pr-3 font-medium">Token / mint</th>
            <th className="pb-2 pr-3 text-right font-medium">Size</th>
            <th className="pb-2 pr-3 text-right font-medium">
              {closed ? "Realised P&L" : "Unrealised P&L"}
            </th>
            <th className="pb-2 pr-3 text-right font-medium">Return</th>
            <th className="pb-2 text-right font-medium">
              {closed ? "Exit" : "State"}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p: PaperPosition) => (
            <TradeRow key={p.mint} p={p} closed={closed} />
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-line text-[11px] text-ink-dim">
            <td className="pt-2 pr-3">
              {rows.length} {closed ? "closed" : "open"}
            </td>
            <td className="pt-2 pr-3 text-right tabular-nums">
              {usd(String(deployed))}
            </td>
            <td
              className={`pt-2 pr-3 text-right font-medium tabular-nums ${
                total > 0 ? "text-up" : total < 0 ? "text-down" : ""
              }`}
            >
              {signedUsd(String(total))}
            </td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function PaperPanel({ book }: { book: PaperBook }) {
  const pnl = Number(book.pnl_usd);
  const tone = pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "";
  const side = (Number(book.cost_pct_per_side) * 100).toFixed(2);
  const round = (Number(book.cost_pct_per_side) * 200).toFixed(2);
  // Derived, not written down: a hardcoded "both closed losses" was wrong
  // within the hour, and a stale number in a paragraph about honesty is
  // worse than no number.
  const worst = book.closed_trades.reduce(
    (w, p) => Math.min(w, Number(p.net_return ?? 0)),
    0,
  );
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Paper book (forward)</PanelTitle>
      </PanelHeader>
      <div className="flex flex-col gap-4 p-4">
        <p className="max-w-[65ch] text-xs text-ink-dim">
          Rules fixed before the outcome was known: buy the pool open,{" "}
          {usd(book.notional_usd)} a position, up to {book.max_slots} at once,
          and leave on whichever comes first — a{" "}
          {(Number(book.trailing_pct) * 100).toFixed(0)}% trailing stop off
          the running peak, a {Number(book.take_profit_x)}x target, or{" "}
          {book.max_hold_minutes} minutes, because the price series ends
          there. The stop is checked before the target: both can be true on
          one sample and minute data cannot say which filled, so the loss is
          taken. Nothing is tuned after the fact — that is the whole point of
          running it forward. Positions are sized in dollars and converted at
          the SOL/USD rate observed when each one opened.
        </p>
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <Stat
            label="Equity"
            value={usd(book.equity_usd)}
            note={`from ${usd(book.starting_usd)} start`}
          />
          <Stat
            label="Realised"
            value={signedUsd(book.realised_usd)}
            note={`${signedUsd(book.unrealised_usd)} open`}
          />
          <Stat
            label="Open"
            value={`${book.open_positions}/${book.max_slots}`}
            note={`${book.closed_positions} closed`}
          />
          <Stat
            label="Wins"
            value={
              book.closed_positions
                ? `${((book.wins / book.closed_positions) * 100).toFixed(0)}%`
                : "—"
            }
            note={`${book.wins} of ${book.closed_positions}`}
          />
        </div>
        <p className={`text-sm font-semibold tabular-nums ${tone}`}>
          {signedUsd(book.pnl_usd)} ({Number(book.return_pct) >= 0 ? "+" : ""}
          {(Number(book.return_pct) * 100).toFixed(2)}%) against the{" "}
          {usd(book.starting_usd)} book
        </p>

        <div className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
            Open trades — marked to the last price, nothing banked
          </h3>
          <TradeTable
            rows={book.open_trades}
            closed={false}
            empty="No open positions. The book opens one per graduating token as pools appear."
          />
        </div>

        <div className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
            Closed trades — banked, and the only figures that count
          </h3>
          <TradeTable
            rows={book.closed_trades}
            closed
            empty="Nothing closed yet. Until a position exits, this book has proved nothing."
          />
        </div>

        {/* The question this page will be asked is "would a real wallet have
            made this?", so it is answered here rather than left implied. */}
        <div className="max-w-[65ch] rounded-md border border-line p-3 text-xs text-ink-dim">
          <p className="mb-1 font-semibold text-ink">
            Would a real wallet have made this?
          </p>
          <p>
            Close, but not to the cent, and the difference cuts both ways.
            Every price above is a real trade printed on-chain and read from
            the same DexScreener feed the rest of this site uses — nothing is
            simulated — and each leg is charged {side}% ({round}% round trip)
            for the pump fee, assumed slippage and priority fee. What a live
            wallet would hit differently:
          </p>
          <ul className="mt-1 list-disc pl-4">
            <li>
              Slippage here is <em>assumed</em>, not measured. These pools run
              deep enough that a {usd(book.notional_usd)} order moves the price
              well under the assumption, so the charge is more likely too harsh
              than too kind.
            </li>
            <li>
              The stop is checked once a minute against a sampled price, so an
              exit fills at the next price seen, not at the stop level. A token
              that collapses between samples fills far below the stop
              {worst < -Number(book.trailing_pct) ? (
                <>
                  {" "}
                  — the worst exit here landed at {(worst * 100).toFixed(0)}%
                  against a{" "}
                  {(Number(book.trailing_pct) * 100).toFixed(0)}% stop
                </>
              ) : null}
              . A live stop order would not have waited for the next sample,
              but on a pool draining that fast it may not have filled either.
            </li>
            <li>
              Nothing here can fail, get sandwiched, or miss a block. A real
              buy at a pool open competes with bots for the same slot.
            </li>
            <li>
              The {Number(book.take_profit_x)}x target is measured against the
              price paid, and the exit pays its own cost, so it banks about{" "}
              {(
                (Number(book.take_profit_x) *
                  (1 - Number(book.cost_pct_per_side)) -
                  1) *
                100
              ).toFixed(0)}
              %, not{" "}
              {((Number(book.take_profit_x) - 1) * 100).toFixed(0)}%.
            </li>
          </ul>
          <p className="mt-1">
            So treat these as what the rules would have earned at the prices
            the market actually printed — honest, and not a promise.
          </p>
        </div>
      </div>
    </Panel>
  );
}

export function GraduationLabPage() {
  const { data, isLoading, isError, refetch } = useGraduationStatus();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-6">
        <ErrorState
          title="Could not load the Graduation Lab"
          body="The status endpoint did not answer."
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (!data.running) {
    return (
      <div className="p-6">
        <EmptyState
          title="The Graduation Lab is not running"
          body="LAB_GRADUATION_ENABLED is off, so the recorder is not connected. This is not the same as the lab running and finding nothing — no tokens are being watched at all."
        />
      </div>
    );
  }

  const { funnel, signals } = data;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Graduation Lab</h1>
        <p className="max-w-[65ch] text-sm text-ink-dim">
          pump.fun tokens climbing the bonding curve, recorded from the free
          launch feed and a {data.poll_interval_s}s chain poll. Watching only —
          there is no book and nothing is ranked.
        </p>
      </header>

      {data.recorder_stalled ? (
        <div className="rounded border border-danger/50 bg-danger/10 p-4">
          <p className="text-sm font-semibold text-danger">
            The recorder is not reading the chain
          </p>
          <p className="mt-1 max-w-[65ch] text-xs text-danger">
            {data.watch_set} tokens are being watched but nothing has been read
            for{" "}
            {data.seconds_since_chain_read === null
              ? "any recorded time"
              : `${data.seconds_since_chain_read}s`}
            , against a {data.stall_threshold_s}s threshold. The counts below
            are what was already stored — they will look normal while nothing
            new arrives. Usual causes: a revoked or wrong RPC key, an
            unreachable node, or a stopped recorder.
          </p>
        </div>
      ) : null}

      <Panel>
        <PanelHeader>
          <PanelTitle>Right now</PanelTitle>
        </PanelHeader>
        <div className="grid grid-cols-2 gap-6 p-4 sm:grid-cols-4">
          <Stat
            label="Watch set"
            value={`${data.watch_set}`}
            note={`of ${data.watch_set_max} max`}
          />
          <Stat
            label="RPC calls / min"
            value={`${data.rpc_calls_per_minute}`}
            note="derived from the watch set"
          />
          <Stat
            label="New tokens / hr"
            value={`${data.tokens_last_hour}`}
            note="admitted from the feed"
          />
          <Stat
            label="Curve samples / hr"
            value={`${data.samples_last_hour}`}
            note="written only when reserves move"
          />
          <Stat
            label="Last chain read"
            value={
              data.seconds_since_chain_read === null
                ? "never"
                : `${data.seconds_since_chain_read}s ago`
            }
            note={data.recorder_stalled ? "STALLED" : "polling normally"}
          />
        </div>
      </Panel>

      <Panel>
        <PanelHeader>
          <PanelTitle>How far they get</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-4">
          <div className="flex min-w-[520px] items-end gap-2">
            {STAGES.map((stage) => {
              const value = funnel[stage.key];
              const share = funnel.seen ? value / funnel.seen : 0;
              return (
                <div key={stage.key} className="flex flex-1 flex-col gap-2">
                  <div className="flex h-28 items-end">
                    <div
                      className="w-full rounded-t bg-accent/70"
                      style={{ height: `${Math.max(share * 100, 1.5)}%` }}
                    />
                  </div>
                  <div className="flex flex-col gap-0.5 border-t border-line pt-2">
                    <span className="text-sm font-semibold tabular-nums">
                      {value}
                    </span>
                    <span className="text-[11px] uppercase tracking-wider text-ink-dim">
                      {stage.label}
                    </span>
                    <span className="text-[11px] tabular-nums text-ink-dim">
                      {pct(value, funnel.seen)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Graduation signals</PanelTitle>
          </PanelHeader>
          <div className="flex flex-col gap-3 p-4">
            <p className="max-w-[60ch] text-xs text-ink-dim">
              Two independent sources report a graduation — the migration feed
              and the curve account&rsquo;s own <code>complete</code> flag —
              and either can arrive alone. Counting one would undercount.
            </p>
            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Both agreed</dt>
                <dd className="tabular-nums">{signals.both}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Feed only</dt>
                <dd className="tabular-nums">{signals.feed_only}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Chain only</dt>
                <dd className="tabular-nums">{signals.chain_only}</dd>
              </div>
            </dl>
          </div>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>What has been recorded</PanelTitle>
          </PanelHeader>
          <div className="flex flex-col gap-3 p-4">
            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Curve samples</dt>
                <dd className="tabular-nums">{data.curve_samples}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Checkpoints</dt>
                <dd className="tabular-nums">{data.checkpoints}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">…of those, with reserves</dt>
                <dd className="tabular-nums">
                  {data.checkpoints_with_reserves}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Post-graduation samples</dt>
                <dd className="tabular-nums">{data.postgrad_samples}</dd>
              </div>
            </dl>
            {!data.quote_side_trusted ? (
              <p className="max-w-[60ch] rounded border border-warn/40 bg-warn/10 p-3 text-xs text-warn">
                The curve&rsquo;s SOL side is not modelled correctly yet, so
                reserve and market-cap figures should not be relied on. The
                token side is sound — progress and the checkpoints are
                unaffected, and they are what this lab records.
              </p>
            ) : null}
          </div>
        </Panel>
      </div>

      {data.paper.running ? <PaperPanel book={data.paper} /> : null}

      <Panel>
        <PanelHeader>
          <PanelTitle>Furthest up the curve</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-4">
          {data.recent.length === 0 ? (
            <EmptyState
              title="Nothing has moved yet"
              body="No watched token has recorded a progress reading."
            />
          ) : (
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
                  <th className="pb-2 pr-3 font-medium">Symbol</th>
                  <th className="pb-2 pr-3 font-medium">Mint</th>
                  <th className="pb-2 pr-3 text-right font-medium">Peak</th>
                  <th className="pb-2 pr-3 text-right font-medium">Samples</th>
                  <th className="pb-2 text-right font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((token) => (
                  <TokenRow key={token.mint} token={token} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>

      <p className="text-xs text-ink-dim">
        Polling {data.rpc_host} · recorder refreshes every{" "}
        {data.poll_interval_s}s · this page every 30s
      </p>
    </div>
  );
}
